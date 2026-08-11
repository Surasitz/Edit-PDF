# -*- coding: utf-8 -*-
"""Shared fixtures.

`sample_thai.pdf` is a real Word-exported Thai document (subset fonts,
ActualText markers, Identity-H) - the exact class of file every historical
font bug came from. Synthetic PDFs can't reproduce Word's quirks, so the
regression tests run against the real thing.
"""
import os
import sys

import fitz
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wnyeditpdf.document import PdfDocument  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "sample_thai.pdf")
FONTS_DIR = os.path.join(ROOT, "fonts")


def bundled_fonts():
    return {os.path.splitext(f)[0]: os.path.join(FONTS_DIR, f)
            for f in os.listdir(FONTS_DIR)
            if f.lower().endswith((".ttf", ".otf"))}


@pytest.fixture
def doc():
    """The Word-exported Thai sample, opened with bundled fonts configured."""
    d = PdfDocument()
    assert d.open(FIXTURE) is None
    d.bundled_fonts = bundled_fonts()
    d.default_thai_font = d.bundled_fonts.get("Sarabun-Regular")
    yield d
    d.close()


@pytest.fixture
def loma_doc(tmp_path):
    """A PDF using a font that is NOT in the project's fonts/ folder -
    exercises the embedded-font path with zero bundled support."""
    loma = "/usr/share/fonts/opentype/tlwg/Loma.otf"
    if not os.path.exists(loma):
        pytest.skip("Loma system font not available")
    path = str(tmp_path / "loma.pdf")
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    for y, size, text in (
            (100, 18, "สวัสดีครับ นี่คือทดสอบฟอนต์ Loma ที่ไม่มีในโปรเจค"),
            (150, 16, "เพื่อเป็นการทดสอบว่าฟอนต์เพี้ยนหรือไม่ ต้องมีตัวอักษรครบ")):
        tw = fitz.TextWriter(page.rect)
        tw.append(fitz.Point(72, y), text,
                  font=fitz.Font(fontfile=loma), fontsize=size)
        tw.write_text(page)
    pdf.save(path)
    pdf.close()
    d = PdfDocument()
    assert d.open(path) is None
    d.bundled_fonts = bundled_fonts()
    yield d
    d.close()


def find_span(d, pno, needle):
    for sp in d.spans(pno):
        if needle in sp["text"]:
            return sp
    return None


def refind(d, pno, text, cx, cy):
    """Nearest span with the same text (mirrors the UI's re-find logic)."""
    cand = [s for s in d.spans(pno) if s["text"] == text]
    if not cand:
        return None
    return min(cand, key=lambda s: (
        (fitz.Rect(s["bbox"]).x0 + fitz.Rect(s["bbox"]).x1) / 2 - cx) ** 2
        + ((fitz.Rect(s["bbox"]).y0 + fitz.Rect(s["bbox"]).y1) / 2 - cy) ** 2)
