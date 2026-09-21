"""
Google Calendar service.
Creates, lists, and deletes health appointments.
All events go into the primary calendar with a "Health" prefix in the title.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from .google_auth import get_credentials
from config import GOOGLE_CALENDAR_ID

logger = logging.getLogger(__name__)

TIMEZONE = "America/Toronto"


def _calendar_service():
    creds = get_credentials()
    return build("calendar", "v3", credentials=creds)


def event_exists_on_date(doctor: str, start_dt: datetime) -> bool:
    """Check if an event for this doctor already exists on the same day."""
    service = _calendar_service()
    day_start = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = start_dt.replace(hour=23, minute=59, second=59, microsecond=0)

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        singleEvents=True,
    ).execute()

    events = result.get("items", [])
    doctor_last = doctor.strip().lower().split()[-1]
    for e in events:
        summary = e.get("summary", "").lower()
        if doctor_last in summary:
            return True
    return False


def create_appointment(doctor: str, date: str, time: str, patient: str = "Jana", location: str = "") -> dict:
    """
    Create a calendar event.
    date: DD-Mon (e.g. 15-Apr)
    time: HH:MM (e.g. 10:00)
    patient: "Jana" or "Luis"
    location: optional address string
    Returns the created event dict.
    """
    year = datetime.now(ZoneInfo(TIMEZONE)).year
    try:
        start_dt = datetime.strptime(f"{date} {time} {year}", "%d-%b %H:%M %Y")
        start_dt = start_dt.replace(tzinfo=ZoneInfo(TIMEZONE))
        if start_dt < datetime.now(ZoneInfo(TIMEZONE)):
            start_dt = start_dt.replace(year=year + 1)
    except ValueError as e:
        raise ValueError(f"Could not parse date/time: {date} {time}. Use DD-Mon HH:MM (e.g. 15-Apr 10:00)") from e

    if event_exists_on_date(doctor, start_dt):
        raise ValueError(f"An appointment for {doctor} already exists on that date.")

    end_dt = start_dt + timedelta(hours=1)

    event = {
        "summary": f"Health [{patient}]: {doctor}",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 1440},  # 24h
                {"method": "popup", "minutes": 60},    # 1h
            ],
        },
    }
    if location:
        event["location"] = location

    service = _calendar_service()
    created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
    logger.info(f"Created calendar event: {created.get('id')}")
    return created


def update_appointment_location(event_id: str, location: str) -> dict:
    """Patch the location field on an existing calendar event."""
    service = _calendar_service()
    updated = service.events().patch(
        calendarId=GOOGLE_CALENDAR_ID,
        eventId=event_id,
        body={"location": location},
    ).execute()
    logger.info(f"Updated location for event {event_id}: {location}")
    return updated


def list_upcoming_appointments(max_results: int = 30) -> list:
    """Return upcoming health appointments from the calendar."""
    now = datetime.now(ZoneInfo(TIMEZONE))
    time_max = now.replace(year=now.year + 1).isoformat()
    service = _calendar_service()

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=now.isoformat(),
        timeMax=time_max,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    return result.get("items", [])


def list_past_appointments(max_results: int = 50) -> list:
    """Return past appointments from the calendar going back 12 months."""
    now = datetime.now(ZoneInfo(TIMEZONE))
    time_max = now.isoformat()
    time_min = now.replace(year=now.year - 1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    service = _calendar_service()
    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])


def delete_appointment(event_id: str):
    """Delete a calendar event by ID."""
    service = _calendar_service()
    service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
    logger.info(f"Deleted calendar event: {event_id}")
