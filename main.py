import asyncio
import hashlib
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="VIES VAT Validation Service",
    description="Microservice zur Validierung von EU USt-IdNr. über VIES + BZSt eVatR",
    version="1.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Cache (in-memory, TTL-basiert)
# ---------------------------------------------------------------------------
CACHE: dict[str, dict] = {}
CACHE_TTL_SECONDS = 3600  # 1 Stunde

# ---------------------------------------------------------------------------
# Request-History (in-memory, max 1000 Einträge)
# ---------------------------------------------------------------------------
HISTORY: list[dict] = []
HISTORY_MAX = 1000

VIES_BASE = "https://ec.europa.eu/taxation_customs/vies/rest-api"
BZST_BASE = "https://api.evatr.vies.bzst.de/app/v1"
OWN_VAT_ID = os.environ.get("OWN_VAT_ID", "")  # Eigene deutsche USt-IdNr.

# VIES userError-Codes, die KEINE inhaltliche Aussage über die VAT-Nummer machen,
# sondern auf Verfügbarkeitsprobleme des EU-/MS-Systems hindeuten. Bei diesen Codes
# ist isValid: false NICHT als „ungültige USt-IdNr." zu interpretieren.
VIES_TRANSIENT_ERRORS = {
    "MS_MAX_CONCURRENT_REQ",     # Mitgliedstaat-System hat Anfrage wegen zu vieler paralleler Anfragen abgewiesen
    "MS_UNAVAILABLE",            # Mitgliedstaat-System nicht erreichbar
    "SERVICE_UNAVAILABLE",       # VIES-Service insgesamt nicht erreichbar
    "TIMEOUT",                   # Antwort vom Mitgliedstaat-System nicht rechtzeitig
    "GLOBAL_MAX_CONCURRENT_REQ", # globales VIES-Rate-Limit
    "SERVER_BUSY",               # Server überlastet
}

VIES_RETRY_ATTEMPTS = 4   # inkl. Erstversuch
VIES_RETRY_BACKOFF = 1.5  # Sekunden, exponentiell

# Spanien (ES) liefert über VIES bewusst keine Stammdaten. Als Sekundärquelle für
# Name/Adresse nutzen wir die öffentlich zugängliche einforma.com-Unternehmensseite
# (best-effort, nicht-offiziell — siehe README).
EINFORMA_BASE = "https://www.einforma.com"
EINFORMA_PATH = "/servlet/app/portal/ENTP/prod/ETIQUETA_EMPRESA/nif"
EINFORMA_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
ES_REGISTRY_CACHE_TTL_SECONDS = 86400  # 24 h — Registerdaten ändern sich selten

# ---------------------------------------------------------------------------
# Land → EU-Ländercode Mapping
# ---------------------------------------------------------------------------
COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "austria": "AT", "österreich": "AT",
    "belgium": "BE", "belgien": "BE", "belgique": "BE",
    "bulgaria": "BG", "bulgarien": "BG",
    "croatia": "HR", "kroatien": "HR", "hrvatska": "HR",
    "cyprus": "CY", "zypern": "CY",
    "czech republic": "CZ", "czechia": "CZ", "tschechien": "CZ",
    "denmark": "DK", "dänemark": "DK", "danmark": "DK",
    "estonia": "EE", "estland": "EE", "eesti": "EE",
    "finland": "FI", "finnland": "FI", "suomi": "FI",
    "france": "FR", "frankreich": "FR",
    "germany": "DE", "deutschland": "DE",
    "greece": "EL", "griechenland": "EL",
    "hungary": "HU", "ungarn": "HU", "magyarország": "HU",
    "ireland": "IE", "irland": "IE",
    "italy": "IT", "italien": "IT", "italia": "IT",
    "latvia": "LV", "lettland": "LV", "latvija": "LV",
    "lithuania": "LT", "litauen": "LT", "lietuva": "LT",
    "luxembourg": "LU", "luxemburg": "LU",
    "malta": "MT",
    "netherlands": "NL", "niederlande": "NL", "nederland": "NL",
    "poland": "PL", "polen": "PL", "polska": "PL",
    "portugal": "PT",
    "romania": "RO", "rumänien": "RO", "românia": "RO",
    "slovakia": "SK", "slowakei": "SK", "slovensko": "SK",
    "slovenia": "SI", "slowenien": "SI", "slovenija": "SI",
    "spain": "ES", "spanien": "ES", "españa": "ES",
    "sweden": "SE", "schweden": "SE", "sverige": "SE",
    "northern ireland": "XI",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class VatRequest(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    vat_number: str = Field(..., min_length=2, max_length=12)


class BulkVatRequest(BaseModel):
    items: list[VatRequest] = Field(..., min_items=1, max_items=50)


class VerifyRequest(BaseModel):
    """Kundendaten zur Gegenprüfung mit VIES."""
    vat_number: str = Field(..., description="USt-IdNr. (mit oder ohne Länderprefix)")
    company_name: Optional[str] = Field(None, description="Firmenname vom Kunden")
    address: Optional[str] = Field(None, description="Adresse vom Kunden (eine Zeile oder mehrzeilig)")
    postal_code: Optional[str] = Field(None, description="PLZ vom Kunden")
    city: Optional[str] = Field(None, description="Stadt vom Kunden")
    country: Optional[str] = Field(None, description="Land (Name oder Code, z.B. 'Estonia' oder 'EE')")


class BzstVerifyRequest(BaseModel):
    """Qualifizierte Bestätigungsabfrage über BZSt eVatR."""
    vat_number: str = Field(..., description="Zu prüfende USt-IdNr. (mit oder ohne Länderprefix)")
    company_name: str = Field(..., description="Firmenname inkl. Rechtsform")
    city: str = Field(..., description="Ort")
    postal_code: Optional[str] = Field(None, description="PLZ")
    street: Optional[str] = Field(None, description="Straße mit Hausnummer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cache_key(country_code: str, vat_number: str) -> str:
    raw = f"{country_code}:{vat_number}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached(key: str) -> Optional[dict]:
    entry = CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL_SECONDS:
        return entry["data"]
    if entry:
        del CACHE[key]
    return None


def _set_cache(key: str, data: dict) -> None:
    CACHE[key] = {"data": data, "ts": time.time()}


def _log(entry: dict) -> None:
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    HISTORY.append(entry)
    if len(HISTORY) > HISTORY_MAX:
        HISTORY.pop(0)


def _normalize(text: str) -> str:
    """Normalisiert Text für Fuzzy-Vergleich: lowercase, Umlaute auflösen, Sonderzeichen entfernen."""
    text = text.lower().strip()
    # Unicode-Normalisierung (ö → o, ä → a, etc.)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Sonderzeichen und Mehrfach-Leerzeichen entfernen
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _similarity(a: str, b: str) -> float:
    """Einfacher Token-basierter Ähnlichkeitsvergleich (Jaccard auf Wort-Ebene)."""
    if not a or not b:
        return 0.0
    tokens_a = set(_normalize(a).split())
    tokens_b = set(_normalize(b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _contains_match(needle: str, haystack: str) -> bool:
    """Prüft ob die wesentlichen Tokens von needle in haystack enthalten sind."""
    needle_tokens = set(_normalize(needle).split())
    haystack_tokens = set(_normalize(haystack).split())
    if not needle_tokens:
        return False
    return len(needle_tokens & haystack_tokens) / len(needle_tokens) >= 0.5


def _detect_country_code(country: Optional[str], vat_number: str) -> Optional[str]:
    """Erkennt den Ländercode aus Ländername oder VAT-Nummer-Prefix."""
    # Aus VAT-Nummer-Prefix
    prefix_match = re.match(r"^([A-Za-z]{2})", vat_number.strip())
    if prefix_match:
        code = prefix_match.group(1).upper()
        if code in {v for v in COUNTRY_NAME_TO_CODE.values()}:
            return code

    # Aus Ländername
    if country:
        normalized = country.lower().strip()
        if len(normalized) == 2 and normalized.upper() in {v for v in COUNTRY_NAME_TO_CODE.values()}:
            return normalized.upper()
        return COUNTRY_NAME_TO_CODE.get(normalized)

    return None


def _clean_vat_number(vat_number: str, country_code: str) -> str:
    """Entfernt Länderprefix, Leerzeichen, Punkte, Bindestriche aus der VAT-Nummer."""
    cleaned = vat_number.strip().replace(" ", "").replace(".", "").replace("-", "")
    # Länderprefix entfernen falls vorhanden
    if cleaned.upper().startswith(country_code):
        cleaned = cleaned[len(country_code):]
    return cleaned


# ---------------------------------------------------------------------------
# ES Registry-Lookup (einforma.com)
# ---------------------------------------------------------------------------
ES_REGISTRY_CACHE: dict[str, dict] = {}


def _parse_einforma_html(raw: bytes, cif: str) -> Optional[dict]:
    """Extrahiert Stammdaten aus einer einforma.com-Unternehmensseite.

    Die Seite ist ISO-8859-1 kodiert und liefert die relevanten Felder als
    HTML-Snippets in einer Tabellenstruktur. Wir parsen defensiv via Regex —
    wenn einforma die Struktur ändert, geben wir lieber `None` zurück als
    halb-richtige Daten.
    """
    try:
        html = raw.decode("iso-8859-1", errors="replace")
    except Exception:
        return None

    # Hinweis: einforma zeigt für unbekannte CIFs eine Suchseite mit "no se
    # encuentra" / "no encontrada" — in dem Fall haben wir keinen Treffer.
    if re.search(r"no se encuentra|no encontrada|sin resultados", html, re.I):
        return None

    name = None
    m = re.search(r"'nombreEmpresa':\s*'([^']+)'", html)
    if m:
        name = m.group(1).strip()

    # Registrierter Geschäftssitz — einforma nutzt je nach Layout entweder
    # "Domicilio social actual" oder "Dirección social actual".
    street = None
    m = re.search(
        r"(?:Domicilio|Direcci[^<]*)\s+social\s+actual:.*?</strong></td>\s*<td[^>]*>([^<]+?)(?:\s*<a|</td>)",
        html, re.S | re.I,
    )
    if m:
        street = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(",").strip()

    # Localidad: PLZ + Stadt + (Provinz)
    postal_code = None
    city = None
    province = None
    m = re.search(
        r"Localidad:</strong></td>\s*<td[^>]*>\s*(\d{5})\s+([^()<]+?)\s*\(\s*([^)]+?)\s*\)",
        html, re.S | re.I,
    )
    if m:
        postal_code = m.group(1)
        city = m.group(2).strip()
        province = m.group(3).strip()

    # Wenn wir GAR nichts gefunden haben → vermutlich Captcha/Layoutwechsel
    if not (name or street or postal_code or city):
        return None

    return {
        "name": name,
        "street": street,
        "postal_code": postal_code,
        "city": city,
        "province": province,
        "cif": cif.upper(),
    }


async def _query_es_registry(cif: str) -> dict:
    """Holt Stammdaten einer spanischen Firma über einforma.com (öffentliche
    Profilseite, ohne Login). Best-effort — bei Parsefehler/Captcha gibt es
    `found: false` zurück, nie ein HTTPException, damit es als Fallback
    aufgerufen werden kann ohne die Hauptantwort zu killen.
    """
    cif_normalized = cif.strip().upper().replace(" ", "")
    if cif_normalized.startswith("ES"):
        cif_normalized = cif_normalized[2:]

    cached = ES_REGISTRY_CACHE.get(cif_normalized)
    if cached and (time.time() - cached["ts"]) < ES_REGISTRY_CACHE_TTL_SECONDS:
        return {**cached["data"], "cached": True}

    url = f"{EINFORMA_BASE}{EINFORMA_PATH}/{cif_normalized}"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": EINFORMA_UA, "Accept-Language": "es-ES,es;q=0.9"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        return {
            "found": False,
            "cif": cif_normalized,
            "source": "einforma.com",
            "source_url": url,
            "error": f"network: {exc}",
            "cached": False,
        }

    if resp.status_code != 200:
        return {
            "found": False,
            "cif": cif_normalized,
            "source": "einforma.com",
            "source_url": url,
            "error": f"http {resp.status_code}",
            "cached": False,
        }

    parsed = _parse_einforma_html(resp.content, cif_normalized)
    if parsed is None:
        return {
            "found": False,
            "cif": cif_normalized,
            "source": "einforma.com",
            "source_url": url,
            "error": "parse_failed_or_not_found",
            "cached": False,
        }

    data = {
        "found": True,
        "cif": cif_normalized,
        "name": parsed.get("name"),
        "street": parsed.get("street"),
        "postal_code": parsed.get("postal_code"),
        "city": parsed.get("city"),
        "province": parsed.get("province"),
        "source": "einforma.com",
        "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    ES_REGISTRY_CACHE[cif_normalized] = {"data": data, "ts": time.time()}
    return {**data, "cached": False}


BZST_MATCH_CODES = {
    "A": "stimmt überein",
    "B": "stimmt NICHT überein",
    "C": "nicht abgefragt",
    "D": "vom EU-Mitgliedstaat nicht mitgeteilt",
}


async def _query_bzst(
    vat_number: str,
    company_name: str,
    city: str,
    postal_code: Optional[str] = None,
    street: Optional[str] = None,
) -> dict:
    """Qualifizierte Bestätigungsabfrage beim BZSt (eVatR REST API)."""
    if not OWN_VAT_ID:
        raise HTTPException(
            status_code=500,
            detail="OWN_VAT_ID Umgebungsvariable nicht gesetzt. Eigene deutsche USt-IdNr. wird für BZSt-Abfragen benötigt.",
        )

    # VAT-Nummer mit Prefix zusammenbauen falls nötig
    cleaned = vat_number.strip().replace(" ", "").replace(".", "").replace("-", "")

    payload = {
        "anfragendeUstid": OWN_VAT_ID,
        "angefragteUstid": cleaned,
        "firmenname": company_name,
        "ort": city,
    }
    if postal_code:
        payload["plz"] = postal_code
    if street:
        payload["strasse"] = street

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{BZST_BASE}/abfrage", json=payload)

    data = resp.json()

    # BZSt Ergebnis-Codes für Adressfelder
    erg_name = data.get("ergFirmenname")
    erg_street = data.get("ergStrasse")
    erg_plz = data.get("ergPlz")
    erg_city = data.get("ergOrt")

    checks = {}
    if erg_name:
        checks["firmenname"] = {"code": erg_name, "ergebnis": BZST_MATCH_CODES.get(erg_name, erg_name)}
    if erg_street:
        checks["strasse"] = {"code": erg_street, "ergebnis": BZST_MATCH_CODES.get(erg_street, erg_street)}
    if erg_plz:
        checks["plz"] = {"code": erg_plz, "ergebnis": BZST_MATCH_CODES.get(erg_plz, erg_plz)}
    if erg_city:
        checks["ort"] = {"code": erg_city, "ergebnis": BZST_MATCH_CODES.get(erg_city, erg_city)}

    # Gesamtbewertung
    codes = [erg_name, erg_street, erg_plz, erg_city]
    codes = [c for c in codes if c and c not in ("C", "D")]
    if not codes:
        overall = "NICHT_PRÜFBAR"
    elif "B" in codes:
        overall = "ABWEICHUNG"
    else:
        overall = "OK"

    result = {
        "vat_valid": data.get("status") == "evatr-0000",
        "status_code": data.get("status"),
        "vat_number": cleaned,
        "anfrage_zeitpunkt": data.get("anfrageZeitpunkt"),
        "gueltig_ab": data.get("gueltigAb"),
        "gueltig_bis": data.get("gueltigBis"),
        "overall_result": overall,
        "checks": checks,
        "input": payload,
        "bzst_raw": data,
    }

    _log({"type": "bzst", "vat_number": cleaned, "status": data.get("status"), "overall": overall})
    return result


def _classify_vies_response(data: dict) -> str:
    """Bestimmt den Status der VIES-Antwort.

    Rückgabewerte:
      - "valid":       isValid = true → USt-IdNr. ist gültig
      - "unavailable": userError ist transient (MS-System überlastet/down)
                       → KEINE inhaltliche Aussage möglich
      - "invalid":     isValid = false und keine transiente Störung
                       → USt-IdNr. ist (zum Abfragezeitpunkt) ungültig
    """
    user_error = (data.get("userError") or "").upper()
    if data.get("isValid") is True:
        return "valid"
    if user_error in VIES_TRANSIENT_ERRORS:
        return "unavailable"
    return "invalid"


async def _query_vies(country_code: str, vat_number: str) -> dict:
    """Fragt die VIES REST API ab (mit Cache, Retry bei transienten MS-Fehlern).

    Cached werden nur belastbare Ergebnisse (valid/invalid). „unavailable"-Antworten
    werden NICHT gecached und bei Retry-Erschöpfung mit dem letzten userError zurückgegeben.
    """
    key = _cache_key(country_code, vat_number)
    cached = _get_cached(key)
    if cached:
        _log({
            "country_code": country_code,
            "vat_number": vat_number,
            "cached": True,
            "status": cached.get("status"),
            "valid": cached.get("valid"),
        })
        return {**cached, "cached": True}

    url = f"{VIES_BASE}/ms/{country_code}/vat/{vat_number}"

    last_data: Optional[dict] = None
    last_status: Optional[str] = None
    last_http_error: Optional[tuple[int, str]] = None

    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(VIES_RETRY_ATTEMPTS):
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                last_http_error = (599, f"network error: {exc}")
                last_status = "unavailable"
                if attempt < VIES_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(VIES_RETRY_BACKOFF * (2 ** attempt))
                    continue
                break

            if resp.status_code != 200:
                last_http_error = (resp.status_code, resp.text)
                # 5xx als transient behandeln und retry-en, sonst direkt abbrechen
                if 500 <= resp.status_code < 600 and attempt < VIES_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(VIES_RETRY_BACKOFF * (2 ** attempt))
                    continue
                _log({
                    "country_code": country_code,
                    "vat_number": vat_number,
                    "cached": False,
                    "error": last_http_error[1],
                })
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"VIES API error: {last_http_error[1]}",
                )

            last_data = resp.json()
            last_status = _classify_vies_response(last_data)
            if last_status != "unavailable" or attempt == VIES_RETRY_ATTEMPTS - 1:
                break
            await asyncio.sleep(VIES_RETRY_BACKOFF * (2 ** attempt))

    # Wenn wir hier ohne Daten landen, war es ein dauerhaft transienter Netzwerk-/HTTP-Fehler
    if last_data is None:
        result = {
            "valid": False,
            "status": "unavailable",
            "country_code": country_code,
            "vat_number": vat_number,
            "name": "---",
            "address": "---",
            "user_error": last_http_error[1] if last_http_error else "NETWORK_ERROR",
            "request_date": datetime.now(timezone.utc).isoformat(),
            "attempts": VIES_RETRY_ATTEMPTS,
        }
        _log({
            "country_code": country_code,
            "vat_number": vat_number,
            "cached": False,
            "status": "unavailable",
            "valid": False,
            "user_error": result["user_error"],
        })
        return {**result, "cached": False}

    result = {
        "valid": last_status == "valid",
        "status": last_status,
        "country_code": country_code,
        "vat_number": vat_number,
        "name": last_data.get("name", "---") or "---",
        "address": last_data.get("address", "---") or "---",
        "user_error": last_data.get("userError"),
        "request_date": last_data.get("requestDate"),
    }

    # Nur belastbare Ergebnisse cachen — transiente Antworten könnten kurz darauf gültig liefern
    if last_status in ("valid", "invalid"):
        _set_cache(key, result)

    _log({
        "country_code": country_code,
        "vat_number": vat_number,
        "cached": False,
        "status": last_status,
        "valid": result["valid"],
        "user_error": result["user_error"],
    })
    return {**result, "cached": False}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {
        "service": "VIES VAT Validation Service",
        "version": app.version,
        "endpoints": {
            "validate": "GET /vat/{country_code}/{vat_number}",
            "verify": "POST /vat/verify — Kundendaten gegenprüfen (VIES, mit ES-Registry-Fallback)",
            "bzst_verify": "POST /vat/bzst-verify — Qualifizierte Bestätigungsabfrage (BZSt)",
            "bzst_status": "GET /vat/bzst-status — BZSt Statusmeldungen + EU-MS Verfügbarkeit",
            "es_registry": "GET /es/registry/{cif} — Stammdaten zu spanischer Firma (einforma.com)",
            "bulk": "POST /vat/bulk",
            "history": "GET /history",
            "health": "GET /health",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok", "cache_size": len(CACHE), "history_size": len(HISTORY)}


@app.get("/vat/{country_code}/{vat_number}")
async def validate_vat(country_code: str, vat_number: str):
    """Einzelne USt-IdNr. validieren."""
    country_code = country_code.upper().strip()
    vat_number = vat_number.strip().replace(" ", "")
    return await _query_vies(country_code, vat_number)


@app.post("/vat/verify")
async def verify_vat(request: VerifyRequest):
    """Kundendaten gegen VIES prüfen — erkennt Ländercode, bereinigt Nummer, gleicht Name/Adresse ab."""

    # 1. Ländercode ermitteln
    country_code = _detect_country_code(request.country, request.vat_number)
    if not country_code:
        raise HTTPException(
            status_code=400,
            detail="Ländercode konnte nicht ermittelt werden. Bitte 'country' angeben (z.B. 'Estonia' oder 'EE') oder VAT-Nummer mit Prefix senden (z.B. 'EE17238591').",
        )

    # 2. VAT-Nummer bereinigen
    vat_number = _clean_vat_number(request.vat_number, country_code)

    # 3. VIES abfragen
    vies_result = await _query_vies(country_code, vat_number)

    # Länder, die grundsätzlich KEINE Name/Adress-Daten über VIES liefern
    COUNTRIES_WITHOUT_DETAILS = {"DE", "ES", "EE", "NL"}
    vies_status = vies_result.get("status", "invalid")  # "valid" | "invalid" | "unavailable"
    vies_unavailable = vies_status == "unavailable"
    vat_is_invalid = vies_status == "invalid"

    # 4. Abgleich der Kundendaten mit VIES-Ergebnis
    checks = {}
    vies_name = vies_result.get("name", "---")
    vies_address = vies_result.get("address", "---")

    def _missing_data_hint() -> str:
        if vies_unavailable:
            user_error = vies_result.get("user_error") or "unbekannt"
            return (
                f"VIES/Mitgliedstaat-System aktuell nicht abrufbar (userError: {user_error}) — "
                "USt-IdNr. konnte WEDER bestätigt NOCH widerlegt werden. Bitte später erneut prüfen."
            )
        if vat_is_invalid:
            return "USt-IdNr. ist ungültig — VIES liefert deshalb keine Daten"
        if country_code in COUNTRIES_WITHOUT_DETAILS:
            return f"{country_code} liefert keine Daten über VIES"
        return "Keine Daten von VIES zurückgegeben"

    # Name prüfen
    if request.company_name and vies_name != "---":
        name_score = _similarity(request.company_name, vies_name)
        checks["name"] = {
            "customer_input": request.company_name,
            "vies_official": vies_name,
            "similarity": round(name_score, 2),
            "match": "OK" if name_score >= 0.3 else "ABWEICHUNG",
        }
    elif request.company_name and vies_name == "---":
        checks["name"] = {
            "customer_input": request.company_name,
            "vies_official": None,
            "similarity": None,
            "match": "NICHT_PRÜFBAR",
            "hinweis": _missing_data_hint(),
        }

    # Adresse prüfen (Zusammenführung aller Adressfelder vom Kunden)
    customer_address_parts = [
        p for p in [request.address, request.postal_code, request.city] if p
    ]
    customer_address_combined = ", ".join(customer_address_parts)

    if customer_address_combined and vies_address != "---":
        addr_score = _similarity(customer_address_combined, vies_address)
        # Zusätzlich: PLZ und Stadt einzeln gegen VIES-Adresse prüfen
        plz_ok = _contains_match(request.postal_code, vies_address) if request.postal_code else None
        city_ok = _contains_match(request.city, vies_address) if request.city else None

        checks["address"] = {
            "customer_input": customer_address_combined,
            "vies_official": vies_address,
            "similarity": round(addr_score, 2),
            "postal_code_found": plz_ok,
            "city_found": city_ok,
            "match": "OK" if addr_score >= 0.25 else "ABWEICHUNG",
        }
    elif customer_address_combined and vies_address == "---":
        checks["address"] = {
            "customer_input": customer_address_combined,
            "vies_official": None,
            "similarity": None,
            "match": "NICHT_PRÜFBAR",
            "hinweis": _missing_data_hint(),
        }

    # 5. Gesamtbewertung
    if vies_unavailable:
        # VIES konnte keine Aussage treffen — überschreibt alles andere.
        overall = "NICHT_PRÜFBAR"
    else:
        all_checks = [c["match"] for c in checks.values()]
        if not all_checks:
            overall = "NUR_VALIDIERUNG"
        elif "ABWEICHUNG" in all_checks:
            overall = "ABWEICHUNG"
        elif "NICHT_PRÜFBAR" in all_checks and "OK" not in all_checks:
            overall = "NICHT_PRÜFBAR"
        elif "NICHT_PRÜFBAR" in all_checks:
            overall = "TEILWEISE_PRÜFBAR"
        else:
            overall = "OK"

    response = {
        "vat_valid": vies_result.get("valid", False),
        "vies_status": vies_status,
        "country_code": country_code,
        "vat_number": vat_number,
        "vat_number_original": request.vat_number,
        "overall_result": overall,
        "checks": checks,
        "vies_raw": {
            "name": vies_name,
            "address": vies_address,
            "request_date": vies_result.get("request_date"),
            "user_error": vies_result.get("user_error"),
        },
        "cached": vies_result.get("cached", False),
    }
    if vies_unavailable:
        response["hinweis"] = _missing_data_hint()

    # 6. ES-Registry-Fallback: wenn ES-VAT gültig ist und VIES keine Stammdaten
    # liefert (was bei ES Standard ist), versuchen wir einforma.com als
    # Sekundärquelle, um zumindest die registrierte Adresse zurückzuliefern.
    if (
        country_code == "ES"
        and vies_status == "valid"
        and (vies_name == "---" or not vies_name)
    ):
        registry = await _query_es_registry(vat_number)
        response["registry_fallback"] = registry

        # Wenn Kunde Name/Adresse mitgegeben hat, vergleichen wir on-the-fly
        if registry.get("found"):
            reg_checks = {}
            if request.company_name and registry.get("name"):
                score = _similarity(request.company_name, registry["name"])
                reg_checks["name"] = {
                    "customer_input": request.company_name,
                    "registry_official": registry["name"],
                    "similarity": round(score, 2),
                    "match": "OK" if score >= 0.3 else "ABWEICHUNG",
                }
            reg_address_parts = [
                p for p in [registry.get("street"), registry.get("postal_code"), registry.get("city")] if p
            ]
            reg_address_combined = ", ".join(reg_address_parts) if reg_address_parts else None
            if customer_address_combined and reg_address_combined:
                addr_score = _similarity(customer_address_combined, reg_address_combined)
                plz_ok = (
                    request.postal_code
                    and registry.get("postal_code")
                    and request.postal_code.strip() == registry["postal_code"]
                )
                city_ok = _contains_match(request.city, reg_address_combined) if request.city else None
                reg_checks["address"] = {
                    "customer_input": customer_address_combined,
                    "registry_official": reg_address_combined,
                    "similarity": round(addr_score, 2),
                    "postal_code_match": plz_ok,
                    "city_found": city_ok,
                    "match": "OK" if addr_score >= 0.25 and plz_ok else "ABWEICHUNG",
                }
            if reg_checks:
                response["registry_checks"] = reg_checks
                # Wenn vorher NUR_VALIDIERUNG oder NICHT_PRÜFBAR und der Registry-Match
                # eine Abweichung zeigt, das im Gesamtergebnis sichtbar machen.
                reg_matches = [c["match"] for c in reg_checks.values()]
                if overall in ("NUR_VALIDIERUNG", "NICHT_PRÜFBAR") and "ABWEICHUNG" in reg_matches:
                    response["overall_result"] = "ABWEICHUNG"
                elif overall == "NUR_VALIDIERUNG" and all(m == "OK" for m in reg_matches):
                    response["overall_result"] = "OK"

    return response


@app.get("/es/registry/{cif}")
async def es_registry(cif: str):
    """Stammdaten zu einer spanischen Firma aus einforma.com.

    Spanien gibt über VIES bewusst keine Name-/Adressdaten frei. Dieser
    Endpoint dient als ergänzende, **nicht-offizielle** Quelle, um den
    registrierten Geschäftssitz prüfen zu können (z. B. für den
    Vertrauensschutz-Adressabgleich).

    Antwort:
      - `found: true` mit Stammdaten oder
      - `found: false` mit `error`-Hinweis (Captcha, parse failure etc.)

    Cache: 24 h. Quelle ist „best-effort" — für die rechtssichere
    Abfrage ist `/vat/bzst-verify` zu nutzen.
    """
    return await _query_es_registry(cif)


@app.post("/vat/bzst-verify")
async def bzst_verify(request: BzstVerifyRequest):
    """Qualifizierte Bestätigungsabfrage beim BZSt — prüft USt-IdNr. mit Adressabgleich (Vertrauensschutz)."""
    return await _query_bzst(
        vat_number=request.vat_number,
        company_name=request.company_name,
        city=request.city,
        postal_code=request.postal_code,
        street=request.street,
    )


@app.get("/vat/bzst-status")
async def bzst_status():
    """BZSt Statusmeldungen und EU-Mitgliedstaaten-Verfügbarkeit abrufen."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        status_resp, ms_resp = await asyncio.gather(
            client.get(f"{BZST_BASE}/info/statusmeldungen"),
            client.get(f"{BZST_BASE}/info/eu_mitgliedstaaten"),
            return_exceptions=True,
        )

    result = {}
    if not isinstance(status_resp, Exception):
        result["statusmeldungen"] = status_resp.json()
    else:
        result["statusmeldungen_error"] = str(status_resp)

    if not isinstance(ms_resp, Exception):
        result["eu_mitgliedstaaten"] = ms_resp.json()
    else:
        result["eu_mitgliedstaaten_error"] = str(ms_resp)

    return result


@app.post("/vat/bulk")
async def validate_vat_bulk(request: BulkVatRequest):
    """Mehrere USt-IdNr. gleichzeitig validieren (max. 50)."""
    tasks = [
        _query_vies(item.country_code.upper().strip(), item.vat_number.strip().replace(" ", ""))
        for item in request.items
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    response = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            response.append({
                "country_code": request.items[i].country_code,
                "vat_number": request.items[i].vat_number,
                "error": str(result),
            })
        else:
            response.append(result)

    return {"results": response, "total": len(response)}


@app.get("/history")
def get_history(limit: int = Query(default=50, le=HISTORY_MAX)):
    """Letzte Abfragen anzeigen."""
    return {"entries": HISTORY[-limit:], "total": len(HISTORY)}
