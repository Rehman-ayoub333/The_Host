import io
import json
import re

from PIL import Image
import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL
from schemas import ExtractionResult

PROMPT_TEMPLATE = """
You are a document-extraction system. You will be shown one photo of a real-world document.

Do the following:
1. Classify the document into exactly one of: receipt, invoice, prescription, id_card, form, unknown.
2. Extract every meaningful field you can read, as a list of objects with: key (snake_case), label (human readable), value (as text, exactly as it appears), and confidence (your own estimate from 0.0 to 1.0 of how certain you are this value is correct given image quality and legibility).
3. Also produce raw_text: a full plain-text transcription of everything visible on the document.
4. Produce overall_confidence: a single 0.0–1.0 estimate of how confident you are in the extraction as a whole.

Respond with ONLY valid JSON matching this exact shape, no markdown fences, no extra commentary:

{
  "document_type": "...",
  "fields": [
    {"key": "...", "label": "...", "value": "...", "confidence": 0.0}
  ],
  "raw_text": "...",
  "overall_confidence": 0.0
}

If the document is a receipt or invoice, you MUST include a field with key "line_items" whose value is a readable summary string of each item and amount (e.g. "Bread 200, Milk 150, Eggs 300"), and a separate field with key "total" for the printed total amount.
If the document is an id_card, you MUST attempt to include fields with keys: full_name, date_of_birth, id_number, expiry_date (use value "not found" if genuinely not visible, with confidence 0.0).
If the document is a prescription, you MUST attempt to include fields with keys: patient_name, doctor_name, date, medications.
"""


def _preprocess_image(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("RGB")

    width, height = image.size
    longer_side = max(width, height)
    max_dimension = 1600

    if longer_side > max_dimension:
        scale = max_dimension / longer_side
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _extract_json_fragment(text: str) -> str:
    if not text:
        raise ValueError("Gemini returned an empty response.")

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return fenced_match.group(1)

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return brace_match.group(0)

    return text.strip()


def extract(image_bytes: bytes) -> ExtractionResult:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to backend/.env before running extraction.")

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        preprocessed_bytes = _preprocess_image(image_bytes)
        image = Image.open(io.BytesIO(preprocessed_bytes)).convert("RGB")

        model = genai.GenerativeModel(model_name=GEMINI_MODEL)
        response = model.generate_content(
            [PROMPT_TEMPLATE, image],
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json"),
            request_options={"timeout": 15},
        )
        raw_text = getattr(response, "text", "")
        if not raw_text:
            raise ValueError("Gemini returned no text content.")

        json_text = _extract_json_fragment(raw_text)
        payload = json.loads(json_text)
        payload["source"] = "gemini"
        return ExtractionResult.model_validate(payload)
    except Exception as exc:  # pragma: no cover - boundary conversion handled by caller
        raise RuntimeError(f"Gemini extraction failed: {exc}") from exc
