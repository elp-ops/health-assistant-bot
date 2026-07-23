"""
Google Sheets service.
Manages the doctors/contacts spreadsheet.

Sheet columns:
  A: Doctor name
  B: Specialty
  C: Clinic
  D: Phone
  E: Email
  F: Address
  G: Notes
"""

import logging
import re

from googleapiclient.discovery import build

from .google_auth import get_credentials
from config import GOOGLE_DOCTORS_SHEET_ID

logger = logging.getLogger(__name__)

SHEET_NAME = "Sheet1"
HEADERS = ["Doctor", "Specialty", "Clinic", "Phone", "Email", "Address", "Notes"]


def _sheets_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def _normalize_phone(phone: str) -> str:
    """Normalise to 777-888-9999 x extension format."""
    if not phone:
        return ""
    phone = phone.strip()
    ext = ""
    # Split off extension
    match = re.split(r'\s*[xX]\s*', phone, maxsplit=1)
    if len(match) == 2:
        phone = match[0]
        ext = re.sub(r'\D', '', match[1])
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits[0] == '1':
        digits = digits[1:]
    if len(digits) == 10:
        formatted = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    else:
        formatted = digits
    return f"{formatted} x{ext}" if ext else formatted


def _normalize_name(name: str) -> str:
    """Strip titles and return lowercase last name for fuzzy matching."""
    name = name.strip().lower()
    for prefix in ("dr.", "dr ", "prof.", "prof ", "mr.", "mrs.", "ms."):
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    parts = name.split()
    return parts[-1] if parts else name


def _ensure_headers():
    """Create header row if the sheet is empty. Also removes Last Visit column if still present."""
    service = _sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
        range=f"{SHEET_NAME}!A1:H1",
    ).execute()

    existing_headers = result.get("values", [[]])[0] if result.get("values") else []

    # Migrate: remove Last Visit column if it exists
    if "Last Visit" in existing_headers:
        col_index = existing_headers.index("Last Visit")
        sheet_meta = service.spreadsheets().get(spreadsheetId=GOOGLE_DOCTORS_SHEET_ID).execute()
        sheet_id = sheet_meta["sheets"][0]["properties"]["sheetId"]
        service.spreadsheets().batchUpdate(
            spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
            body={"requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": col_index,
                        "endIndex": col_index + 1,
                    }
                }
            }]}
        ).execute()
        logger.info("Migrated: removed Last Visit column from sheet.")
        return

    if not existing_headers:
        service.spreadsheets().values().update(
            spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()


def upsert_doctor(doctor: str, specialty: str = "", clinic: str = "",
                  address: str = "", phone: str = "", email: str = "",
                  notes: str = "", soft: bool = False):
    """Add a new doctor row, or update the existing one if doctor name matches.

    soft=True: only fill in empty fields (never overwrite existing values).
    soft=False (default): new non-empty values overwrite existing ones.
    """
    _ensure_headers()
    service = _sheets_service()

    phone = _normalize_phone(phone)

    result = service.spreadsheets().values().get(
        spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
        range=f"{SHEET_NAME}!A:A",
    ).execute()

    rows = result.get("values", [])
    match_row = None
    doc_norm = _normalize_name(doctor)

    for i, row in enumerate(rows):
        if row:
            if _normalize_name(row[0]) == doc_norm or row[0].strip().lower() == doctor.strip().lower():
                match_row = i + 1
                break

    new_row = [doctor, specialty, clinic, phone, email, address, notes]

    if match_row:
        existing = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
            range=f"{SHEET_NAME}!A{match_row}:G{match_row}",
        ).execute().get("values", [[]])[0]

        existing += [""] * (7 - len(existing))
        if soft:
            # Only fill in fields that are currently empty
            merged = [existing[i] if existing[i] else new_row[i] for i in range(7)]
        else:
            # New non-empty values win
            merged = [new_row[i] if new_row[i] else existing[i] for i in range(7)]

        service.spreadsheets().values().update(
            spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
            range=f"{SHEET_NAME}!A{match_row}:G{match_row}",
            valueInputOption="RAW",
            body={"values": [merged]},
        ).execute()
        logger.info(f"Updated doctor row for: {doctor}")
    else:
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
            range=f"{SHEET_NAME}!A:G",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]},
        ).execute()
        logger.info(f"Added new doctor row: {doctor}")


def delete_doctor_row(row_number: int):
    """Delete a row from the sheet by 1-based row number (as shown in list_doctors output)."""
    _ensure_headers()
    service = _sheets_service()

    sheet_meta = service.spreadsheets().get(spreadsheetId=GOOGLE_DOCTORS_SHEET_ID).execute()
    sheet_id = sheet_meta["sheets"][0]["properties"]["sheetId"]

    # row_number is 1-based from the user's perspective (row 1 = first data row after header)
    # In the API, row index 0 = header, so data row 1 = index 1
    actual_index = row_number  # header is index 0, data rows start at index 1

    service.spreadsheets().batchUpdate(
        spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
        body={"requests": [{
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": actual_index,
                    "endIndex": actual_index + 1,
                }
            }
        }]}
    ).execute()
    logger.info(f"Deleted row {row_number} from doctors sheet.")


def list_doctors() -> list:
    """Return all doctor rows as a list of dicts."""
    _ensure_headers()
    service = _sheets_service()

    result = service.spreadsheets().values().get(
        spreadsheetId=GOOGLE_DOCTORS_SHEET_ID,
        range=f"{SHEET_NAME}!A:G",
    ).execute()

    rows = result.get("values", [])
    if len(rows) <= 1:
        return []

    return [dict(zip(HEADERS, row + [""] * (7 - len(row)))) for row in rows[1:]]
