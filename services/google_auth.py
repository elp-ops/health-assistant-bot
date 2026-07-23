"""
Shared Google auth using a service account.

Loads credentials from GOOGLE_CREDENTIALS_JSON env var (JSON string) if set,
otherwise falls back to the credentials file path (local dev).
"""

import json
import os

from google.oauth2 import service_account
from config import GOOGLE_CREDENTIALS_PATH, GOOGLE_SCOPES


def get_credentials():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        return service_account.Credentials.from_service_account_info(
            info, scopes=GOOGLE_SCOPES
        )
    return service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_PATH,
        scopes=GOOGLE_SCOPES,
    )
