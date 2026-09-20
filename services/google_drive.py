"""
Google Drive service.
Uploads report images to the health folder.
"""

import logging
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .google_auth import get_credentials
from config import GOOGLE_DRIVE_FOLDER_ID

logger = logging.getLogger(__name__)


def _drive_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


def upload_report(file_path: str, filename: str, mimetype: str = "image/jpeg") -> str:
    """
    Upload a file to the health reports folder on Drive.
    Returns the shareable view URL.
    """
    service = _drive_service()

    file_metadata = {
        "name": filename,
        "parents": [GOOGLE_DRIVE_FOLDER_ID],
    }
    media = MediaFileUpload(file_path, mimetype=mimetype)

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    file_id = uploaded.get("id")
    link = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

    # Make it readable by anyone with the link (optional, remove if you want it private)
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    logger.info(f"Uploaded {filename} to Drive: {file_id}")
    return link
