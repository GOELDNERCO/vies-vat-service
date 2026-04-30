# VIES VAT Validation Service

Microservice zur Validierung europäischer USt-IdNr. (Partita IVA, TVA, VAT-Number, …)
über die offizielle **VIES** REST-API der EU sowie die **qualifizierte Bestätigungs­abfrage**
beim deutschen **BZSt eVatR**.

Die Service-URL des Production-Deployments lautet:

```
https://vies-vat-service-production.up.railway.app
```

Deployt über [Railway](https://railway.com/project/3427daf5-1e58-4a7c-8c22-659772b39f67)
direkt aus diesem Repository. Stack: **FastAPI** + **httpx**, gehostet als Docker-Container.

---

## Features

- Einzel-Validierung beliebiger EU-USt-IdNr. über VIES
- Bulk-Validierung (max. 50 Nummern parallel)
- **Kundendaten-Gegenprüfung** (`/vat/verify`): Firmen­name + Adresse werden gegen den
  VIES-Eintrag verglichen — mit Fuzzy-Match (Token-Jaccard, Unicode-Normalisierung)
- **Qualifizierte BZSt-Bestätigungsabfrage** (`/vat/bzst-verify`) inkl. Adress­abgleich
  und Vertrauensschutz; liefert die Einzelergebnisse Firmenname / Straße / PLZ / Ort
  als BZSt-Codes (A/B/C/D)
- BZSt-Statusmeldungen + EU-Mitgliedstaaten-Verfügbarkeit (`/vat/bzst-status`)
- In-Memory-Cache (TTL 1 h) — erspart wiederholte VIES-Abfragen
- Request-History (letzte 1000 Abfragen) für Audit/Debug
- **Robuste Behandlung transienter VIES-Fehler** — siehe unten

---

## Versionshistorie

### v1.3.0 — Korrekte Behandlung transienter VIES-Fehler

VIES-Mitgliedstaat-Backends (insbesondere Frankreich und Italien während Lastspitzen)
liefern bei Überlast `isValid: false` zusammen mit einem `userError`-Code wie
`MS_MAX_CONCURRENT_REQ`. Frühere Versionen haben das fälschlich als „USt-IdNr. ungültig"
durchgereicht — mit dem Folgefehler, dass eigentlich gültige EU-Kunden falsch besteuert
wurden (deutsche/lokale MwSt. via OSS statt Reverse-Charge).

**Was sich geändert hat:**

1. Neuer Status `vies_status` mit drei Werten:
   - `valid` — VIES bestätigt die Nummer
   - `invalid` — VIES verneint sie eindeutig
   - `unavailable` — Mitgliedstaat-System hat die Anfrage abgewiesen oder ist
     nicht erreichbar; **keine** Aussage über die Nummer möglich
2. Folgende `userError`-Codes werden als transient eingestuft:
   `MS_MAX_CONCURRENT_REQ`, `MS_UNAVAILABLE`, `SERVICE_UNAVAILABLE`, `TIMEOUT`,
   `GLOBAL_MAX_CONCURRENT_REQ`, `SERVER_BUSY`
3. Bei transienten Fehlern wird bis zu **4 ×** mit Exponential-Backoff (1.5 s → 3 s → 6 s)
   neu angefragt, bevor der Service `unavailable` zurückgibt
4. Der Cache nimmt nur `valid` / `invalid` auf — `unavailable` wird **nie** gecached
5. `/vat/verify` setzt bei `vies_status == "unavailable"` zwingend
   `overall_result: "NICHT_PRÜFBAR"` und legt einen sprechenden `hinweis` mit dem
   konkreten `userError` bei

### v1.2.0 — BZSt eVatR

Endpoint `/vat/bzst-verify` für die qualifizierte Bestätigungs­abfrage beim BZSt
inklusive Adressabgleich (Vertrauensschutz). Setzt eine eigene deutsche USt-IdNr. als
anfragende ID voraus (Umgebungsvariable `OWN_VAT_ID`).

### v1.1.x — Detail-Refinements für /vat/verify

Unterscheidung zwischen „USt-IdNr. ungültig" und „Mitgliedstaat liefert grundsätzlich
keine Stammdaten über VIES" (DE, ES, EE, NL); leere `name` / `address`-Werte werden
als nicht verfügbar (statt fälschlich `null`-Match) behandelt.

### v1.0 — Initial Release

Grundlegender VIES-Validator, Bulk-Endpoint, In-Memory-Cache, Request-History.

---

## Endpoints

| Methode | Pfad | Zweck |
|---|---|---|
| `GET`  | `/`                                  | Service-Info |
| `GET`  | `/health`                            | Healthcheck (Cache-/History-Größe) |
| `GET`  | `/vat/{country_code}/{vat_number}`   | Einzelne USt-IdNr. validieren |
| `POST` | `/vat/verify`                        | Kundendaten gegen VIES gegenprüfen |
| `POST` | `/vat/bzst-verify`                   | Qualifizierte Bestätigung beim BZSt |
| `GET`  | `/vat/bzst-status`                   | BZSt-Statusmeldungen + MS-Verfügbarkeit |
| `POST` | `/vat/bulk`                          | Mehrere VAT-Nummern parallel (max. 50) |
| `GET`  | `/history`                           | Letzte Abfragen (Audit) |

OpenAPI/Swagger UI: `https://vies-vat-service-production.up.railway.app/docs`

---

## `/vat/verify` — Kundendaten-Gegenprüfung

Der Standard-Workflow: Kundendaten reinwerfen, der Service erkennt den Ländercode
selbst (entweder aus `country` oder aus dem Prefix der `vat_number`), bereinigt die
VAT-Nummer (Leerzeichen, Punkte, Bindestriche, Prefix) und gleicht Name + Adresse
fuzzy gegen den VIES-Eintrag ab.

### Request

```bash
curl -X POST https://vies-vat-service-production.up.railway.app/vat/verify \
  -H "Content-Type: application/json" \
  -d '{
    "vat_number":   "IT02152700890",
    "company_name": "ESTETICA MODERNA S.R.L.",
    "address":      "Contrada Zisola SNC",
    "postal_code":  "96017",
    "city":         "Noto",
    "country":      "Italy"
  }'
```

### Response (Erfolgsfall)

```json
{
  "vat_valid":          true,
  "vies_status":        "valid",
  "country_code":       "IT",
  "vat_number":         "02152700890",
  "vat_number_original": "IT02152700890",
  "overall_result":     "OK",
  "checks": {
    "name":    { "customer_input": "...", "vies_official": "...", "similarity": 1.0,  "match": "OK" },
    "address": { "customer_input": "...", "vies_official": "...", "similarity": 0.83, "postal_code_found": true, "city_found": true, "match": "OK" }
  },
  "vies_raw": {
    "name":         "ESTETICA MODERNA S.R.L.",
    "address":      "CONTRADA ZISOLA SNC \n96017 NOTO SR\n",
    "request_date": "2026-04-28T09:47:19.041Z",
    "user_error":   "VALID"
  },
  "cached": false
}
```

### Response (VIES nicht erreichbar)

```json
{
  "vat_valid":      false,
  "vies_status":    "unavailable",
  "overall_result": "NICHT_PRÜFBAR",
  "vies_raw": {
    "user_error":   "MS_MAX_CONCURRENT_REQ",
    "request_date": "2026-04-29T16:38:50.832Z"
  },
  "hinweis": "VIES/Mitgliedstaat-System aktuell nicht abrufbar (userError: MS_MAX_CONCURRENT_REQ) — USt-IdNr. konnte WEDER bestätigt NOCH widerlegt werden. Bitte später erneut prüfen."
}
```

### `overall_result` — Werte und Bedeutung

| Wert | Bedeutung | Steuerliche Konsequenz |
|---|---|---|
| `OK`                  | VAT gültig + alle Checks OK                              | Reverse-Charge möglich |
| `ABWEICHUNG`          | VAT gültig, aber Name oder Adresse passen nicht          | Beim Kunden klären; Sitzadresse aus VIES verwenden |
| `TEILWEISE_PRÜFBAR`   | VAT gültig, einige Felder konnten nicht abgeglichen werden (z. B. DE/ES/EE/NL liefern keine Adresse) | Reverse-Charge möglich |
| `NICHT_PRÜFBAR`       | Entweder Nummer ungültig **oder** VIES temporär nicht erreichbar — `vies_status` lesen! | Bei `unavailable`: später erneut prüfen. Bei `invalid`: B2C-Behandlung (lokale MwSt. via OSS) |
| `NUR_VALIDIERUNG`     | Nur die VAT wurde geprüft, keine Vergleichsdaten geliefert | – |

> ⚠️ **Wichtig:** Vor v1.3.0 lieferte der Service bei MS-Überlast fälschlich
> `vat_valid: false`. Implementierungen sollten jetzt zwingend `vies_status` auswerten
> und bei `unavailable` neu anfragen statt eine Steuerentscheidung zu treffen.

---

## `/vat/bzst-verify` — Qualifizierte Bestätigung beim BZSt

Für Rechnungen mit deutschen Reverse-Charge-Empfängern: gibt zusätzlich zur reinen
Gültigkeit die **Adressabgleichs-Codes** zurück (Vertrauensschutz nach § 6a UStG).

```bash
curl -X POST https://vies-vat-service-production.up.railway.app/vat/bzst-verify \
  -H "Content-Type: application/json" \
  -d '{
    "vat_number":   "ATU12345678",
    "company_name": "Mustermann GmbH",
    "city":         "Wien",
    "postal_code":  "1010",
    "street":       "Stephansplatz 1"
  }'
```

BZSt-Ergebniscodes:

| Code | Bedeutung |
|------|-----------|
| `A`  | stimmt überein |
| `B`  | stimmt NICHT überein |
| `C`  | nicht abgefragt |
| `D`  | vom EU-Mitgliedstaat nicht mitgeteilt |

`overall_result` ist `OK` (alle relevanten Felder = A), `ABWEICHUNG` (mindestens ein B)
oder `NICHT_PRÜFBAR` (alles C/D).

> Voraussetzung: die eigene deutsche USt-IdNr. muss in der Umgebungsvariable
> `OWN_VAT_ID` gesetzt sein. Auf Railway aktuell: `OWN_VAT_ID=DE213401310`.

---

## Bulk

```bash
curl -X POST https://vies-vat-service-production.up.railway.app/vat/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"country_code": "IT", "vat_number": "02152700890"},
      {"country_code": "FR", "vat_number": "41750997322"}
    ]
  }'
```

Verarbeitet alle Nummern parallel; einzelne Fehler werden pro Eintrag im Result
zurückgegeben statt die ganze Anfrage abzubrechen.

---

## Konfiguration

| Variable | Pflicht | Zweck |
|---|---|---|
| `OWN_VAT_ID` | nur für `/vat/bzst-verify` | Eigene deutsche USt-IdNr. (anfragende ID gegenüber dem BZSt) |

Weitere relevante Defaults (in `main.py`):

| Konstante | Wert | Bedeutung |
|---|---|---|
| `CACHE_TTL_SECONDS`     | `3600` | Cache-Lebensdauer pro VAT-Nummer |
| `HISTORY_MAX`           | `1000` | Größe des In-Memory-Audit-Logs |
| `VIES_RETRY_ATTEMPTS`   | `4`    | Versuche inkl. Erstabfrage bei transienten Fehlern |
| `VIES_RETRY_BACKOFF`    | `1.5`  | Sekunden Basis-Backoff (exponentiell) |
| `VIES_TRANSIENT_ERRORS` | siehe oben | Set der `userError`-Codes, die als „nicht prüfbar" gelten |

---

## Lokale Entwicklung

```bash
git clone https://github.com/GOELDNERCO/vies-vat-service.git
cd vies-vat-service

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest

# Optional: für BZSt-Endpoint
export OWN_VAT_ID=DE213401310

uvicorn main:app --reload --port 8000
# → http://127.0.0.1:8000/docs
```

### Tests

```bash
python3 -m pytest tests/ -v
```

Testabdeckung:

- `tests/test_vies_classifier.py` — Klassifikation aller relevanten VIES-`userError`-Codes
- `tests/test_verify_endpoint.py` — `/vat/verify` mit gemocktem `_query_vies` für die
  Pfade `valid` / `invalid` / `unavailable`

---

## Deployment

Railway baut bei jedem Push auf `main` automatisch das Docker-Image und deployt es.
Der Healthcheck ist auf `/health` mit 30 s Timeout konfiguriert (`railway.toml`).

Aktuelle Live-Version prüfen:

```bash
curl -s https://vies-vat-service-production.up.railway.app/openapi.json | jq -r '.info.version'
# → 1.3.0
```

---

## Datenquellen

- **VIES REST-API**: `https://ec.europa.eu/taxation_customs/vies/rest-api`
  ([offizielle Dokumentation](https://ec.europa.eu/taxation_customs/vies/))
- **BZSt eVatR REST-API**: `https://api.evatr.vies.bzst.de/app/v1`
  (Details siehe [`BZST_EVATR_API_RESEARCH.md`](./BZST_EVATR_API_RESEARCH.md))

---

## Lizenz / Status

Internes Tool — kein Public-Release. Bug-Reports und PRs willkommen.
