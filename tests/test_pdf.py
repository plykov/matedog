"""PDF extraction and import tests."""

import pytest

from matedog import pdfx
from tests.pdf_fixture import make_pdf


def test_extract_text():
    pdf = make_pdf(["The cat sleeps on the sofa.", "Delivery takes 14 days."])
    text = pdfx.extract_text(pdf)
    assert "The cat sleeps on the sofa." in text
    assert "Delivery takes 14 days." in text


def test_reject_non_pdf():
    with pytest.raises(ValueError, match="Not a readable PDF"):
        pdfx.extract_text(b"this is not a pdf at all")


def test_reject_textless_pdf():
    pdf = make_pdf([])
    with pytest.raises(ValueError, match="No extractable text"):
        pdfx.extract_text(pdf)
