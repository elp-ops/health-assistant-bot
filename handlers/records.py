"""
Health record handler.

Usage:
  /record <text> — append a freeform note to the health doc
  e.g. /record Blood pressure 120/80. Felt fine. Dr said to come back in 6 months.

  /viewrecord — show the most recent entries from the health doc
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.google_docs import append_entry, get_recent_entries

logger = logging.getLogger(__name__)


async def update_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /record <text>\n"
            "e.g. /record Blood pressure 120/80. Felt fine."
        )
        return

    text = " ".join(context.args)

    try:
        append_entry(text)
    except Exception as e:
        logger.error(f"Record update error: {e}", exc_info=True)
        await update.message.reply_text(
            "Could not update the health record. Check Google Docs setup."
        )
        return

    await update.message.reply_text("Added to your health record.")


async def view_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = get_recent_entries()
    except Exception as e:
        logger.error(f"Record view error: {e}", exc_info=True)
        await update.message.reply_text(
            "Could not read the health record. Check Google Docs setup."
        )
        return

    if not text.strip():
        await update.message.reply_text("Your health record is empty.")
        return

    await update.message.reply_text(f"Recent health record entries:\n\n{text.strip()}")
