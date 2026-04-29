"""Tests für die VIES-Antwort-Klassifikation und das Verify-Verhalten bei
transienten Mitgliedstaat-Fehlern.

Hintergrund: Frankreich (und andere MS) liefern bei Überlast `isValid: false`
zusammen mit `userError: MS_MAX_CONCURRENT_REQ`. Vor diesem Patch wurden solche
Antworten fälschlich als „USt-IdNr. ungültig" interpretiert — was im Steuerkontext
zu falschen Empfehlungen (B2C/OSS statt Reverse-Charge) führte.
"""

import pytest

from main import _classify_vies_response, VIES_TRANSIENT_ERRORS


@pytest.mark.parametrize(
    "vies_payload,expected_status",
    [
        # Echte gültige Antwort
        ({"isValid": True, "userError": "VALID"}, "valid"),
        # Echte ungültige Antwort
        ({"isValid": False, "userError": "INVALID_INPUT"}, "invalid"),
        ({"isValid": False, "userError": ""}, "invalid"),
        ({"isValid": False}, "invalid"),
        # Transiente Mitgliedstaat-/Service-Fehler — KEINE Aussage über VAT
        ({"isValid": False, "userError": "MS_MAX_CONCURRENT_REQ"}, "unavailable"),
        ({"isValid": False, "userError": "MS_UNAVAILABLE"}, "unavailable"),
        ({"isValid": False, "userError": "SERVICE_UNAVAILABLE"}, "unavailable"),
        ({"isValid": False, "userError": "TIMEOUT"}, "unavailable"),
        ({"isValid": False, "userError": "GLOBAL_MAX_CONCURRENT_REQ"}, "unavailable"),
        ({"isValid": False, "userError": "SERVER_BUSY"}, "unavailable"),
        # Case-insensitive
        ({"isValid": False, "userError": "ms_max_concurrent_req"}, "unavailable"),
    ],
)
def test_classify_vies_response(vies_payload, expected_status):
    assert _classify_vies_response(vies_payload) == expected_status


def test_transient_set_contains_known_codes():
    """Sicherheitsnetz: stellt sicher, dass die kritischen FR/IT-Codes drin sind."""
    must_be_transient = {
        "MS_MAX_CONCURRENT_REQ",
        "MS_UNAVAILABLE",
        "SERVICE_UNAVAILABLE",
        "TIMEOUT",
        "GLOBAL_MAX_CONCURRENT_REQ",
    }
    assert must_be_transient.issubset(VIES_TRANSIENT_ERRORS)
