"""
Reminder handler.

Usage:
  /remind <message> <DD-Mon> <HH:MM>
  e.g. /remind Book follow-up with cardiologist 01-Jul 09:00

  /reminders — list active reminders
  /deletereminder <id> — delete a reminder by ID
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

REMINDERS_FILE = Path(__file__).parent.parent / "data" / "reminders.json"
HISTORY_DIR = Path(__file__).parent.parent / "data" / "history"


def _append_reminder_to_history(chat_id: int, text: str):
    """Save a fired reminder message to conversation history so the brain knows it was sent."""
    history_file = HISTORY_DIR / f"{chat_id}.json"
    history = []
    if history_file.exists():
        try:
            with open(history_file) as f:
                history = json.load(f)
        except Exception:
            pass
    now_str = datetime.now(ZoneInfo("America/Toronto")).strftime("%d %b %Y at %H:%M Toronto")
    history.append({"role": "assistant", "content": f"[REMINDER SENT at {now_str}]: {text}"})
    history = history[-40:]
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(history_file, "w") as f:
        json.dump(history, f)
TIMEZONE = ZoneInfo("America/Toronto")

REPEAT_DELTAS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": None,  # handled specially
}


def _load_reminders() -> list:
    if not REMINDERS_FILE.exists():
        REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        return []
    with open(REMINDERS_FILE) as f:
        return json.load(f)


def _save_reminders(reminders: list):
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REMINDERS_FILE, "w") as f:
        json.dump(reminders, f, indent=2)


def _parse_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """Parse date + time into a timezone-aware datetime. Accepts multiple formats."""
    year = datetime.now(TIMEZONE).year

    # Normalise time: handle "7pm", "7:00pm", "7:00 PM" → "19:00"
    time_normalised = time_str.strip()
    import re as _re
    m12 = _re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", time_normalised, _re.IGNORECASE)
    if m12:
        h = int(m12.group(1))
        mins = int(m12.group(2) or 0)
        if m12.group(3).lower() == "pm" and h != 12:
            h += 12
        elif m12.group(3).lower() == "am" and h == 12:
            h = 0
        time_normalised = f"{h:02d}:{mins:02d}"

    date_formats = [
        ("%d-%b %H:%M %Y", f"{date_str} {time_normalised} {year}"),      # 07-May 19:00 2026
        ("%d-%b-%Y %H:%M", f"{date_str} {time_normalised}"),              # 07-May-2026 19:00
        ("%Y-%m-%d %H:%M", f"{date_str} {time_normalised}"),              # 2026-05-07 19:00
        ("%d %B %Y %H:%M", f"{date_str} {time_normalised}"),              # 7 May 2026 19:00
        ("%B %d %Y %H:%M", f"{date_str} {time_normalised}"),              # May 7 2026 19:00
        ("%d %B %H:%M %Y", f"{date_str} {time_normalised} {year}"),       # 7 May 19:00 2026
        ("%B %d %H:%M %Y", f"{date_str} {time_normalised} {year}"),       # May 7 19:00 2026
    ]

    for fmt, value in date_formats:
        try:
            naive = datetime.strptime(value.strip(), fmt)
            aware = naive.replace(tzinfo=TIMEZONE)
            if aware < datetime.now(TIMEZONE):
                aware = aware.replace(year=aware.year + 1)
            return aware
        except ValueError:
            continue

    return None


def _next_occurrence(due: datetime, repeat: str) -> datetime:
    """Calculate the next occurrence after firing."""
    if repeat == "daily":
        return due + timedelta(days=1)
    elif repeat == "weekly":
        return due + timedelta(weeks=1)
    elif repeat == "monthly":
        month = due.month + 1
        year = due.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        import calendar
        max_day = calendar.monthrange(year, month)[1]
        day = min(due.day, max_day)
        return due.replace(year=year, month=month, day=day)
    return due


async def _fire_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Called by JobQueue when a reminder is due."""
    job = context.job
    chat_id = job.chat_id
    data = job.data
    reminder_id = data["id"]
    message = data["message"]
    repeat = data.get("repeat")

    fired_text = f"Reminder: {message}"
    await context.bot.send_message(chat_id=chat_id, text=fired_text)
    _append_reminder_to_history(chat_id, fired_text)

    reminders = _load_reminders()

    if repeat:
        # Find the current record and advance its due time
        for r in reminders:
            if r["id"] == reminder_id:
                current_due = datetime.fromisoformat(r["due"])
                next_due = _next_occurrence(current_due, repeat)
                r["due"] = next_due.isoformat()
                context.job_queue.run_once(
                    _fire_reminder,
                    when=next_due,
                    chat_id=chat_id,
                    name=reminder_id,
                    data={"id": reminder_id, "message": message, "repeat": repeat},
                )
                break
        _save_reminders(reminders)
    else:
        # One-time: remove from store
        reminders = [r for r in reminders if r["id"] != reminder_id]
        _save_reminders(reminders)


async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /remind <message> <DD-Mon> <HH:MM> [daily|weekly|monthly]
    The last two required tokens are date and time; optional repeat at the end.
    """
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Usage: /remind <message> <DD-Mon> <HH:MM> [daily|weekly|monthly]\n"
            "e.g. /remind Take stent medicine 20-Apr 09:00 daily"
        )
        return

    repeat = None
    if args[-1].lower() in REPEAT_DELTAS:
        repeat = args[-1].lower()
        args = args[:-1]

    time_str = args[-1]
    date_str = args[-2]
    message = " ".join(args[:-2])

    if not message:
        await update.message.reply_text("Please include a reminder message.")
        return

    import re as _re
    message = _re.sub(r"^[Rr]eminder:\s*", "", message).strip()

    due = _parse_datetime(date_str, time_str)
    if not due:
        await update.message.reply_text(
            f"Could not parse date/time: {date_str} {time_str}\n"
            "Format: DD-Mon HH:MM (e.g. 20-Apr 09:00)"
        )
        return

    reminder_id = str(uuid.uuid4())[:8]
    chat_id = update.effective_chat.id

    context.job_queue.run_once(
        _fire_reminder,
        when=due,
        chat_id=chat_id,
        name=reminder_id,
        data={"id": reminder_id, "message": message, "repeat": repeat},
    )

    reminders = _load_reminders()
    reminders.append({
        "id": reminder_id,
        "message": message,
        "due": due.isoformat(),
        "chat_id": chat_id,
        "repeat": repeat,
    })
    _save_reminders(reminders)

    repeat_label = f" (repeats {repeat})" if repeat else ""
    await update.message.reply_text(
        f"Reminder set.\n"
        f"ID: {reminder_id}\n"
        f"Message: {message}\n"
        f"Due: {due.strftime('%d %b %Y at %H:%M')} Toronto time{repeat_label}"
    )


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = _load_reminders()
    if not reminders:
        await update.message.reply_text("No active reminders.")
        return

    lines = []
    for i, r in enumerate(reminders, 1):
        due = datetime.fromisoformat(r["due"]).strftime("%d %b at %H:%M")
        repeat_label = f" (repeats {r['repeat']})" if r.get("repeat") else ""
        lines.append(f"{i}. {r['message']} — {due}{repeat_label}")

    await update.message.reply_text("Active reminders:\n\n" + "\n".join(lines))


async def delete_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deletereminder <id>")
        return

    reminder_id = context.args[0]
    reminders = _load_reminders()
    updated = [r for r in reminders if r["id"] != reminder_id]

    if len(updated) == len(reminders):
        await update.message.reply_text(f"No reminder found with ID: {reminder_id}")
        return

    _save_reminders(updated)

    # Also remove from job queue if still pending
    jobs = context.job_queue.get_jobs_by_name(reminder_id)
    for job in jobs:
        job.schedule_removal()

    await update.message.reply_text(f"Reminder {reminder_id} deleted.")


def restore_reminders(app):
    """
    Call this on bot startup to re-schedule any reminders that survived a restart.
    Recurring reminders that have passed are fast-forwarded to the next future occurrence.
    One-time reminders that have passed are dropped.
    """
    reminders = _load_reminders()
    now = datetime.now(ZoneInfo("America/Toronto"))
    active = []

    for r in reminders:
        due = datetime.fromisoformat(r["due"])
        repeat = r.get("repeat")

        if due <= now:
            if repeat:
                # Fast-forward to the next future occurrence
                while due <= now:
                    due = _next_occurrence(due, repeat)
                r["due"] = due.isoformat()
                logger.info(f"Fast-forwarded recurring reminder {r['id']} to {due}")
            else:
                logger.info(f"Dropping expired reminder {r['id']}: {r['message']}")
                continue

        app.job_queue.run_once(
            _fire_reminder,
            when=due,
            chat_id=r["chat_id"],
            name=r["id"],
            data={"id": r["id"], "message": r["message"], "repeat": repeat},
        )
        active.append(r)

    _save_reminders(active)
    logger.info(f"Restored {len(active)} reminders from disk.")
