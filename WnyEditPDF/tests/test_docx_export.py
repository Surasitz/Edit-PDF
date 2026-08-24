# -*- coding: utf-8 -*-
"""Regression suite for the PDF -> Word exporter.

The promise this feature makes is narrow and testable: the words that come out
in Word are the words that were in the PDF, in the same font at the same size.
Everything here guards that promise - character-level fidelity, the
complex-script run properties Word needs before it will render Thai at all,
and the Thai sequences that PDF producers habitually mangle.
"""
import collections
import os
import zipfile
import xml.etree.ElementTree as ET

import fitz
import pytest

from wnyeditpdf import docx_export as dx
from wnyeditpdf.document import PdfDocument

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def cps(s):
    return " ".join("%04X" % ord(c) for c in s)


def body(path):
    """The parsed word/document.xml of an exported file."""
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read("word/document.xml"))


def all_text(root):
    return "".join(t.text or "" for t in root.iter(W + "t"))


def pdf_text(d):
    """Every character the PDF holds, after the repair pass."""
    return "".join(
        dx.repair_text(sp["text"])
        for pno in range(d.page_count)
        for blk in dx.page_blocks(d.doc[pno])
        for ln in blk["lines"] for sp in ln["spans"])


def squash(s):
    """Compare ignoring whitespace: line wrapping legitimately moves spaces
    around, but no visible character may appear or vanish."""
    return collections.Counter("".join(s.split()))


# ------------------------------------------------------------- Thai repairs
class TestThaiRepair:
    @pytest.mark.parametrize("broken, fixed", [
        ("คํา", "คำ"),        # NIKHAHIT + SARA AA
        ("คํ่า", "ค่ำ"),       # NIKHAHIT + tone + SARA AA
        ("ค่ํา", "ค่ำ"),       # tone + NIKHAHIT + SARA AA
    ])
    def test_sara_am_is_recomposed(self, broken, fixed):
        """A decomposed SARA AM renders as "ํา" instead of "ำ" and makes the
        word unsearchable in Word."""
        assert dx.repair_text(broken) == fixed, cps(dx.repair_text(broken))

    @pytest.mark.parametrize("broken, fixed", [
        ("ก่ิ", "กิ่"),       # tone written before the upper vowel
        ("กุ้", "กุ้"),       # tone written before the lower vowel
    ])
    def test_marks_are_put_in_canonical_order(self, broken, fixed):
        assert dx.repair_text(broken) == fixed, cps(dx.repair_text(broken))

    @pytest.mark.parametrize("good", [
        "สวัสดีครับ", "กิ่ง", "น้ำ", "ค่ำคืน", "ทดสอบ ๑๒๓", "plain ASCII",
    ])
    def test_correct_text_is_left_alone(self, good):
        """The repair must be a no-op on well-formed text, or it becomes the
        thing that corrupts documents."""
        assert dx.repair_text(good) == good

    def test_repair_is_idempotent(self):
        once = dx.repair_text("คํ่า")
        assert dx.repair_text(once) == once

    def test_invisible_characters_are_dropped(self):
        assert dx.repair_text("A B​C­D﻿E") == "A BCDE"

    def test_control_characters_cannot_reach_the_xml(self):
        """A stray control byte in a PDF would make the .docx unopenable."""
        assert "\x00" not in dx.repair_text("ab\x00c\x0bd")


class TestUndecodableDetection:
    def test_private_use_text_is_flagged(self):
        assert dx.undecodable_ratio("".join(chr(0xE000 + i) for i in range(9))) == 1.0

    def test_real_thai_is_not_flagged(self):
        assert dx.undecodable_ratio("สวัสดีครับ ทดสอบภาษาไทย") == 0.0


class TestFontNames:
    @pytest.mark.parametrize("ps_name, family", [
        ("ABCDEF+THSarabunPSK", "TH SarabunPSK"),
        ("THSarabunNew-Bold", "TH Sarabun New"),
        ("ArialMT", "Arial"),
        ("TimesNewRomanPS-BoldMT", "Times New Roman"),
        ("AngsanaNew,Bold", "Angsana New"),
        ("BCDEFG+Sarabun-SemiBold", "Sarabun"),
    ])
    def test_postscript_names_become_word_families(self, ps_name, family):
        assert dx.font_family(ps_name) == family

    def test_bold_is_taken_from_the_name_when_the_flag_is_missing(self):
        """Subset fonts often carry the weight only in their name."""
        fam, bold, ital, _ = dx.span_style({"font": "ABCDEF+THSarabunPSK-Bold",
                                            "flags": 0})
        assert (fam, bold, ital) == ("TH SarabunPSK", True, False)

    def test_bold_is_taken_from_the_flag_when_the_name_is_missing(self):
        assert dx.span_style({"font": "Sarabun", "flags": 16})[1] is True


# ------------------------------------------------------------ real documents
@pytest.fixture(params=[True, False], ids=["layout", "flow"])
def exported(request, doc, tmp_path):
    """The Thai sample exported both ways."""
    out = str(tmp_path / "out.docx")
    stats = doc.export_docx(out, layout=request.param)
    return out, stats, request.param


class TestFidelity:
    def test_every_character_survives(self, exported, doc):
        """The whole point of the feature: nothing added, nothing lost."""
        out, _stats, _layout = exported
        assert squash(all_text(body(out))) == squash(pdf_text(doc))

    def test_font_size_and_weight_survive(self, exported, doc):
        out, _stats, _layout = exported
        want = collections.Counter()
        for pno in range(doc.page_count):
            for blk in dx.page_blocks(doc.doc[pno]):
                for ln in blk["lines"]:
                    for sp in ln["spans"]:
                        if sp["text"].strip():
                            fam, bold, _i, _s = dx.span_style(sp)
                            want[(fam, dx._halfpt(sp["size"]), bold)] += 1
        got = collections.Counter()
        for r in body(out).iter(W + "r"):
            pr = r.find(W + "rPr")
            if pr is None:
                continue
            got[(pr.find(W + "rFonts").get(W + "ascii"),
                 int(pr.find(W + "sz").get(W + "val")),
                 pr.find(W + "b") is not None)] += 1
        # adjacent runs that share formatting are merged, so compare the set of
        # (font, size, weight) combinations rather than the counts
        assert set(got) == set(want)


class TestWordWillRenderThai:
    """Word chooses the face for Thai from the complex-script slot. Miss any of
    these and a 16 pt Sarabun document opens as 11 pt Calibri-with-fallback -
    the single most common way a PDF-to-Word converter 'ruins' a Thai file."""

    def test_every_run_sets_a_complex_script_font(self, exported):
        out, _stats, _layout = exported
        for r in body(out).iter(W + "r"):
            pr = r.find(W + "rPr")
            if pr is None:
                continue
            fonts = pr.find(W + "rFonts")
            assert fonts.get(W + "cs") == fonts.get(W + "ascii")

    def test_every_run_sets_the_complex_script_size(self, exported):
        out, _stats, _layout = exported
        for r in body(out).iter(W + "r"):
            pr = r.find(W + "rPr")
            if pr is None:
                continue
            assert pr.find(W + "szCs").get(W + "val") == \
                pr.find(W + "sz").get(W + "val")

    def test_every_run_declares_thai_as_the_bidi_language(self, exported):
        out, _stats, _layout = exported
        for r in body(out).iter(W + "r"):
            pr = r.find(W + "rPr")
            if pr is None:
                continue
            assert pr.find(W + "lang").get(W + "bidi") == "th-TH"

    def test_bold_is_applied_to_the_complex_script_too(self, exported):
        """<w:b/> alone leaves Thai looking regular - it needs <w:bCs/>."""
        out, _stats, _layout = exported
        for r in body(out).iter(W + "r"):
            pr = r.find(W + "rPr")
            if pr is None:
                continue
            assert (pr.find(W + "b") is None) == (pr.find(W + "bCs") is None)

    def test_document_defaults_are_a_thai_font(self, exported):
        with zipfile.ZipFile(exported[0]) as z:
            styles = ET.fromstring(z.read("word/styles.xml"))
        rpr = styles.find(".//" + W + "rPrDefault/" + W + "rPr")
        assert rpr.find(W + "rFonts").get(W + "cs")
        assert rpr.find(W + "szCs").get(W + "val") == rpr.find(W + "sz").get(W + "val")


class TestPackage:
    def test_every_part_is_well_formed_xml(self, exported):
        out, _stats, _layout = exported
        with zipfile.ZipFile(out) as z:
            for name in z.namelist():
                if name.endswith((".xml", ".rels")):
                    ET.fromstring(z.read(name))     # raises if malformed

    def test_the_required_parts_are_present(self, exported):
        out, _stats, _layout = exported
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml",
                "word/_rels/document.xml.rels", "word/styles.xml"} <= names

    def test_every_image_reference_resolves(self, exported):
        """A dangling r:embed makes Word declare the file unreadable."""
        out, _stats, _layout = exported
        with zipfile.ZipFile(out) as z:
            rels = ET.fromstring(z.read("word/_rels/document.xml.rels"))
            parts = set(z.namelist())
            known = {r.get("Id") for r in rels}
            for r in rels:
                target = r.get("Target")
                if target.startswith("media/"):
                    assert "word/" + target in parts
        R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        for blip in body(out).iter(
                "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
            assert blip.get(R + "embed") in known

    def test_one_section_per_page_at_the_pdf_page_size(self, exported, doc):
        out, _stats, _layout = exported
        sects = list(body(out).iter(W + "sectPr"))
        assert len(sects) == doc.page_count
        for pno, sect in enumerate(sects):
            size = sect.find(W + "pgSz")
            rect = doc.doc[pno].rect
            assert int(size.get(W + "w")) == pytest.approx(dx._tw(rect.width), abs=2)
            assert int(size.get(W + "h")) == pytest.approx(dx._tw(rect.height), abs=2)


class TestModes:
    def test_layout_mode_pins_every_line(self, doc, tmp_path):
        out = str(tmp_path / "l.docx")
        doc.export_docx(out, layout=True)
        root = body(out)
        lines = sum(len(b["lines"]) for pno in range(doc.page_count)
                    for b in dx.page_blocks(doc.doc[pno]))
        assert len(list(root.iter(W + "framePr"))) == lines

    def test_flow_mode_pins_nothing(self, doc, tmp_path):
        out = str(tmp_path / "f.docx")
        doc.export_docx(out, layout=False)
        assert not list(body(out).iter(W + "framePr"))

    def test_ruled_tables_become_word_tables(self, doc, tmp_path):
        out = str(tmp_path / "t.docx")
        doc.export_docx(out, layout=False, tables=True)
        root = body(out)
        if not list(root.iter(W + "tbl")):
            pytest.skip("the sample has no ruled tables")
        for tbl in root.iter(W + "tbl"):
            cols = len(list(tbl.find(W + "tblGrid")))
            for tr in tbl.iter(W + "tr"):
                span = sum(int(tc.find(W + "tcPr").find(W + "gridSpan")
                               .get(W + "val"))
                           if tc.find(W + "tcPr").find(W + "gridSpan") is not None
                           else 1
                           for tc in tr.findall(W + "tc"))
                # a row that does not fill the grid makes Word rebuild the table
                assert span == cols

    def test_tables_can_be_turned_off(self, doc, tmp_path):
        out = str(tmp_path / "nt.docx")
        doc.export_docx(out, layout=False, tables=False)
        assert not list(body(out).iter(W + "tbl"))


class TestPageSelection:
    def test_only_the_requested_pages_are_written(self, doc, tmp_path):
        out = str(tmp_path / "s.docx")
        stats = doc.export_docx(out, pages=[2, 0])
        assert stats["pages"] == 2
        assert len(list(body(out).iter(W + "sectPr"))) == 2

    def test_the_requested_order_is_kept(self, doc, tmp_path):
        out = str(tmp_path / "s.docx")
        doc.export_docx(out, pages=[2, 0])
        text = "".join(all_text(body(out)).split())
        first = "".join("".join(sp["text"] for ln in b["lines"] for sp in ln["spans"])
                        for b in dx.page_blocks(doc.doc[2])).split()
        assert text.startswith("".join(dx.repair_text(" ".join(first)).split())[:20])

    def test_an_empty_selection_is_refused(self, doc, tmp_path):
        with pytest.raises(ValueError):
            doc.export_docx(str(tmp_path / "e.docx"), pages=[])


class TestCancel:
    def test_the_progress_callback_can_stop_the_export(self, doc, tmp_path):
        out = str(tmp_path / "c.docx")
        with pytest.raises(dx.ExportCancelled):
            doc.export_docx(out, progress=lambda done, total: done < 2)
        assert not os.path.exists(out)      # nothing half-written is left behind

    def test_progress_counts_every_page(self, doc, tmp_path):
        seen = []
        doc.export_docx(str(tmp_path / "p.docx"),
                        progress=lambda done, total: seen.append((done, total)))
        assert seen == [(i + 1, doc.page_count) for i in range(doc.page_count)]


class TestUndecodablePages:
    def test_a_page_with_no_text_becomes_a_picture(self, tmp_path):
        """A scan has nothing to extract, so the page has to go in as an image
        or the user gets a blank document."""
        src = fitz.open()
        page = src.new_page(width=595, height=842)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 850))
        pix.set_rect(pix.irect, (240, 240, 230))
        page.insert_image(page.rect, pixmap=pix)
        path = str(tmp_path / "scan.pdf")
        src.save(path)
        src.close()

        d = PdfDocument()
        assert d.open(path) is None
        out = str(tmp_path / "scan.docx")
        stats = d.export_docx(out)
        d.close()
        assert stats["images"] == 1
        assert list(body(out).iter(WP + "anchor"))

    def test_garbled_pages_are_reported_not_written(self, doc, tmp_path,
                                                    monkeypatch):
        """When the text cannot be decoded we ship a picture instead and tell
        the caller which pages, so the UI can say so."""
        monkeypatch.setattr(dx, "_GARBLED_LIMIT", -1.0)
        out = str(tmp_path / "g.docx")
        stats = doc.export_docx(out)
        assert stats["picture_pages"] == list(range(1, doc.page_count + 1))
        assert not all_text(body(out)).strip()
