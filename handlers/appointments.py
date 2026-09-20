"""
Appointment handler.

Usage:
  /appointment <doctor> <DD-Mon> <HH:MM>
  e.g. /appointment Dentist 15-Apr 10:00

  /appointments — list upcoming appointments
  /deleteappointment <event_id> — delete by Google Calendar event ID
"""

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from services.google_calendar import (
    create_appointment,
    list_upcoming_appointments,
    delete_appointment as cal_delete,
)

logger = logging.getLogger(__name__)


async def add_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /appointment <doctor> <DD-Mon> <HH:MM>
    Last two tokens are date and time; everything before is the doctor/description.
    """
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Usage: /appointment <doctor> <DD-Mon> <HH:MM>\n"
            "e.g. /appointment Dentist 15-Apr 10:00"
        )
        return

    time_str = args[-1]
    date_str = args[-2]
    doctor = " ".join(args[:-2])

    if not doctor:
        await update.message.reply_text("Please include a doctor or appointment description.")
        return

    try:
        event = create_appointment(doctor, date_str, time_str)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        await update.message.reply_text(
            "Could not create the appointment. Check that Google Calendar is set up correctly."
        )
        return

    start = event["start"].get("dateTime", "")
    try:
        dt = datetime.fromisoformat(start)
        formatted = dt.strftime("%d %b %Y at %H:%M")
    except Exception:
        formatted = start

    await update.message.reply_text(
        f"Appointment added.\n"
        f"Doctor: {doctor}\n"
        f"When: {formatted}\n"
        f"Event ID: {event['id']}\n\n"
        f"Google Calendar reminders set for 24h and 1h before."
    )


async def list_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        events = list_upcoming_appointments()
    except Exception as e:
        logger.error(f"Calendar list error: {e}")
        await update.message.reply_text("Could not fetch appointments. Check Google Calendar setup.")
        return

    if not events:
        await update.message.reply_text("No upcoming health appointments found.")
        return

    lines = []
    for event in events:
        title = event.get("summary", "").replace("Health: ", "")
        start = event["start"].get("dateTime", event["start"].get("date", ""))
        try:
            dt = datetime.fromisoformat(start)
            formatted = dt.strftime("%d %b %Y at %H:%M")
        except Exception:
            formatted = start
        lines.append(f"{formatted} — {title}\n(ID: {event['id']})")

    await update.message.reply_text("Upcoming appointments:\n\n" + "\n\n".join(lines))


async def delete_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /deleteappointment <event_id>\n"
            "Get the event ID from /appointments."
        )
        return

    event_id = context.args[0]
    try:
        cal_delete(event_id)
    except Exception as e:
        logger.error(f"Delete error: {e}")
        await update.message.reply_text("Could not delete the appointment. Check the event ID.")
        return

    await update.message.reply_text(f"Appointment deleted.")
