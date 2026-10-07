# -*- coding: utf-8 -*-
"""Regression suite for PdfDocument.

Every test here encodes a bug that actually shipped at some point:
font substitution on move, cumulative faux-bold, soft-hyphen swaps,
collateral-line corruption, temp-file leaks. If one of these goes red,
that exact user-visible bug is back.
"""
import glob
import os
import zipfile

import fitz
import pytest

from conftest import bundled_fonts, find_span, refind
from wnyeditpdf.document import PdfDocument


# ---------------------------------------------------------------- move: font
class TestMoveKeepsFont:
    def test_move_keeps_font_and_size(self, doc):
        """v5.6.0 bug: moving Thai text swapped Sarabun for a lookalike."""
        sp = find_span(doc, 0, "เพื่อเป็น")
        doc.move_span(0, sp, 5, 0, doc.default_thai_font)
        after = find_span(doc, 0, "เพื่อเป็น")
        assert after["font"] == sp["font"]
        assert after["size"] == pytest.approx(sp["size"])
        assert len(after["text"]) == len(sp["text"])

    def test_move_does_not_add_fonts(self, doc):
        """The Tm fast path must not register any new font object."""
        n0 = len(doc.doc[0].get_fonts())
        sp = find_span(doc, 0, "เพื่อเป็น")
        doc.move_span(0, sp, 5, 0, doc.default_thai_font)
        assert len(doc.doc[0].get_fonts()) == n0

    def test_move_preserves_actualtext(self, doc):
        """ActualText markers carry Thai combining marks for extraction -
        the move path must leave them in the content stream."""
        import re
        def count():
            return sum(len(re.findall(rb"ActualText",
                                      doc.doc.xref_stream(x)))
                       for x in doc.doc[0].get_contents())
        before = count()
        assert before > 0
        sp = find_span(doc, 0, "เพื่อเป็น")
        doc.move_span(0, sp, 5, 0, doc.default_thai_font)
        assert count() == before

    def test_repeated_moves_do_not_thicken(self, doc):
        """v5.6.x bug: every arrow-key nudge stacked faux bold / ghosts."""
        sp = find_span(doc, 0, "เพื่อเป็น")
        text = sp["text"]
        bb = fitz.Rect(sp["bbox"])
        pix = doc.doc[0].get_pixmap(dpi=200, clip=bb)
        base_ink = sum(1 for i in range(0, len(pix.samples), pix.n)
                       if pix.samples[i] < 128)
        for _ in range(5):
            doc.move_span(0, sp, 3, 0, doc.default_thai_font)
            bb2 = fitz.Rect(bb.x0 + 3, bb.y0, bb.x1 + 3, bb.y1)
            sp = refind(doc, 0, text, (bb2.x0 + bb2.x1) / 2,
                        (bb2.y0 + bb2.y1) / 2)
            assert sp is not None
            bb = fitz.Rect(sp["bbox"])
        pix = doc.doc[0].get_pixmap(dpi=200, clip=bb)
        ink = sum(1 for i in range(0, len(pix.samples), pix.n)
                  if pix.samples[i] < 128)
        assert ink <= base_ink * 1.10   # no cumulative thickening

    def test_move_external_font(self, loma_doc):
        """Fonts absent from fonts/ must survive moves untouched."""
        sp = find_span(loma_doc, 0, "สวัสดี")
        for _ in range(3):
            loma_doc.move_span(0, sp, 5, 0, None)
            sp = find_span(loma_doc, 0, "สวัสดี")
        assert sp["font"] == "Loma"
        assert sp["size"] == pytest.approx(18.0, abs=0.5)


# ------------------------------------------------------------ move: overlap
class TestOverlapMoves:
    def test_overlap_leaves_neighbor_alone(self, doc):
        """v5.6.8 bug: lines a dragged span touched were re-typeset in the
        substitute font, drifting position and width."""
        tgt = find_span(doc, 0, "เพื่อเป็น")
        below = next(s for s in doc.spans(0)
                     if s["text"].startswith("เทคโนโลยี และนโยบาย"))
        prefix = below["text"][:25]
        orig_y = below["bbox"][1]
        orig_font = below["font"]
        dy = below["bbox"][1] - tgt["bbox"][1]
        doc.move_span(0, tgt, 0, dy, doc.default_thai_font)
        text = tgt["text"]
        for _ in range(4):
            cand = [s for s in doc.spans(0) if s["text"] == text]
            if not cand:
                break
            doc.move_span(0, cand[0], 3, 0, doc.default_thai_font)
        bl = next(s for s in doc.spans(0) if s["text"].startswith(prefix))
        assert bl["bbox"][1] == pytest.approx(orig_y, abs=0.5)
        assert bl["font"] == orig_font


# --------------------------------------------------------------- text fidelity
class TestTextFidelity:
    def test_hyphen_not_soft_hyphen(self, doc):
        """v5.6.4 bug: '-' round-tripped as U+00AD after a move because the
        subset cmap mapped both code points at the same glyph."""
        tgt = next(s for s in doc.spans(1) if "กลุ่มที่ 2" in s["text"])
        assert "\xad" not in tgt["text"]
        doc.move_span(1, tgt, 5, 0, doc.default_thai_font)
        after = next(s for s in doc.spans(1) if "Next" in s["text"])
        assert "\xad" not in after["text"]
        assert "Next-Gen" in after["text"]

    def test_combining_marks_covered(self, doc):
        """v5.6.6: ActualText recovers U+0E4C etc. that ToUnicode maps to PUA."""
        sp = find_span(doc, 0, "พลิเคชันเพื่อลด")
        emb = doc._embedded_fontfile(0, sp)
        assert emb is not None
        assert doc._font_covers(emb, sp["text"])

    def test_tounicode_parser(self, doc):
        tu = doc._read_tounicode(5)      # BAAAAA+Sarabun subset
        assert len(tu) > 100
        thai = [u for u in tu.values() if 0x0E00 <= u <= 0x0E7F]
        assert len(thai) >= 40

    def test_actualtext_parser(self, doc):
        at = doc._read_actualtext(0)
        pairs = {}
        for res in at.values():
            pairs.update(res)
        assert 0x0E4C in pairs.values()   # thanthakhat recovered


# ----------------------------------------------------------- lifecycle/safety
class TestLifecycle:
    def test_undo_restores_position(self, doc):
        sp = find_span(doc, 0, "เพื่อเป็น")
        x0 = sp["bbox"][0]
        doc.move_span(0, sp, 25, 0, doc.default_thai_font)
        doc.undo()
        sp2 = find_span(doc, 0, "เพื่อเป็น")
        assert sp2["bbox"][0] == pytest.approx(x0, abs=0.3)

    def test_move_after_undo_uses_right_font(self, doc):
        """v5.7.0: stale font-cache after undo mapped wrong glyphs."""
        sp = find_span(doc, 0, "เพื่อเป็น")
        doc.move_span(0, sp, 5, 0, doc.default_thai_font)
        doc.undo()
        sp = find_span(doc, 0, "เพื่อเป็น")
        doc.move_span(0, sp, 5, 0, doc.default_thai_font)
        after = find_span(doc, 0, "เพื่อเป็น")
        assert after["font"] == "Sarabun"
        assert after["size"] == pytest.approx(16.0)

    def test_save_reopen_move(self, doc, tmp_path):
        out = str(tmp_path / "saved.pdf")
        sp = find_span(doc, 0, "เพื่อเป็น")
        doc.move_span(0, sp, 7, 0, doc.default_thai_font)
        doc.save(out)
        from wnyeditpdf.document import PdfDocument
        d2 = PdfDocument()
        assert d2.open(out) is None
        d2.bundled_fonts = doc.bundled_fonts
        sp2 = find_span(d2, 0, "เพื่อเป็น")
        assert sp2 is not None
        d2.move_span(0, sp2, 5, 0, doc.default_thai_font)
        after = find_span(d2, 0, "เพื่อเป็น")
        assert after["font"] == "Sarabun"
        d2.close()

    def test_temp_fonts_cleaned_on_close(self, doc):
        """v5.7.0: extracted subsets leaked into the OS temp dir forever."""
        sp = find_span(doc, 0, "รายละเอียด")
        doc._embedded_fontfile(0, sp)
        created = list(doc._temp_fonts)
        assert created
        doc.close()
        assert doc._temp_fonts == []
        for p in created:
            assert not os.path.exists(p)


# ------------------------------------------------------------------- features
class TestFeatures:
    def test_export_images_zip(self, doc, tmp_path):
        out = str(tmp_path / "pages.zip")
        n = doc.export_images_zip(out, fmt="png")
        assert n == doc.page_count
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            assert len(names) == n
            assert names[0].endswith("_page_001.png")
            assert z.getinfo(names[0]).file_size > 1000

    def test_wrap_text_thai(self, doc):
        """Thai has no spaces - wrapping must fall back to per-character."""
        font = doc.default_thai_font
        lines = doc._wrap_text("เพื่อเป็นการทดสอบการตัดบรรทัดภาษาไทยที่ยาวมาก",
                               16, font, 120)
        assert len(lines) >= 2
        f = doc._cached_font(font)
        for ln in lines:
            assert f.text_length(ln, fontsize=16) <= 120 + 1

    def test_wrap_text_spaces(self, doc):
        lines = doc._wrap_text("one two three four five six seven eight",
                               12, doc.default_thai_font, 80)
        assert len(lines) >= 2
        assert all(" " not in (ln[0], ln[-1]) for ln in lines if ln)

    def test_add_text_wrapped(self, doc):
        n_before = len(list(doc.spans(0)))
        doc.add_text(0, fitz.Point(72, 700),
                     "ทดสอบข้อความยาวที่ควรถูกตัดเป็นหลายบรรทัดโดยอัตโนมัติเมื่อชนขอบขวา",
                     16, (0, 0, 0), doc.default_thai_font, max_width=150)
        assert len(list(doc.spans(0))) >= n_before + 2

    def test_form_fields_empty_doc(self, doc):
        """Sample has no AcroForm - the API must degrade gracefully."""
        assert doc.form_fields(0) == []
        assert doc.form_field_at(0, fitz.Point(100, 100)) is None
        assert doc.has_form() is False

    def test_form_fill_roundtrip(self, tmp_path):
        """Create a real text widget, fill it, reopen, value must persist."""
        path = str(tmp_path / "form.pdf")
        pdf = fitz.open()
        page = pdf.new_page(width=595, height=842)
        w = fitz.Widget()
        w.rect = fitz.Rect(72, 100, 300, 130)
        w.field_name = "fullname"
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        page.add_widget(w)
        pdf.save(path)
        pdf.close()

        from wnyeditpdf.document import PdfDocument
        d = PdfDocument()
        assert d.open(path) is None
        assert d.has_form()
        fields = d.form_fields(0)
        assert len(fields) == 1 and fields[0]["name"] == "fullname"
        d.set_form_field(0, fields[0], "สมชาย ใจดี")
        out = str(tmp_path / "filled.pdf")
        d.save(out)
        d.close()

        d2 = PdfDocument()
        assert d2.open(out) is None
        assert d2.form_fields(0)[0]["value"] == "สมชาย ใจดี"
        d2.close()


# ------------------------------------------------------- save subset of pages
class TestSavePages:
    def test_parse_page_spec_basic(self, doc):
        n = doc.page_count
        assert doc.parse_page_spec("1", n) == [0]
        assert doc.parse_page_spec("1-3", n) == [0, 1, 2]
        assert doc.parse_page_spec("1-2,4", n) == [0, 1, 3]
        assert doc.parse_page_spec(" 1 , 3 ", n) == [0, 2]

    def test_parse_page_spec_open_ended(self, doc):
        n = doc.page_count
        assert doc.parse_page_spec("-2", n) == [0, 1]
        assert doc.parse_page_spec(f"{n-1}-", n) == [n - 2, n - 1]

    def test_parse_page_spec_dedup_and_order(self, doc):
        """Duplicates collapse; typed order is kept so pages can be reordered."""
        assert doc.parse_page_spec("3,1,2,1", doc.page_count) == [2, 0, 1]

    def test_parse_page_spec_rejects_bad_input(self, doc):
        n = doc.page_count
        for bad in ("", "   ", "0", f"{n+1}", "abc", f"1-{n+5}"):
            with pytest.raises(ValueError):
                doc.parse_page_spec(bad, n)

    def test_save_single_page(self, doc, tmp_path):
        out = str(tmp_path / "one.pdf")
        assert doc.save_pages([1], out) == 1
        with fitz.open(out) as sub:
            assert sub.page_count == 1
            # page 2 of the sample carries this heading
            assert "กลุ่มที่ 2" in sub[0].get_text()

    def test_save_pages_keeps_unsaved_edits(self, doc, tmp_path):
        """The subset must reflect what the user sees NOW, not the file on disk."""
        sp = find_span(doc, 0, "เพื่อเป็น")
        doc.move_span(0, sp, 0, 40, doc.default_thai_font)
        out = str(tmp_path / "edited.pdf")
        doc.save_pages([0], out)
        with fitz.open(out) as sub:
            moved = next(b for b in sub[0].get_text("dict")["blocks"]
                         if b.get("type", 0) == 0
                         and "เพื่อเป็น" in str(b))
            assert moved is not None

    def test_save_pages_does_not_change_open_document(self, doc, tmp_path):
        """Exporting a subset is not 'save as' - the working file stays put."""
        original_path = doc.path
        original_count = doc.page_count
        doc.save_pages([0], str(tmp_path / "sub.pdf"))
        assert doc.path == original_path
        assert doc.page_count == original_count

    def test_save_pages_rejects_empty(self, doc, tmp_path):
        with pytest.raises(ValueError):
            doc.save_pages([], str(tmp_path / "x.pdf"))


# ---------------------------------------------------------------- rotated pages
def _rotated_scan(tmp_path, rot, crop=None):
    """A scanner-style page: a sideways image page saved with /Rotate."""
    path = str(tmp_path / f"scan{rot}.pdf")
    pdf = fitz.open()
    page = pdf.new_page(width=243, height=153)      # ID-card size, landscape
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40))
    pix.clear_with(200)
    page.insert_image(page.rect, pixmap=pix)
    page.insert_text((20, 40), "scanned label", fontsize=12)
    if crop:
        pdf.xref_set_key(page.xref, "CropBox", crop)
    page.set_rotation(rot)
    pdf.save(path)
    pdf.close()
    return path


def _upright_lines(page):
    """(direction, bbox) of every text line as the user sees it."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            out.append((ln["dir"], fitz.Rect(ln["bbox"]),
                        "".join(s["text"] for s in ln["spans"])))
    return out


class TestRotatedPages:
    @pytest.mark.parametrize("rot", [90, 180, 270])
    def test_added_text_is_horizontal_where_clicked(self, tmp_path, rot):
        """Bug: on a scanned ID card saved with /Rotate, new text came out
        vertical (sideways) and far from the click point."""
        d = PdfDocument()
        assert d.open(_rotated_scan(tmp_path, rot)) is None
        d.bundled_fonts = bundled_fonts()
        d.default_thai_font = d.bundled_fonts.get("THSarabunNew")
        view = d.page_rect(0)
        before = d.doc[0].get_pixmap()
        d.add_text(0, fitz.Point(30, 60), "ทดสอบ", 16, (0, 0, 0),
                   d.default_thai_font)
        page = d.doc[0]
        assert page.rect == view                     # page looks the same size
        added = [ln for ln in _upright_lines(page) if "scanned" not in ln[2]]
        assert added
        direction, bbox, _ = added[0]
        assert direction == pytest.approx((1, 0), abs=1e-3)
        assert bbox.x0 == pytest.approx(30, abs=3)
        assert bbox.y1 == pytest.approx(60, abs=8)
        assert before.width == page.get_pixmap().width
        d.close()

    @pytest.mark.parametrize("rot", [90, 180, 270])
    def test_opening_keeps_appearance(self, tmp_path, rot):
        path = _rotated_scan(tmp_path, rot, crop="[10 5 230 150]")
        with fitz.open(path) as raw:
            want = raw[0].get_pixmap().samples
            label = [fitz.Rect(ln[1]) * raw[0].rotation_matrix
                     for ln in _upright_lines(raw[0])]
        d = PdfDocument()
        assert d.open(path) is None
        assert d.doc[0].rotation == 0
        assert d.doc[0].get_pixmap().samples == want
        # existing text is reported in the coordinates the user clicks in
        got = [ln[1] for ln in _upright_lines(d.doc[0])]
        assert len(got) == len(label)
        for a, b in zip(got, label):
            assert a.x0 == pytest.approx(b.x0, abs=1)
            assert a.y0 == pytest.approx(b.y0, abs=1)
        d.close()

    def test_rotate_page_then_add_text(self, tmp_path):
        d = PdfDocument()
        assert d.open(_rotated_scan(tmp_path, 0)) is None
        d.default_thai_font = bundled_fonts().get("THSarabunNew")
        d.rotate_page(0, 90)
        assert d.page_rect(0).width == pytest.approx(153)
        d.add_text(0, fitz.Point(20, 30), "abc", 12, (0, 0, 0), None)
        new = [ln for ln in _upright_lines(d.doc[0]) if ln[2] == "abc"]
        assert new and new[0][0] == pytest.approx((1, 0), abs=1e-3)
        d.close()

    def test_highlight_lands_where_dragged(self, tmp_path):
        d = PdfDocument()
        assert d.open(_rotated_scan(tmp_path, 90)) is None
        d.highlight(0, fitz.Rect(10, 10, 100, 30))
        page = d.doc[0]                  # keep the page alive while reading
        r = next(iter(page.annots())).rect
        assert r.x0 == pytest.approx(10, abs=6)
        assert r.y1 == pytest.approx(30, abs=6)
        d.close()
