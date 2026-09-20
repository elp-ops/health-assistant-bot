# Changelog

Plain-English record of real improvements to this bot, kept so anyone using this as a template can see what changed and why, not just raw commit history.

## 2026-07-24

- **Bot can now clean up its own stale reminders.** Previously, if it noticed an expired or duplicate reminder, it would just tell the patient/family member to go delete it manually — even though it already had the tool to do it itself. Now it asks "want me to clear these?" and does it on confirmation. (`handlers/brain.py`)
- **Removed a hardcoded personal email** that was silently used as a fallback default for the calendar ID. If you're setting this up for yourself, you now have to set `GOOGLE_CALENDAR_ID` explicitly — no risk of accidentally inheriting someone else's default. (`config.py`)
- **Added a daily uptime check**, run separately from the main bot so it can catch a full outage (this bot went silent for months without anyone noticing because its hosting platform showed "online" even though it had stopped actually receiving messages — see the check's own comments for the full story). Not something a template user strictly needs, but worth knowing the pattern exists. (`monitor/` — private repo only, excluded from the public template since it points at a specific Telegram chat)
