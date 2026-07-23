"""
Vision service.
Reads a medical report image and extracts structured information.
Uses Claude (default) or Gemini.
"""

import base64
import logging
import json
from pathlib import Path

from config import VISION_PROVIDER, ANTHROPIC_API_KEY, GEMINI_API_KEY

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """
You are reading a medical document or report image.

Extract the following information if present:
- doctor_name: full name of the doctor or specialist
- specialty: medical specialty (e.g. Cardiology, Dentist, GP)
- clinic_or_hospital: name of the clinic or hospital
- phone: phone number(s)
- email: email address if present
- report_date: date shown on this document (when it was issued). Always include the year.
- appointment_date: the date of the scheduled appointment if this is an appointment reminder or confirmation. Format: DD Mon YYYY (e.g. 21 May 2026). Always include the year — if the year is not visible, use 2026.
- appointment_time: time of the appointment in 24h format (e.g. 14:30). Leave empty if not shown.
- report_type: type of document (e.g. Blood Test, X-Ray, Consultation Note, Appointment Reminder, Prescription)
- medication_name: if this is a prescription, the name of the medication(s) prescribed (e.g. "Clopidogrel 75mg", "Atorvastatin"). Leave empty for non-prescription documents.
- key_findings: a short plain-English summary of the key findings, results, or appointment details (2-4 sentences max)
- patient_name: patient name if shown

Important: Always include the year in every date field. If the year is not visible in the document, assume 2026.

Respond ONLY with a valid JSON object using these exact keys.
If a field is not found, use an empty string "".
Do not add any explanation outside the JSON.
"""


def extract_report_data(image_path: str) -> dict:
    """
    Read an image file and return extracted medical data as a dict.
    """
    provider = VISION_PROVIDER.lower()

    if provider == "claude":
        return _extract_with_claude(image_path)
    elif provider == "gemini":
        return _extract_with_gemini(image_path)
    else:
        raise ValueError(f"Unknown vision provider: {provider}")


def _extract_with_claude(image_path: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    suffix = Path(image_path).suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(suffix, "image/jpeg")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()
    return _parse_json(raw)


def _extract_with_gemini(image_path: str) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    import PIL.Image
    img = PIL.Image.open(image_path)

    response = model.generate_content([EXTRACTION_PROMPT, img])
    raw = response.text.strip()
    return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Could not parse vision response as JSON: {raw}")
        return {"key_findings": raw}
