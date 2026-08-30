"""
Extraction module: turn an uploaded file into plain text.

Order of attempts (cheapest/most-reliable first, per the blueprint):
  1. Text-based PDF -> extract directly, no OCR needed at all
  2. Image / scanned PDF -> Tesseract OCR (free, local, no API quota used)
  3. Only if Tesseract's result looks too thin/empty -> fall back to a
     vision-capable pooled key for one-shot extraction

This keeps almost all uploads off the vision-key budget entirely, which
was the whole point of doing extraction this way instead of sending
images straight into a vision model for every question about them.
"""

import io

import pdfplumber
import pytesseract
from PIL import Image

# Below this many extracted characters, treat Tesseract's result as
# unreliable and try the vision fallback instead. Tuned loosely — a real
# document/page almost always produces far more than this.
MIN_OCR_CHARS = 20


def extract_from_pdf_bytes(data: bytes) -> str:
    """Direct text extraction for text-based PDFs. Returns '' if the PDF
    turns out to have no extractable text (i.e. it's actually scanned)."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts).strip()


def ocr_image_bytes(data: bytes) -> str:
    """Tesseract OCR on a single image."""
    image = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(image).strip()


def ocr_pdf_bytes(data: bytes) -> str:
    """OCR a scanned PDF page-by-page by rasterizing with pdfplumber."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            pil_image = page.to_image(resolution=200).original
            page_text = pytesseract.image_to_string(pil_image).strip()
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts).strip()


async def extract_text(filename: str, data: bytes, vision_fallback_fn=None) -> dict:
    """
    Returns {"text": str, "method": "pdf_text" | "ocr" | "vision_fallback",
             "needs_review": bool}

    `vision_fallback_fn` is an optional async callable(image_bytes) -> str,
    injected by the caller so this module doesn't need to know about the
    key pool directly.
    """
    is_pdf = filename.lower().endswith(".pdf")
    text = ""

    try:
        if is_pdf:
            text = extract_from_pdf_bytes(data)
            if len(text) >= MIN_OCR_CHARS:
                return {"text": text, "method": "pdf_text", "needs_review": False}
            # Looked like a scanned PDF — try OCR on it
            text = ocr_pdf_bytes(data)
            if len(text) >= MIN_OCR_CHARS:
                return {"text": text, "method": "ocr", "needs_review": True}
        else:
            text = ocr_image_bytes(data)
            if len(text) >= MIN_OCR_CHARS:
                return {"text": text, "method": "ocr", "needs_review": True}
    except pytesseract.TesseractNotFoundError:
        text = ""

    # OCR gave too little (handwriting, low-quality scan) — try vision once
    if vision_fallback_fn is not None:
        try:
            vision_text = await vision_fallback_fn(data)
            if vision_text:
                return {"text": vision_text, "method": "vision_fallback", "needs_review": True}
        except Exception:
            pass

    # Nothing worked — return whatever OCR produced (possibly empty) so the
    # user can still see/edit it rather than getting a hard failure.
    return {"text": text, "method": "ocr", "needs_review": True}
