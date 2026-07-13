"""PDF text extraction for translation import.

Import-only: text is extracted page by page and segmented for translation;
the translated result is exported as XLIFF or plain text. Layout round-trip
back into PDF is out of scope (MateCat solves this with external converters).
Scanned/image-only PDFs have no extractable text and are rejected — run OCR
first.
"""

import io

from pypdf import PdfReader


def extract_text(data: bytes) -> str:
    """Extract plain text from a PDF, pages separated by blank lines."""
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        raise ValueError(f"Not a readable PDF: {e}") from e
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:
            raise ValueError("PDF is password-protected") from e
    pages = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(text)
    full = "\n\n".join(pages)
    if not full.strip():
        raise ValueError("No extractable text found — this looks like a scanned "
                         "(image-only) PDF. Run OCR on it first.")
    return full
