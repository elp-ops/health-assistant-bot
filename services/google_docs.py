"""
Google Docs service.
Appends entries to the health narrative document.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from .google_auth import get_credentials
from config import GOOGLE_HEALTH_DOC_ID

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("America/Toronto")


def _docs_service():
    creds = get_credentials()
    return build("docs", "v1", credentials=creds)


def append_entry(text: str, heading: str = None):
    """
    Append a dated entry to the health doc.
    First line is bold: heading — Entry date: timestamp
    Content is formatted as bullet points.
    Inserted at the top of the document.
    """
    service = _docs_service()

    now = datetime.now(TIMEZONE).strftime("%d %b %Y")

    if heading:
        first_line = f"{heading} — Entry date: {now}"
    else:
        first_line = f"Entry date: {now}"

    # Format each line as a bullet point, stripping any existing markers
    lines = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        for prefix in ("• ", "- ", "* ", "· "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        lines.append(f"• {line}")

    bullet_text = "\n".join(lines)
    content = f"{first_line}\n{bullet_text}\n*****\n"

    # Check for duplicate: skip if same heading already exists in recent entries
    existing = get_recent_entries(char_limit=5000)
    if first_line in existing:
        logger.info(f"Skipping duplicate entry: {first_line}")
        return

    # Insert at the top of the document (index 1)
    # Bold the first line only; explicitly unbold the rest (inherited bold fix)
    content_len = len(content)
    requests = [
        {
            "insertText": {
                "location": {"index": 1},
                "text": content,
            }
        },
        {
            "updateTextStyle": {
                "range": {
                    "startIndex": 1,
                    "endIndex": 1 + len(first_line),
                },
                "textStyle": {"bold": True},
                "fields": "bold",
            }
        },
        {
            "updateTextStyle": {
                "range": {
                    "startIndex": 1 + len(first_line),
                    "endIndex": 1 + content_len,
                },
                "textStyle": {"bold": False},
                "fields": "bold",
            }
        },
    ]

    service.documents().batchUpdate(
        documentId=GOOGLE_HEALTH_DOC_ID,
        body={"requests": requests},
    ).execute()

    logger.info("Appended entry to health doc.")


def get_recent_entries(char_limit: int = 2000) -> str:
    """Return the last N characters of the health doc (recent entries)."""
    service = _docs_service()
    doc = service.documents().get(documentId=GOOGLE_HEALTH_DOC_ID).execute()

    full_text = ""
    for element in doc.get("body", {}).get("content", []):
        para = element.get("paragraph")
        if para:
            for run in para.get("elements", []):
                full_text += run.get("textRun", {}).get("content", "")

    return full_text[:char_limit] if len(full_text) > char_limit else full_text
