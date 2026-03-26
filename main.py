import asyncio
import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="VIES VAT Validation Service",
    description="Microservice zur Validierung von EU USt-IdNr. über die VIES REST API",
    version="1.0.0",
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


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class VatRequest(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    vat_number: str = Field(..., min_length=2, max_length=12)


class BulkVatRequest(BaseModel):
    items: list[VatRequest] = Field(..., min_items=1, max_items=50)


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


async def _query_vies(country_code: str, vat_number: str) -> dict:
    """Fragt die VIES REST API ab (mit Cache)."""
    key = _cache_key(country_code, vat_number)
    cached = _get_cached(key)
    if cached:
        _log({"country_code": country_code, "vat_number": vat_number, "cached": True, "valid": cached.get("valid")})
        return {**cached, "cached": True}

    url = f"{VIES_BASE}/ms/{country_code}/vat/{vat_number}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)

    if resp.status_code != 200:
        error_detail = resp.text
        _log({"country_code": country_code, "vat_number": vat_number, "cached": False, "error": error_detail})
        raise HTTPException(status_code=resp.status_code, detail=f"VIES API error: {error_detail}")

    data = resp.json()
    result = {
        "valid": data.get("isValid", False),
        "country_code": country_code,
        "vat_number": vat_number,
        "name": data.get("name", "---"),
        "address": data.get("address", "---"),
        "request_date": data.get("requestDate"),
    }

    _set_cache(key, result)
    _log({"country_code": country_code, "vat_number": vat_number, "cached": False, "valid": result["valid"]})
    return {**result, "cached": False}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {
        "service": "VIES VAT Validation Service",
        "version": "1.0.0",
        "endpoints": {
            "validate": "GET /vat/{country_code}/{vat_number}",
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
