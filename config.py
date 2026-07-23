import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_HEALTH_DOC_ID = os.getenv("GOOGLE_HEALTH_DOC_ID")
GOOGLE_DOCTORS_SHEET_ID = os.getenv("GOOGLE_DOCTORS_SHEET_ID")

NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL")
GMAIL_SENDER = os.getenv("GMAIL_SENDER", os.getenv("NOTIFICATION_EMAIL"))
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

VISION_PROVIDER = os.getenv("VISION_PROVIDER", "claude")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Google API scopes
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
]
