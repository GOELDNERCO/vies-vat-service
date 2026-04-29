"""Integrationstest für /vat/verify: stellt sicher, dass eine transiente
VIES-Antwort (status=unavailable) zu overall_result=NICHT_PRÜFBAR führt
und NICHT zu „USt-IdNr. ungültig" — der Bug, der vor diesem Patch FR-VATs
während französischer MS-Überlast fälschlich verworfen hat.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def _vies_unavailable(country_code, vat_number):
    return {
        "valid": False,
        "status": "unavailable",
        "country_code": country_code,
        "vat_number": vat_number,
        "name": "---",
        "address": "---",
        "user_error": "MS_MAX_CONCURRENT_REQ",
        "request_date": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }


def _vies_valid(country_code, vat_number):
    return {
        "valid": True,
        "status": "valid",
        "country_code": country_code,
        "vat_number": vat_number,
        "name": "EURL ATTITUDE NAILS ACADEMY",
        "address": "2208 Route de Grasse\n06600 ANTIBES",
        "user_error": "VALID",
        "request_date": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }


def _vies_invalid(country_code, vat_number):
    return {
        "valid": False,
        "status": "invalid",
        "country_code": country_code,
        "vat_number": vat_number,
        "name": "---",
        "address": "---",
        "user_error": "INVALID_INPUT",
        "request_date": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }


def test_verify_unavailable_returns_nicht_pruefbar():
    """MS-Überlast darf NICHT als ungültige VAT durchgereicht werden."""
    async def fake(country_code, vat_number):
        return _vies_unavailable(country_code, vat_number)

    with patch.object(main, "_query_vies", side_effect=fake):
        resp = client.post("/vat/verify", json={
            "vat_number": "FR41750997322",
            "company_name": "ATTITUDE NAILS ACADEMY",
            "country": "France",
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_result"] == "NICHT_PRÜFBAR"
    assert body["vies_status"] == "unavailable"
    assert body["vat_valid"] is False
    assert "hinweis" in body
    assert "MS_MAX_CONCURRENT_REQ" in body["hinweis"]


def test_verify_valid_returns_ok():
    async def fake(country_code, vat_number):
        return _vies_valid(country_code, vat_number)

    with patch.object(main, "_query_vies", side_effect=fake):
        resp = client.post("/vat/verify", json={
            "vat_number": "FR41750997322",
            "company_name": "ATTITUDE NAILS ACADEMY",
            "address": "Route de Grasse 2208",
            "postal_code": "06600",
            "city": "Antibes",
            "country": "France",
        })

    body = resp.json()
    assert body["vies_status"] == "valid"
    assert body["vat_valid"] is True
    assert body["overall_result"] in ("OK", "TEILWEISE_PRÜFBAR")


def test_verify_invalid_returns_invalid():
    async def fake(country_code, vat_number):
        return _vies_invalid(country_code, vat_number)

    with patch.object(main, "_query_vies", side_effect=fake):
        resp = client.post("/vat/verify", json={
            "vat_number": "FR00000000000",
            "company_name": "Bogus",
            "country": "France",
        })

    body = resp.json()
    assert body["vies_status"] == "invalid"
    assert body["vat_valid"] is False
    # Hier ist NICHT_PRÜFBAR erlaubt (weil Name nicht abgleichbar), aber NICHT
    # darf der Hinweis-Text auf transienten Fehler verweisen.
    assert "hinweis" not in body or "MS_MAX" not in body.get("hinweis", "")
