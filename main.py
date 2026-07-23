import logging
import os
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from config import TELEGRAM_BOT_TOKEN
from handlers.appointments import (
    add_appointment,
    list_appointments,
    delete_appointment,
)
from handlers.reminders import set_reminder, list_reminders, delete_reminder
from handlers.records import update_record, view_record
from handlers.reports import handle_photo
from handlers.reminders import restore_reminders
from handlers.brain import handle_message

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi Jana. I'm Dr. Tony, your health assistant.\n\n"
        "Here's what I can do:\n\n"
        "/appointment — add a doctor appointment\n"
        "/appointments — list upcoming appointments\n"
        "/remind — set a custom reminder\n"
        "/reminders — list your reminders\n"
        "/record — add a note to your health record\n"
        "/viewrecord — view recent health record entries\n\n"
        "Send me a photo or screenshot of a report and I'll read it, save it, and log it."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n\n"
        "/appointment <doctor> <date> <time> — add appointment\n"
        "  e.g. /appointment Dentist 15-Apr 10:00\n\n"
        "/appointments — list upcoming appointments\n\n"
        "/remind <message> <date> <time> — set a reminder\n"
        "  e.g. /remind Book follow-up with cardiologist 01-Jul 09:00\n\n"
        "/reminders — list active reminders\n\n"
        "/record <text> — add note to health record\n"
        "  e.g. /record Blood pressure normal, 120/80\n\n"
        "/viewrecord — show recent entries\n\n"
        "Photo — send any medical report screenshot to save and parse it."
    )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "I don't recognise that command. Type /help to see what I can do."
    )


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # Appointments
    app.add_handler(CommandHandler("appointment", add_appointment))
    app.add_handler(CommandHandler("appointments", list_appointments))
    app.add_handler(CommandHandler("deleteappointment", delete_appointment))

    # Reminders
    app.add_handler(CommandHandler("remind", set_reminder))
    app.add_handler(CommandHandler("reminders", list_reminders))
    app.add_handler(CommandHandler("deletereminder", delete_reminder))

    # Health record
    app.add_handler(CommandHandler("record", update_record))
    app.add_handler(CommandHandler("viewrecord", view_record))

    # Photo/report handler
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    # Brain: all plain text goes here
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Fallback for unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Re-schedule any reminders that survived a restart
    restore_reminders(app)

    logger.info("Health bot starting...")

    webhook_url = os.getenv("WEBHOOK_URL")
    port = int(os.getenv("PORT", 8080))

    if webhook_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=f"{webhook_url}/{TELEGRAM_BOT_TOKEN}",
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
