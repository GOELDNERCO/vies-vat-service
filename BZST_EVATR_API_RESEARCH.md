# BZSt eVatR API Research

## Research Date: 2026-03-26

---

## 1. Interface Type

The BZSt (Bundeszentralamt fuer Steuern) offers **two interfaces** for programmatic VAT ID validation:

### OLD: XML-RPC Interface (DISCONTINUED since 30.11.2025)
- Protocol: XML-RPC over HTTPS (TLS 1.2)
- Synchronous request/response
- Data format: XML

### NEW: REST API (active since 01.07.2025)
- Protocol: REST over HTTPS
- Data format: JSON
- Synchronous request/response

---

## 2. Endpoint URLs

### NEW REST API (current)

| Endpoint | Method | URL |
|----------|--------|-----|
| **VAT Validation** | `POST` | `https://api.evatr.vies.bzst.de/app/v1/abfrage` |
| **Status Messages** | `GET` | `https://api.evatr.vies.bzst.de/app/v1/info/statusmeldungen` |
| **EU Member States Availability** | `GET` | `https://api.evatr.vies.bzst.de/app/v1/info/eu_mitgliedstaaten` |

Base URL: `https://api.evatr.vies.bzst.de/app/v1`

### OLD XML-RPC (discontinued 30.11.2025)
- Endpoint: `https://evatr.bff-online.de/evatrRPC`
- Function: `evatrRPC(UstId_1, UstId_2, Firmenname, Ort, PLZ, Strasse)`

---

## 3. Request Parameters

### NEW REST API - POST JSON Body

| JSON Field | Type | Required (Simple) | Required (Qualified) | Description |
|------------|------|-------------------|----------------------|-------------|
| `anfragendeUstid` | String | Yes | Yes | Your own German VAT ID (e.g., "DE123456789") |
| `angefragteUstid` | String | Yes | Yes | Foreign VAT ID to verify (e.g., "ATU12345678") |
| `firmenname` | String | No | Yes | Company name including legal form |
| `ort` | String | No | Yes | City / Location |
| `plz` | String | No | No | Postal code |
| `strasse` | String | No | No | Street and house number |

### OLD XML-RPC Parameters (for reference)

| Parameter | Required (Simple) | Required (Qualified) | Description |
|-----------|-------------------|----------------------|-------------|
| `UstId_1` | Yes | Yes | Your German VAT ID (case-sensitive) |
| `UstId_2` | Yes | Yes | Foreign VAT ID (case-sensitive) |
| `Firmenname` | No | Yes | Company name (not case-sensitive) |
| `Ort` | No | Yes | City (not case-sensitive) |
| `PLZ` | No | No | Postal code (not case-sensitive) |
| `Strasse` | No | No | Street (not case-sensitive) |

---

## 4. Request / Response Examples

### NEW REST API

**Simple Confirmation Request (einfache Bestaetigungsabfrage):**

```http
POST https://api.evatr.vies.bzst.de/app/v1/abfrage
Content-Type: application/json

{
  "anfragendeUstid": "DE123456789",
  "angefragteUstid": "ATU12345678"
}
```

**Qualified Confirmation Request (qualifizierte Bestaetigungsabfrage):**

```http
POST https://api.evatr.vies.bzst.de/app/v1/abfrage
Content-Type: application/json

{
  "anfragendeUstid": "DE123456789",
  "angefragteUstid": "ATU12345678",
  "firmenname": "Musterhaus GmbH & Co KG",
  "ort": "Wien",
  "plz": "1010",
  "strasse": "Musterstrasse 1"
}
```

**Response (JSON):**

```json
{
  "id": "unique-request-id",
  "anfrageZeitpunkt": "2026-03-26T10:30:00Z",
  "status": "evatr-0000",
  "ergFirmenname": "A",
  "ergStrasse": "B",
  "ergPlz": "A",
  "ergOrt": "A",
  "gueltigAb": null,
  "gueltigBis": null
}
```

### OLD XML-RPC (for reference)

**Request URL (GET style, also worked as XML-RPC POST):**

```
https://evatr.bff-online.de/evatrRPC?UstId_1=DE123456789&UstId_2=ATU12345678&Firmenname=Musterhaus+GmbH&Ort=Wien&PLZ=1010&Strasse=Musterstrasse+1
```

**Response XML:**

```xml
<params>
  <param><value><array><data>
    <value><string>Datum</string></value>
    <value><string>26.03.2026</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Uhrzeit</string></value>
    <value><string>10:30:00</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>ErrorCode</string></value>
    <value><string>200</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>UstId_1</string></value>
    <value><string>DE123456789</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>UstId_2</string></value>
    <value><string>ATU12345678</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Firmenname</string></value>
    <value><string>Musterhaus GmbH</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Ort</string></value>
    <value><string>Wien</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>PLZ</string></value>
    <value><string>1010</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Strasse</string></value>
    <value><string>Musterstrasse 1</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Erg_Name</string></value>
    <value><string>A</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Erg_Ort</string></value>
    <value><string>A</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Erg_PLZ</string></value>
    <value><string>A</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Erg_Str</string></value>
    <value><string>B</string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Gueltig_ab</string></value>
    <value><string></string></value>
  </data></array></value></param>
  <param><value><array><data>
    <value><string>Gueltig_bis</string></value>
    <value><string></string></value>
  </data></array></value></param>
</params>
```

---

## 5. Authentication Requirements

**No authentication is required.** The API is publicly accessible. However:

- You must provide a **valid German VAT ID** (`anfragendeUstid` / `UstId_1`) as your own identifier.
- The BZSt verifies that this German VAT ID is valid and authorized.
- You **cannot query a German VAT ID against a German VAT ID** (error code `evatr-0006` / old `213`).
- There is a **session-based rate limit** for qualified queries (`evatr-0008`): after reaching the maximum number of qualified queries in a session, you must start again with a simple query.
- Only **single queries** are supported; no batch processing.

---

## 6. Response Codes

### Address Match Result Codes (Erg_Name, Erg_Str, Erg_PLZ, Erg_Ort / ergFirmenname, ergStrasse, ergPlz, ergOrt)

| Code | Meaning (DE) | Meaning (EN) |
|------|-------------|--------------|
| **A** | Stimmt ueberein | **Matches** the registered data |
| **B** | Stimmt nicht ueberein | **Does not match** the registered data |
| **C** | Nicht angefragt | **Not queried** (field was not provided) |
| **D** | Vom EU-Mitgliedstaat nicht mitgeteilt | **Not provided** by the EU member state |

### NEW REST API Status Codes (evatr-XXXX)

| Code | Category | HTTP | Description (EN) |
|------|----------|------|-----------------|
| `evatr-0000` | Result | 200 | The foreign VAT-ID **is valid** at the time of the request. |
| `evatr-0001` | Notice | - | Please confirm the privacy notice. |
| `evatr-0002` | Notice | 400 | At least one **required field is missing**. |
| `evatr-0003` | Notice | 400 | VAT-ID is valid, but at least one **required field for qualified confirmation is missing** (firmenname, ort). |
| `evatr-0004` | Error | 400 | The requesting German VAT-ID is **syntactically invalid**. Does not match German rules. |
| `evatr-0005` | Error | 400 | The foreign VAT-ID is **syntactically invalid**. |
| `evatr-0006` | Notice | 403 | The requesting German VAT-ID is **not authorized** to query a German VAT-ID. |
| `evatr-0007` | Notice | 403 | Invalid request. |
| `evatr-0008` | Notice | 403 | **Maximum number** of qualified confirmation requests for this session reached. |
| `evatr-0011` | Error | 503 | Request cannot be processed. **Try again later.** |
| `evatr-0012` | Error | 400 | The foreign VAT-ID is syntactically invalid. Does not match the rules. |
| `evatr-0013` | Error | 503 | Request cannot be processed. Try again later. |
| `evatr-1001` | Error | 503 | Request cannot be processed. Try again later. |
| `evatr-1002` | Error | 500 | Request cannot be processed. Try again later. |
| `evatr-1003` | Error | 500 | Request cannot be processed. Try again later. |
| `evatr-1004` | Error | 500 | Request cannot be processed. Try again later. |
| `evatr-2001` | Notice | 404 | The foreign VAT-ID is **not assigned** at the time of the request. |
| `evatr-2002` | Notice | 200 | The foreign VAT-ID is **not yet valid**. Valid starting from `gueltigAb`. |
| `evatr-2003` | Error | 400 | The **country code** of the foreign VAT-ID is not valid. |
| `evatr-2004` | Error | 500 | Request cannot be processed. Try again later. |
| `evatr-2005` | Error | 404 | The own German VAT-ID is **not valid** at the time of the request. |
| `evatr-2006` | Notice | 200 | The foreign VAT-ID is **no longer valid**. Was valid during `gueltigAb` to `gueltigBis`. |
| `evatr-2007` | Error | 500 | Error processing data from the EU member state. |
| `evatr-2008` | Notice | 200 | VAT-ID is valid, but there is a **particular condition** for the qualified confirmation. Contact BZSt. |
| `evatr-2011` | Error | 500 | Request cannot be processed. Try again later. |
| `evatr-3011` | Error | 500 | Request cannot be processed. Try again later. |

### OLD XML-RPC Error Codes (for reference / mapping)

| Old Code | New Code | Meaning |
|----------|----------|---------|
| 200 | evatr-0000 | VAT-ID is valid |
| 201 | evatr-2001 | VAT-ID is invalid |
| 202 | evatr-2001 | Not registered in member state database |
| 203 | evatr-2002 | Valid only from date (Gueltig_ab) |
| 204 | evatr-2006 | Valid only during period (Gueltig_ab to Gueltig_bis) |
| 205 | evatr-1001 | Member state unavailable; retry later |
| 206 | evatr-2005 | Your German VAT-ID is invalid |
| 208 | (removed) | Another user query in progress; retry later |
| 209 | evatr-0005 | Does not match member state format |
| 210 | evatr-0012 | Check digit rules violation |
| 211 | evatr-0005 | Contains invalid characters |
| 212 | evatr-2003 | Invalid country code |
| 213 | evatr-0006 | Not authorized to query German VAT-ID |
| 214 | evatr-0004 | German VAT-ID must begin with 'DE' + 9 digits |
| 215 | evatr-0002 | Missing parameters for simple verification |
| 216 | evatr-0003 | Missing parameters for qualified verification |
| 217 | evatr-2007 | Member state data processing error |
| 218 | evatr-2008 | Qualified verification unavailable; simple executed |
| 219 | evatr-2008 | Qualified verification error; simple executed |
| 221 | evatr-0002 | Invalid parameters or data types |
| 999 | evatr-0011 | Temporary processing unavailable |

---

## 7. Simple vs. Qualified Confirmation Query

### Einfache Bestaetigungsabfrage (Simple Confirmation)
- Only checks **whether the VAT ID is valid** at the time of the query.
- Required parameters: only `anfragendeUstid` + `angefragteUstid`.
- Response: only `status` code (valid/invalid).
- No address matching results.

### Qualifizierte Bestaetigungsabfrage (Qualified Confirmation)
- Checks VAT ID validity **AND** verifies company address data.
- Required parameters: `anfragendeUstid` + `angefragteUstid` + `firmenname` + `ort`.
- Optional parameters: `plz`, `strasse`.
- Response includes address matching results: `ergFirmenname`, `ergStrasse`, `ergPlz`, `ergOrt` (values A/B/C/D).
- **Important for legal compliance**: Only the qualified confirmation provides evidence for "Vertrauensschutz" (protection of legitimate expectations) under German tax law (UStAE). This is the legally relevant proof that you verified your business partner's identity.
- There is a **session-based rate limit** for qualified queries.

### Key Difference

The **simple query** only tells you: "Is this VAT ID valid?" (yes/no).

The **qualified query** additionally tells you: "Does the company name, street, postal code, and city match what is registered?" -- returning A (match), B (no match), C (not queried), or D (not available from member state) for each field.

---

## 8. Migration Timeline

| Date | Event |
|------|-------|
| 01.07.2025 | New REST API available |
| 20.07.2025 | Written/telephone queries no longer accepted |
| 30.11.2025 | Old XML-RPC interface discontinued |

---

## 9. Key Technical Notes

- The service is operated by the BZSt but queries the VIES (VAT Information Exchange System) database of the respective EU member state.
- Some member states may not provide address data (result code D).
- Service availability depends on the availability of the queried member state's VIES node.
- The `GET /info/eu_mitgliedstaaten` endpoint can be used to check which member states are currently available.
- The `GET /info/statusmeldungen` endpoint returns all possible status messages.
- Language for status messages can be configured (German default, English available via `EVATR_LANG=en` environment variable in the PHP library).

---

## Sources

- [BZSt eVatR XML-RPC Documentation (obsolete)](https://www.bzst.de/DE/Unternehmen/Identifikationsnummern/Umsatzsteuer-Identifikationsnummer/eVatR/eVatR_Info_Schnittstelle/eVatR_info_schnittstelle.html)
- [BZSt eVatR Portal](https://www.bzst.de/DE/Unternehmen/Identifikationsnummern/Umsatzsteuer-Identifikationsnummer/eVatR/eVatR_node.html)
- [BZSt Newsletter USTKV 01/2025](https://www.bzst.de/SharedDocs/Newsletter/UStKV/20250701_newsletter_01_2025.html)
- [rechtlogisch/evatr-php (unofficial PHP wrapper)](https://github.com/rechtlogisch/evatr-php) - source code used to reverse-engineer the REST API details
