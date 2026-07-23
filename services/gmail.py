"""
Gmail service.
Sends notification emails to Elena via SMTP with an App Password.

Setup:
  1. Enable 2-Step Verification on your Google account
  2. Go to myaccount.google.com > Security > App passwords
  3. Create an app password for "Mail"
  4. Add to .env: GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
  5. Add to .env: GMAIL_SENDER=elena.lpris@gmail.com
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import NOTIFICATION_EMAIL, GMAIL_APP_PASSWORD, GMAIL_SENDER

logger = logging.getLogger(__name__)


def send_notification(subject: str, body: str, to: str = None):
    """Send a plain-text notification email via SMTP."""
    recipient = to or NOTIFICATION_EMAIL
    if not recipient:
        logger.warning("No notification email configured. Skipping.")
        return

    if not GMAIL_APP_PASSWORD or not GMAIL_SENDER:
        raise ValueError(
            "GMAIL_APP_PASSWORD and GMAIL_SENDER must be set in .env. "
            "See services/gmail.py for setup instructions."
        )

    msg = MIMEMultipart()
    msg["From"] = GMAIL_SENDER
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER, recipient, msg.as_string())

    logger.info(f"Email sent: {subject}")
