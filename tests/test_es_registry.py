"""Tests für den ES-Registry-Fallback (einforma.com Scraper)."""

from unittest.mock import patch

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


# Fixture: realistische Snippet aus einforma.com (gekürzt) für CIF B16722811.
EINFORMA_HTML_SNIPPET = (
    b"<!DOCTYPE HTML><html><head>"
    b"<meta charset=\"ISO-8859-1\" />"
    b"<script>dataLayer = [{'pagina':'X','nombreEmpresa': 'COMISSO & SABAT ASOCIADOS S.L.','precio':'0'}];</script>"
    b"</head><body>"
    b"<tr><td width=\"30%\"><strong>Direcci\xf3n social actual:</strong></td>"
    b"<td align=\"left\" valign=\"bottom\" width=\"70%\">CALLE JOAN MIRO, 59 "
    b"<a class=\"x\" href=\"/mapa\">Ver Mapa</a></td></tr>"
    b"<tr><td><strong>Localidad:</strong></td>"
    b"<td align=\"left\" valign=\"bottom\" width=\"70%\">08320 EL MASNOU ( Barcelona )</td></tr>"
    b"</body></html>"
)


def test_parse_einforma_extracts_fields():
    parsed = main._parse_einforma_html(EINFORMA_HTML_SNIPPET, "B16722811")
    assert parsed is not None
    assert parsed["name"] == "COMISSO & SABAT ASOCIADOS S.L."
    assert parsed["street"] == "CALLE JOAN MIRO, 59"
    assert parsed["postal_code"] == "08320"
    assert parsed["city"] == "EL MASNOU"
    assert parsed["province"] == "Barcelona"
    assert parsed["cif"] == "B16722811"


def test_parse_einforma_handles_captcha_or_layout_break():
    # Wenn keine der erwarteten Felder existiert → None (statt halbgar)
    assert main._parse_einforma_html(b"<html><body>captcha required</body></html>", "B16722811") is None


def test_parse_einforma_handles_not_found_page():
    html = b"<html><body>El CIF B00000000 no se encuentra en nuestra base de datos.</body></html>"
    assert main._parse_einforma_html(html, "B00000000") is None


def test_es_registry_endpoint_returns_parsed_data():
    """Mockt den httpx-Call und prüft den GET /es/registry/{cif} Endpoint."""
    main.ES_REGISTRY_CACHE.clear()

    class FakeResp:
        status_code = 200
        content = EINFORMA_HTML_SNIPPET

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url):
            return FakeResp()

    with patch.object(main.httpx, "AsyncClient", FakeClient):
        resp = client.get("/es/registry/B16722811")

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["name"] == "COMISSO & SABAT ASOCIADOS S.L."
    assert body["postal_code"] == "08320"
    assert body["city"] == "EL MASNOU"
    assert body["province"] == "Barcelona"
    assert body["source"] == "einforma.com"


def test_es_registry_endpoint_handles_captcha():
    main.ES_REGISTRY_CACHE.clear()

    class FakeResp:
        status_code = 200
        content = b"<html>captcha</html>"

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url):
            return FakeResp()

    with patch.object(main.httpx, "AsyncClient", FakeClient):
        resp = client.get("/es/registry/B00000000")

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert "parse_failed" in body.get("error", "")


def test_es_registry_strips_es_prefix():
    """Akzeptiert sowohl 'ESB16722811' als auch 'B16722811'."""
    main.ES_REGISTRY_CACHE.clear()
    captured_urls = []

    class FakeResp:
        status_code = 200
        content = EINFORMA_HTML_SNIPPET

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url):
            captured_urls.append(url)
            return FakeResp()

    with patch.object(main.httpx, "AsyncClient", FakeClient):
        client.get("/es/registry/ESB16722811")

    assert captured_urls[-1].endswith("/B16722811")


def test_es_registry_cache():
    """Zweiter Call innerhalb des TTL trifft Cache, nicht das Netz."""
    main.ES_REGISTRY_CACHE.clear()
    call_count = {"n": 0}

    class FakeResp:
        status_code = 200
        content = EINFORMA_HTML_SNIPPET

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url):
            call_count["n"] += 1
            return FakeResp()

    with patch.object(main.httpx, "AsyncClient", FakeClient):
        r1 = client.get("/es/registry/B16722811")
        r2 = client.get("/es/registry/B16722811")

    assert r1.json()["cached"] is False
    assert r2.json()["cached"] is True
    assert call_count["n"] == 1
