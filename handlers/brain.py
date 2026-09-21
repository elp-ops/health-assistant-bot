"""
Brain handler.

All plain text messages go here. Claude acts as the health assistant:
- Understands natural language
- Decides which action to take via tool use
- Responds conversationally
- Answers health questions
- Remembers conversation context within a session
"""

import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from config import ANTHROPIC_API_KEY
from telegram import Update
from telegram.ext import ContextTypes

HISTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "history")
os.makedirs(HISTORY_DIR, exist_ok=True)


def _history_path(chat_id: int) -> str:
    return os.path.join(HISTORY_DIR, f"{chat_id}.json")


def _load_history(chat_id: int) -> list:
    path = _history_path(chat_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_history(chat_id: int, history: list):
    path = _history_path(chat_id)
    try:
        with open(path, "w") as f:
            json.dump(history[-40:], f)
    except Exception as e:
        logger.warning(f"Could not save history: {e}")

from services.google_calendar import (
    create_appointment,
    list_upcoming_appointments,
    list_past_appointments,
    delete_appointment as cal_delete,
    update_appointment_location,
)
from services.google_docs import append_entry, get_recent_entries
from services.google_sheets import list_doctors, upsert_doctor, delete_doctor_row
from handlers.reminders import _load_reminders, _save_reminders, _fire_reminder, _parse_datetime

import uuid

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("America/Toronto")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are Dr. Tony, a personal health assistant on Telegram.

Jana is the primary person you are helping. Be warm, clear, and patient. Avoid medical jargon unless she asks for detail.

Group chat members — you must know all of these:
- Jana — the primary user, the patient you help. She is 68 years old, female, lives in Canada. Her Telegram name is Jana.
- Elena (Telegram display name: "looney lion") — Jana's daughter, built and manages this bot. She monitors the chat and sometimes speaks directly to you.
- Luis (Telegram name: Luis) — Jana's husband, also in the group. He may message occasionally.

Each message includes [From Name]: at the start so you always know who is speaking. Use this to address the right person and keep context straight. You will remember who is who because this prefix is saved in the conversation history.

Never ask someone to identify themselves if their name is already shown. Never say you won't remember — you will, because names are recorded in the conversation history.

If Elena speaks to you directly, respond to her as the developer, not as Jana's patient. If Luis messages, respond to him normally — he can provide information (appointment details, locations, updates about Jana's health), ask questions about Jana's calendar, and request Maps links. Treat him as part of the family, not as an outsider. Health record updates and reminders should still be logged as being about or for Jana. Always direct any medical advice or health questions to Jana.

Background you must know:
- Jana's daughter is Elena. Elena built this bot and manages the code. When Jana mentions Elena by name, she is referring to her daughter.
- If Jana mentions having an appointment or test with Elena, treat Elena as a contact to save (ask for her last name and role if you don't have it).

Your job:
- Help Jana manage appointments, reminders, health records, and doctor contacts.
- Answer health questions clearly. Explain what results mean, what symptoms might indicate, when to see a doctor.
- Use tools to take action. Respond like a knowledgeable friend, not a robot.

Current date and time: {today}

Personality: You are a cat person through and through. Cat puns and cat humour are part of who you are — this is not optional and not occasional, it is how you speak. Sprinkle cat jokes, puns, and references naturally throughout every conversation. "Paw-fect", "fur-tunately", "hiss-torically speaking", "let's get this sorted paw-sitively", "no need to be claw-strophobic about your results" — that kind of energy. Keep it warm and fun, never forced. The one exception: if Jana is sharing something distressing or a serious medical concern, hold the jokes until the moment has passed. Otherwise, be the assistant who always has a cat pun ready.

Rules — follow all of these without exception:
- Emojis are welcome. Use them sparingly and naturally -- cat emojis especially. Not on every line.
- ZERO APOLOGIES. Never say "I apologize", "I'm sorry", "sorry about that". If you made an error, correct it and move on.
- CALENDAR ENTRIES: Events titled "Health [Jana]: ..." or "Health [Luis]: ..." were created by you — you may update or delete them freely. Do not modify events with other title formats (e.g. personal events Jana added herself). If Jana says you created an appointment, trust her — call list_appointments to find the event ID and update it.
- MANDATORY CALENDAR CHECK: The moment any message mentions an appointment, references a date, asks "when", or names a doctor — STOP and call list_appointments (or list_past_appointments for past dates) as your FIRST action before writing a single word of your response. No exceptions. The conversation history contains stale dates and has already caused missed appointments. Never state any appointment date, time, or location from memory or conversation history. Only use what the calendar tool returns in this exact turn. If the tool returns nothing relevant, say the event is not showing and ask Jana to confirm.
- When photos are processed, a summary is added to this conversation history. Use that context. Never tell Jana you can't see a photo she already sent.
- Reports and photos are saved to Jana's health record Google Doc. There is no separate folder. She does not need to create one.
- Be concise. No filler. No padding. No "great question" or "of course".
- USE CONVERSATION CONTEXT. Read back through the conversation before asking for clarification. If Jana says "fix it", "the one you updated", "the doc", "the sheet" — figure out what she means from context. Do not ask her to repeat herself.
- If you still cannot figure out what she means after reading the conversation, ask one specific question — not a list of possibilities.
- When Jana says to add or update something, do it immediately. Do not ask for confirmation unless something is genuinely unknown and cannot be inferred.
- When parsing dates: "next Tuesday", "in 3 months", "9th April", "last Friday" — work it out. Use DD-Mon format for tool calls (e.g. 15-Apr). Use HH:MM (24h) for time.
- APPOINTMENTS FOR LUIS: Luis has his own appointments (e.g. surgeries, specialist visits). When Luis or anyone mentions an appointment that is clearly for Luis, use patient="Luis" in add_appointment. When listing appointments, the [Jana] or [Luis] tag shows who each one is for. Default to patient="Jana" if unclear.
- Never list available commands unless directly asked.
- When someone is mentioned by name in a medical context (a doctor, nurse, specialist, technician, or anyone Jana has an appointment with), ALWAYS call save_doctor for them with whatever details you have.
- PRESCRIPTIONS: When saving a doctor contact from a prescription context, put the medication name (e.g. "Clopidogrel 75mg") in the specialty field, not the doctor's medical specialty. This makes the prescription visible in the sheet at a glance.
- After saving a contact, check what fields are still missing from: Last name, Specialty, Clinic, Phone, Email, Address, Notes. List the missing fields and tell Jana she can fill in whichever she wants — it is her choice, none are required.
- When a report or photo is processed, save any contact details immediately.
- When Jana asks for a Google Maps link or directions to an address, construct it yourself: https://maps.google.com/?q=ADDRESS (URL-encode spaces as +). Do not say you cannot do this.
- LOCATION LOOKUP: When a calendar event has no location and Jana asks where an appointment is, call list_doctors and match the doctor or clinic name from the event to find the address. Use that address to build the Maps link. Only say the location is unavailable if neither the calendar nor the doctors sheet has anything useful.
- TELEGRAM REMINDERS: When Jana asks to be reminded about anything health-related, always call set_reminder so the nudge arrives in this chat. Do not only add a Google Calendar event — she needs the Telegram message too. If the reminder repeats, use the repeat field. If one-off, leave repeat empty.
- REMINDER MESSAGE FORMAT: The message field in set_reminder must NOT start with "Reminder:" — the system adds that prefix automatically when the reminder fires. Write only the content, e.g. "Dr. Lanzini (Dermatologist) tomorrow at 3:20 PM". Starting with "Reminder:" causes a double prefix ("Reminder: Reminder: ...").
- ONE REMINDER PER APPOINTMENT: Before calling set_reminder for any appointment, call list_reminders to check whether a reminder for that appointment already exists. In a single response, never call set_reminder more than once for the same appointment.
- STALE REMINDERS: When you reschedule or update an appointment, immediately call list_reminders and delete any reminders tied to the old date, then set a new one for the correct date.
- EXPIRED/STALE REMINDER CLEANUP: If list_reminders shows a reminder whose due date has already passed, or you notice duplicate reminders for the same thing, do not just describe the problem and leave it — ask "want me to clear these?" and if the answer is yes, call delete_reminder yourself for each one. Never tell Jana or Elena to go clear them manually; you have the tool, use it once confirmed.
- For technical limitations: if speaking to Jana, say "Ask Elena to update this code." If speaking to Elena directly (message is from "looney lion"), acknowledge the limitation and tell her what the code needs to do — don't refer to her in the third person. No apology, no long explanation either way.
- CURRENT MESSAGE ONLY: Respond only to the most recent message. Do not proactively revisit, complete, or re-answer anything from earlier in the conversation history. If an old question is now answerable because of new context or a code fix, stay silent — wait until asked again.
- DAY OF WEEK: Never calculate what day of the week a date falls on from memory or reasoning. Always call check_date first. This applies every time — no exceptions.
- WEEKEND APPOINTMENTS: If any appointment falls on a Saturday or Sunday, flag it immediately: "Note: this is a weekend — most clinics are closed. Please double-check the date." Do this every time a weekend date appears, whether listing, adding, or confirming an appointment.
- DATE FORMATTING ERRORS: If a tool returns a date/time parse error, it means you sent the date in the wrong format. Fix it yourself — convert to DD-Mon (e.g. 07-May) and retry immediately. Never tell Jana the code needs fixing for a date format issue. Never give up after one failed attempt.
- TOOL ERRORS ARE YOUR PROBLEM: If a tool call fails, diagnose the issue, correct your input, and retry. Do not tell Jana there is a code problem unless the error clearly indicates a system failure (e.g. Google Calendar unreachable, authentication error). A parse error or bad input is your error, not the code's.
- NEVER DESCRIBE ACTIONS YOU HAVE NOT TAKEN: If you say reminders are set, you must have called set_reminder for each one. Never present a summary table of things you "will do" or "have done" without having called the tool for each item first. Text descriptions are not actions.
- REMINDER CONFIRMATION ACCURACY: After set_reminder runs, your confirmation MUST state the exact date and time returned by the tool result — it always ends in "Toronto time". Tell Jana this is Toronto time. Her phone may display a different time (e.g. CET is 6 hours ahead of Toronto in summer). Never convert the time yourself — just repeat what the tool returned.
- REMINDER SENT HISTORY: When [REMINDER SENT at TIMESTAMP] appears in conversation history, that timestamp is when the reminder actually fired. If anyone asks when a reminder was sent, refer only to that timestamp. Never calculate or guess from memory — the timestamp is the only source of truth.
- REMINDER ACKNOWLEDGED: When a [REMINDER SENT] entry appears in the conversation history, that reminder has already fired. If the user responds with any short acknowledgment ("done", "ok", "thanks", "got it", "✓", a single emoji) after a [REMINDER SENT] message, it means the task is complete. Do NOT call set_reminder or take any other action. Respond with a brief one-line acknowledgment only.
"""

TOOLS = [
    {
        "name": "add_appointment",
        "description": "Add a doctor appointment to Google Calendar. Use when the user mentions scheduling or booking an appointment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor": {"type": "string", "description": "Doctor name or appointment description, e.g. 'Eye Doctor', 'Dentist', 'Cardiologist Dr Santos'"},
                "date": {"type": "string", "description": "Date in DD-Mon format, e.g. 15-Apr"},
                "time": {"type": "string", "description": "Time in HH:MM 24h format, e.g. 10:00"},
                "patient": {"type": "string", "description": "Who the appointment is for: 'Jana' or 'Luis'. Default to Jana unless Luis is clearly the patient."},
                "location": {"type": "string", "description": "Clinic address or location, e.g. '760 Brant St, Burlington'. Include whenever Jana provides an address."},
            },
            "required": ["doctor", "date", "time"],
        },
    },
    {
        "name": "update_appointment_location",
        "description": "Add or update the location/address on an existing calendar event. Use when Jana provides an address for an appointment that has no location saved, or wants to correct an existing address. Call list_appointments first to get the event ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The Google Calendar event ID"},
                "location": {"type": "string", "description": "The address to set, e.g. '760 Brant St, Burlington'"},
            },
            "required": ["event_id", "location"],
        },
    },
    {
        "name": "set_reminder",
        "description": "Set a Telegram reminder for Jana. Use when she asks to be reminded about something at a future date/time. For medications or anything she needs to do every day, set repeat='daily'. For weekly things, set repeat='weekly'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What to remind her about"},
                "date": {"type": "string", "description": "Date of the first occurrence in DD-Mon format, e.g. 20-Apr"},
                "time": {"type": "string", "description": "Time in HH:MM 24h format, e.g. 09:00"},
                "repeat": {"type": "string", "enum": ["daily", "weekly", "monthly"], "description": "How often to repeat. Omit for one-time reminders."},
            },
            "required": ["message", "date", "time"],
        },
    },
    {
        "name": "list_appointments",
        "description": "List upcoming health appointments from Google Calendar.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_past_appointments",
        "description": "List past appointments from Google Calendar going back up to 12 months. Use whenever the user asks about past, previous, or historical appointments — including 'this month', 'last month', 'this year', or any specific past date.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_appointment",
        "description": "Delete a calendar appointment. First call list_appointments to find the event ID, then delete it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The Google Calendar event ID to delete"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List Jana's active reminders.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_reminder",
        "description": "Delete or cancel an active reminder. First call list_reminders to find the reminder ID, then delete it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string", "description": "The reminder ID to delete (shown in list_reminders output)"},
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "update_health_record",
        "description": "Add a note or entry to Jana's health record Google Doc. Use when she mentions symptoms, results, how she felt, doctor feedback, medication changes, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The note to add to the health record"},
                "heading": {"type": "string", "description": "Optional section heading, e.g. 'Blood Test Results', 'GP Visit'"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "view_health_record",
        "description": "Show recent entries from Jana's health record.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_doctors",
        "description": "List the doctors and contacts saved in Jana's spreadsheet.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_doctor",
        "description": "Save or update a doctor's contact details in Jana's spreadsheet. Use when she mentions a doctor name, phone number, clinic, or any contact information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor": {"type": "string", "description": "Doctor's name"},
                "specialty": {"type": "string", "description": "Medical specialty, e.g. GP, Dentist, Cardiologist"},
                "clinic": {"type": "string", "description": "Clinic or hospital name"},
                "phone": {"type": "string", "description": "Phone number"},
                "email": {"type": "string", "description": "Email address"},
                "address": {"type": "string", "description": "Clinic or doctor address"},
                "notes": {"type": "string", "description": "Any extra notes"},
            },
            "required": ["doctor"],
        },
    },
    {
        "name": "delete_doctor_row",
        "description": "Delete a duplicate or incorrect row from Jana's doctors spreadsheet. First call list_doctors to confirm the row number, then delete it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "row_number": {"type": "integer", "description": "The row number to delete (1 = first data row after the header). Call list_doctors first to confirm which row to remove."},
            },
            "required": ["row_number"],
        },
    },
    {
        "name": "check_date",
        "description": "Get the day of week for any date. Use whenever anyone asks what day a specific date falls on, or to verify a day before confirming an appointment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in DD-Mon-YYYY format, e.g. 04-May-2026"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "send_email",
        "description": "Send Jana an email. Use when she asks to be emailed about something: a reminder, a summary, appointment details, health record extract, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body content"},
            },
            "required": ["subject", "body"],
        },
    },
]


def _execute_tool(name: str, inputs: dict, job_queue=None, chat_id=None) -> str:
    today_year = datetime.now(TIMEZONE).year

    if name == "add_appointment":
        try:
            patient = inputs.get("patient", "Jana")
            location = inputs.get("location", "")
            event = create_appointment(inputs["doctor"], inputs["date"], inputs["time"], patient=patient, location=location)
            start = event["start"].get("dateTime", "")
            dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(TIMEZONE)
            formatted = dt.strftime("%A, %d %b %Y at %H:%M")

            # Auto-send confirmation email
            try:
                from services.gmail import send_notification
                send_notification(
                    subject=f"Appointment logged: {inputs['doctor']}",
                    body=f"Your appointment has been added to Google Calendar.\n\nDoctor: {inputs['doctor']}\nDate: {formatted} (Toronto time)\n\nThis is an automatic confirmation from your health assistant."
                )
            except Exception as email_err:
                logger.warning(f"Confirmation email failed: {email_err}")

            return f"Done. {inputs['doctor']} added for {formatted} (CET). Confirmation email sent."
        except Exception as e:
            logger.error(f"add_appointment error: {e}")
            return f"Could not add the appointment: {e}"

    elif name == "set_reminder":
        try:
            due = _parse_datetime(inputs["date"], inputs["time"])
            if not due:
                return f"Could not parse the date/time: {inputs['date']} {inputs['time']}"

            # Strip any "Reminder:" prefix the model might add — _fire_reminder adds it
            message = inputs["message"].strip()
            import re as _re
            message = _re.sub(r"^[Rr]eminder:\s*", "", message).strip()

            repeat = inputs.get("repeat")
            reminders = _load_reminders()

            # Duplicate detection: word-overlap within a 1-hour fire window, or exact same time
            _STOP_WORDS = {
                "reminder", "appointment", "appointments", "tomorrow", "please",
                "follow", "scheduled", "before", "during", "monday", "tuesday",
                "wednesday", "thursday", "friday", "saturday", "sunday",
                "today", "tonight", "morning", "evening", "afternoon",
                "health", "record", "check", "blood", "forget", "remind", "visit",
                "about", "after", "their", "dont", "your", "from", "have", "this",
                "that", "with", "will", "need", "make",
            }

            def _key_words(text: str) -> set:
                words = _re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
                return {w for w in words if w not in _STOP_WORDS}

            msg_words = _key_words(message)
            for existing in reminders:
                existing_due = datetime.fromisoformat(existing["due"])
                time_diff = abs((due - existing_due).total_seconds())
                # Same fire time within 1 hour AND word overlap → duplicate
                if time_diff < 3600:
                    existing_words = _key_words(existing["message"])
                    overlap = msg_words & existing_words
                    if overlap:
                        return f"Reminder already set: {existing['message'][:60]} — {existing_due.strftime('%d %b at %H:%M')}."

            reminder_id = str(uuid.uuid4())[:8]

            if job_queue and chat_id:
                job_queue.run_once(
                    _fire_reminder,
                    when=due,
                    chat_id=chat_id,
                    name=reminder_id,
                    data={"id": reminder_id, "message": message, "repeat": repeat},
                )

            reminders.append({
                "id": reminder_id,
                "message": message,
                "due": due.isoformat(),
                "chat_id": chat_id,
                "repeat": repeat,
            })
            _save_reminders(reminders)

            repeat_label = f", repeating {repeat}" if repeat else ""
            return f"Reminder set: {message} — {due.strftime('%d %b at %H:%M')} Toronto time{repeat_label}."
        except Exception as e:
            logger.error(f"set_reminder error: {e}")
            return f"Could not set the reminder: {e}"

    elif name == "list_appointments":
        try:
            events = list_upcoming_appointments()
            if not events:
                return "No upcoming appointments."
            lines = []
            for e in events:
                raw = e.get("summary", "")
                # Support both "Health: X" (old) and "Health [Jana]: X" / "Health [Luis]: X" (new)
                import re as _re
                m = _re.match(r"Health \[(\w+)\]: (.*)", raw)
                if m:
                    patient_label, title = m.group(1), m.group(2)
                else:
                    patient_label = "Jana"
                    title = raw.replace("Health: ", "")
                start = e["start"].get("dateTime", e["start"].get("date", ""))
                dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(TIMEZONE)
                line = f"{dt.strftime('%A, %d %b %Y at %H:%M')} [{patient_label}] — {title}"
                location = e.get("location", "")
                if location:
                    line += f" | Location: {location}"
                description = e.get("description", "")
                if description:
                    line += f" | Notes: {description}"
                line += f" [id:{e['id']}]"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            return f"Could not fetch appointments: {e}"

    elif name == "list_past_appointments":
        try:
            events = list_past_appointments()
            if not events:
                return "No past appointments found in the last 12 months."
            lines = []
            for e in events:
                raw = e.get("summary", "")
                import re as _re
                m = _re.match(r"Health \[(\w+)\]: (.*)", raw)
                if m:
                    patient_label, title = m.group(1), m.group(2)
                else:
                    patient_label = "Jana"
                    title = raw.replace("Health: ", "")
                start = e["start"].get("dateTime", e["start"].get("date", ""))
                dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(TIMEZONE)
                line = f"{dt.strftime('%A, %d %b %Y at %H:%M')} [{patient_label}] — {title}"
                location = e.get("location", "")
                if location:
                    line += f" | Location: {location}"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            return f"Could not fetch past appointments: {e}"

    elif name == "delete_appointment":
        try:
            cal_delete(inputs["event_id"])
            return "Appointment deleted."
        except Exception as e:
            return f"Could not delete appointment: {e}"

    elif name == "update_appointment_location":
        try:
            update_appointment_location(inputs["event_id"], inputs["location"])
            return f"Location updated to: {inputs['location']}"
        except Exception as e:
            return f"Could not update location: {e}"

    elif name == "list_reminders":
        reminders = _load_reminders()
        if not reminders:
            return "No active reminders."
        lines = []
        for i, r in enumerate(reminders, 1):
            due = datetime.fromisoformat(r["due"]).strftime("%d %b at %H:%M Toronto")
            repeat_label = f" (repeats {r['repeat']})" if r.get("repeat") else ""
            lines.append(f"{i}. {r['message']} — {due}{repeat_label} [id:{r['id']}]")
        return "\n".join(lines)

    elif name == "delete_reminder":
        try:
            reminder_id = inputs["reminder_id"]
            reminders = _load_reminders()
            updated = [r for r in reminders if r["id"] != reminder_id]
            if len(updated) == len(reminders):
                return f"No reminder found with ID: {reminder_id}"
            _save_reminders(updated)
            if job_queue:
                jobs = job_queue.get_jobs_by_name(reminder_id)
                for job in jobs:
                    job.schedule_removal()
            return f"Reminder cancelled."
        except Exception as e:
            return f"Could not delete reminder: {e}"

    elif name == "update_health_record":
        try:
            append_entry(inputs["text"], heading=inputs.get("heading"))
            return "Added to your health record."
        except Exception as e:
            return f"Could not update the record: {e}"

    elif name == "view_health_record":
        try:
            text = get_recent_entries()
            return text.strip() if text.strip() else "Your health record is empty."
        except Exception as e:
            return f"Could not read the record: {e}"

    elif name == "list_doctors":
        try:
            doctors = list_doctors()
            if not doctors:
                return "No doctors saved yet."
            lines = []
            for d in doctors:
                if not d.get("Doctor"):
                    continue
                parts = [f"{d['Doctor']}"]
                if d.get("Specialty"):
                    parts[0] += f" ({d['Specialty']})"
                if d.get("Clinic"):
                    parts.append(f"Clinic: {d['Clinic']}")
                if d.get("Phone"):
                    parts.append(f"Phone: {d['Phone']}")
                if d.get("Email"):
                    parts.append(f"Email: {d['Email']}")
                if d.get("Address"):
                    parts.append(f"Address: {d['Address']}")
                if d.get("Notes"):
                    parts.append(f"Notes: {d['Notes']}")
                lines.append(" | ".join(parts))
            return "\n".join(lines)
        except Exception as e:
            return f"Could not read the doctors list: {e}"

    elif name == "save_doctor":
        try:
            upsert_doctor(
                doctor=inputs.get("doctor", ""),
                specialty=inputs.get("specialty", ""),
                clinic=inputs.get("clinic", ""),
                address=inputs.get("address", ""),
                phone=inputs.get("phone", ""),
                email=inputs.get("email", ""),
                notes=inputs.get("notes", ""),
            )
            return f"Saved {inputs['doctor']} to your contacts spreadsheet."
        except Exception as e:
            return f"Could not save doctor: {e}"

    elif name == "delete_doctor_row":
        try:
            delete_doctor_row(int(inputs["row_number"]))
            return f"Row {inputs['row_number']} deleted from the doctors spreadsheet."
        except Exception as e:
            return f"Could not delete row: {e}"

    elif name == "check_date":
        try:
            dt = datetime.strptime(inputs["date"], "%d-%b-%Y").replace(tzinfo=TIMEZONE)
            return f"{inputs['date']} is a {dt.strftime('%A')}."
        except Exception as e:
            return f"Could not parse date: {e}"

    elif name == "send_email":
        try:
            from services.gmail import send_notification
            send_notification(inputs["subject"], inputs["body"])
            return "Email sent."
        except Exception as e:
            return f"Could not send email: {e}"

    return f"Unknown tool: {name}"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # Identify sender by Telegram display name
    user = update.effective_user
    sender_name = (user.full_name or user.username or "Unknown").strip()
    labeled_text = f"[From {sender_name}]: {text}"

    # saved_history: plain text only, persisted to disk
    saved_history = _load_history(chat_id)
    saved_history.append({"role": "user", "content": labeled_text})

    # api_history: full exchange including tool calls, in-memory only for this turn
    api_history = list(saved_history)

    today = datetime.now(TIMEZONE).strftime("%A, %d %B %Y at %H:%M")
    system = SYSTEM_PROMPT.format(today=today)

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system,
            tools=TOOLS,
            messages=api_history,
        )

        # Agentic loop: handle tool calls until Claude gives a final text response
        while response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(
                        block.name,
                        block.input,
                        job_queue=context.job_queue,
                        chat_id=chat_id,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Feed tool results back into api_history only (SDK objects, not serializable)
            api_history.append({"role": "assistant", "content": response.content})
            api_history.append({"role": "user", "content": tool_results})

            await context.bot.send_chat_action(chat_id=chat_id, action="typing")

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=system,
                tools=TOOLS,
                messages=api_history,
            )

        # Extract final text
        reply = ""
        for block in response.content:
            if hasattr(block, "text"):
                reply += block.text

        if not reply:
            reply = "Done."

        # Save only plain text to disk — no SDK objects
        saved_history.append({"role": "assistant", "content": reply})
        _save_history(chat_id, saved_history)

        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"Brain error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong. Try again.")
