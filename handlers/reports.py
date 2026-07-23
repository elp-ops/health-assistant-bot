"""
Photo/report handler.

When Jana sends a photo or image document:
1. Download the image
2. Run vision extraction (Claude or Gemini)
3. Append a dated entry to the health Google Doc
4. Upsert doctor info into the Google Sheet
5. Add calendar event if a future appointment date/time is found
6. Save extracted data to conversation history so brain can reference it
7. Reply with a summary
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from services.vision import extract_report_data
from services.google_docs import append_entry
from services.google_sheets import upsert_doctor

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("America/Toronto")

HISTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "history")


def _history_path(chat_id: int) -> str:
    return os.path.join(HISTORY_DIR, f"{chat_id}.json")


def _load_history(chat_id: int) -> list:
    path = _history_path(chat_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_history(chat_id: int, history: list):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = _history_path(chat_id)
    try:
        with open(path, "w") as f:
            json.dump(history[-40:], f)
    except Exception as e:
        logger.warning(f"Could not save history: {e}")


def _try_add_calendar_event(data: dict) -> str:
    """Try to create a calendar event from extracted appointment data. Returns status string or empty."""
    appt_date = data.get("appointment_date", "").strip()
    appt_time = data.get("appointment_time", "").strip()
    doctor = data.get("doctor_name", "Appointment").strip()

    if not appt_date or not appt_time:
        return ""

    try:
        # Parse date: "21 May 2026", "2026-Mar-31", "2026-02-18"
        dt = None
        for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%b-%d", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(appt_date, fmt)
                break
            except ValueError:
                continue
        if not dt:
            return ""

        # Parse time: "11:15 AM", "14:30", "11:15am"
        t = None
        for fmt in ("%I:%M %p", "%H:%M", "%I:%M%p", "%I %p"):
            try:
                t = datetime.strptime(appt_time.upper().strip(), fmt)
                break
            except ValueError:
                continue
        if not t:
            return ""

        # Only add if in the future
        now = datetime.now(TIMEZONE)
        appt_dt = datetime(dt.year, dt.month, dt.day, t.hour, t.minute, tzinfo=TIMEZONE)
        if appt_dt <= now:
            return ""

        from services.google_calendar import create_appointment
        date_str = dt.strftime("%d-%b")   # e.g. "21-May"
        time_str = t.strftime("%H:%M")    # e.g. "14:30"
        create_appointment(doctor, date_str, time_str)
        return f"Added to calendar: {doctor} on {appt_date} at {appt_time}."

    except Exception as e:
        logger.warning(f"Could not add calendar event from photo: {e}")
        return ""


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""

    # Get sender name for history
    user = update.effective_user
    sender_name = (user.full_name or user.username or "Unknown").strip()

    await update.message.reply_text("Got it. Reading the report...")

    # Get the file object (photo or document)
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        ext = ".jpg"
    else:
        file = await update.message.document.get_file()
        ext = os.path.splitext(update.message.document.file_name or "")[-1] or ".jpg"

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await file.download_to_drive(tmp_path)

        # Extract data from the image
        data = extract_report_data(tmp_path)

        report_type = data.get("report_type") or "Report"
        doctor = data.get("doctor_name") or "Unknown"

        # Append to health doc
        doc_text = _format_doc_entry(data)
        append_entry(doc_text, heading=f"{report_type}: {doctor}")

        # Upsert doctor to sheets
        if data.get("doctor_name"):
            # For prescriptions, use medication name as specialty so it's visible in the sheet
            is_prescription = (data.get("report_type") or "").lower() == "prescription"
            specialty = (
                data.get("medication_name", "") or data.get("specialty", "")
                if is_prescription
                else data.get("specialty", "")
            )
            upsert_doctor(
                doctor=data.get("doctor_name", ""),
                specialty=specialty,
                clinic=data.get("clinic_or_hospital", ""),
                phone=data.get("phone", ""),
                email=data.get("email", ""),
                notes=data.get("report_type", ""),
                address="",
                soft=True,  # Never overwrite existing field values from photo extraction
            )

        # Try to add calendar event if appointment date/time found
        cal_status = _try_add_calendar_event(data)

        # Build reply
        reply = _format_reply(data, cal_status)
        await update.message.reply_text(reply)

        # Save to conversation history so brain can reference this photo in subsequent messages
        history = _load_history(chat_id)
        if caption:
            history.append({"role": "user", "content": f"[From {sender_name}]: {caption} [sent a photo]"})
        else:
            history.append({"role": "user", "content": f"[From {sender_name}]: [sent a photo]"})
        # Summarise what was extracted so the brain has context
        summary_parts = [f"Photo processed. Saved to health record."]
        if doctor and doctor != "Unknown":
            summary_parts.append(f"Doctor: {doctor}.")
        if data.get("specialty"):
            summary_parts.append(f"Specialty: {data['specialty']}.")
        if data.get("appointment_date"):
            summary_parts.append(f"Appointment date: {data['appointment_date']}.")
        if data.get("appointment_time"):
            summary_parts.append(f"Appointment time: {data['appointment_time']}.")
        if data.get("clinic_or_hospital"):
            summary_parts.append(f"Clinic: {data['clinic_or_hospital']}.")
        if data.get("phone"):
            summary_parts.append(f"Phone: {data['phone']}.")
        if data.get("key_findings"):
            summary_parts.append(f"Notes: {data['key_findings']}.")
        if cal_status:
            summary_parts.append(cal_status)
        history.append({"role": "assistant", "content": " ".join(summary_parts)})
        _save_history(chat_id, history)

    except Exception as e:
        logger.error(f"Report handling error: {e}", exc_info=True)
        await update.message.reply_text(
            "Something went wrong processing the report. Check the logs."
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _format_doc_entry(data: dict) -> str:
    lines = []
    if data.get("report_date"):
        lines.append(f"Report date: {data['report_date']}")
    if data.get("appointment_date"):
        lines.append(f"Appointment: {data['appointment_date']}" + (f" at {data['appointment_time']}" if data.get("appointment_time") else ""))
    if data.get("clinic_or_hospital"):
        lines.append(f"Clinic: {data['clinic_or_hospital']}")
    if data.get("key_findings"):
        lines.append(f"Findings: {data['key_findings']}")
    return "\n".join(lines)


def _format_reply(data: dict, cal_status: str) -> str:
    lines = ["Report saved to your health record."]

    if data.get("report_type"):
        lines.append(f"Type: {data['report_type']}")
    if data.get("doctor_name"):
        lines.append(f"Doctor: {data['doctor_name']}")
    if data.get("specialty"):
        lines.append(f"Specialty: {data['specialty']}")
    if data.get("clinic_or_hospital"):
        lines.append(f"Clinic: {data['clinic_or_hospital']}")
    if data.get("phone"):
        lines.append(f"Phone: {data['phone']}")
    if data.get("appointment_date"):
        appt = data['appointment_date']
        if data.get("appointment_time"):
            appt += f" at {data['appointment_time']}"
        lines.append(f"Appointment: {appt}")
    elif data.get("report_date"):
        lines.append(f"Date: {data['report_date']}")
    if data.get("key_findings"):
        lines.append(f"\nFindings: {data['key_findings']}")
    if data.get("doctor_name"):
        lines.append("\nDoctor details saved to your spreadsheet.")
    if cal_status:
        lines.append(cal_status)

    return "\n".join(lines)
