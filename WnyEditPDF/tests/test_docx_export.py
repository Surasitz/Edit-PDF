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
import re
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


def all_parts(path):
    """document.xml plus every header and footer, parsed."""
    with zipfile.ZipFile(path) as z:
        return [ET.fromstring(z.read(n)) for n in z.namelist()
                if n == "word/document.xml"
                or re.match(r"word/(header|footer)\d+\.xml$", n)]


def pdf_text(d):
    """Every character the PDF holds, after the repair pass."""
    return "".join(
        dx.repair_text(sp["text"])
        for pno in range(d.page_count)
        for blk in dx.page_blocks(d.doc[pno])
        for ln in blk["lines"] for sp in ln["spans"])


def body_pdf_text(d):
    """pdf_text without the running headers/footers, which the flowing export
    moves out of the body into Word's header and footer."""
    pages = [(dx.page_blocks(d.doc[p]), d.doc[p].rect.height)
             for p in range(d.page_count)]
    furniture = dx.find_furniture(pages)
    return "".join(
        dx.repair_text(sp["text"])
        for pi, (blocks, _h) in enumerate(pages)
        for bi, blk in enumerate(blocks)
        for li, ln in enumerate(blk["lines"]) if (bi, li) not in furniture[pi]
        for sp in ln["spans"])


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
        ("BCDEFG+Sarabun-Bold", "Sarabun"),
        # a weight with a family of its own keeps it: that is the name the
        # shipped font declares, and the name Word looks an embedded font up by
        ("BCDEFG+Sarabun-SemiBold", "Sarabun SemiBold"),
        ("THSarabunIT9", "TH SarabunIT๙"),
    ])
    def test_postscript_names_become_word_families(self, ps_name, family):
        assert dx.font_family(ps_name) == family

    def test_a_weight_family_is_not_bolded_again(self):
        fam, bold, _i, _s = dx.span_style({"font": "Sarabun-SemiBold", "flags": 16})
        assert (fam, bold) == ("Sarabun SemiBold", False)

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
        out, _stats, layout = exported
        want = pdf_text(doc) if layout else body_pdf_text(doc)
        got = squash(all_text(body(out)))
        if layout:
            assert got == squash(want)
            return
        # a table carried over a page break is joined into one Word table and
        # the header the PDF printed again on the new page becomes a repeating
        # header row instead - the only text the flowing export may drop
        headers = squash("".join(all_text(tr) for tr in body(out).iter(W + "tr")
                                 if tr.find(W + "trPr/" + W + "tblHeader") is not None))
        missing = squash(want) - got
        assert not (got - squash(want))
        assert all(n <= headers[c] for c, n in missing.items()), missing

    def test_font_size_and_weight_survive(self, exported, doc):
        out, _stats, _layout = exported
        # a family whose shipped namesake has other metrics is written as the
        # font that does match (see TestFontEmbedding)
        renames, _reject = dx.fit_fonts(doc.doc, list(range(doc.page_count)))
        want = collections.Counter()
        for pno in range(doc.page_count):
            for blk in dx.page_blocks(doc.doc[pno]):
                for ln in blk["lines"]:
                    for sp in ln["spans"]:
                        if sp["text"].strip():
                            fam, bold, _i, _s = dx.span_style(sp)
                            want[(renames.get(fam, fam),
                                  dx._halfpt(sp["size"]), bold)] += 1
        got = collections.Counter()
        for r in (r for root in all_parts(out) for r in root.iter(W + "r")):
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

    def test_layout_mode_has_one_section_per_page(self, doc, tmp_path):
        out = str(tmp_path / "l.docx")
        doc.export_docx(out, layout=True)
        sects = list(body(out).iter(W + "sectPr"))
        assert len(sects) == doc.page_count
        for pno, sect in enumerate(sects):
            size = sect.find(W + "pgSz")
            rect = doc.doc[pno].rect
            assert int(size.get(W + "w")) == pytest.approx(dx._tw(rect.width), abs=2)
            assert int(size.get(W + "h")) == pytest.approx(dx._tw(rect.height), abs=2)


    def test_flow_mode_is_one_section_that_flows(self, doc, tmp_path):
        """Pages of one size become a single section: Word paginates the
        text itself instead of forcing a break where the PDF had one."""
        out = str(tmp_path / "f.docx")
        doc.export_docx(out, layout=False)
        sects = list(body(out).iter(W + "sectPr"))
        assert len(sects) == 1
        size = sects[0].find(W + "pgSz")
        assert int(size.get(W + "w")) == pytest.approx(dx._tw(doc.doc[0].rect.width), abs=2)

    def test_every_part_is_declared(self, exported):
        """A part missing from [Content_Types].xml makes Word refuse the file."""
        out, _stats, _layout = exported
        with zipfile.ZipFile(out) as z:
            types = z.read("[Content_Types].xml").decode("utf-8")
            for name in z.namelist():
                ext = name.rsplit(".", 1)[-1]
                assert ('PartName="/%s"' % name in types
                        or 'Extension="%s"' % ext in types), name


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


# ------------------------------------------------------ flowing paragraphs
THSN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "fonts", "THSarabunNew.ttf")


def _filled(words, width, size=16, prefix=""):
    """Repeat `words` until the text is about `width` points wide - a line
    that ran out of room, the way a wrapped paragraph line does."""
    font = fitz.Font(fontfile=THSN)
    text = prefix
    i = 0
    while font.text_length(text + words[i % len(words)], fontsize=size) < width:
        text += words[i % len(words)]
        i += 1
    return text


@pytest.fixture
def letter(tmp_path):
    """Two A4 pages laid out like a typical Thai document: page numbers in
    the header, a heading, a first-line-indented paragraph, a bullet with a
    hanging continuation, and a paragraph broken by the page break."""
    words = ["การทดสอบ", "เอกสาร", "ภาษาไทย", "ให้ถูกต้อง", "ครบถ้วน"]
    lines = [
        (0, 295, 40, "1"),
        (0, 72, 100, "หัวข้อเรื่อง"),
        (0, 108, 130, _filled(words, 410)),
        (0, 72, 153, _filled(words[1:] + words[:1], 446)),
        (0, 72, 176, "ปิดท้ายย่อหน้าแรก"),
        # TH Sarabun New has no "●"; a dash is a bullet just the same
        (0, 84, 216, _filled(words[2:] + words[:2], 420, prefix="- ")),
        (0, 102, 239, "บรรทัดต่อของข้อนี้"),
        (0, 72, 279, _filled(words[3:] + words[:3], 446,
                             prefix="ย่อหน้าที่ข้ามหน้า")),
        (0, 72, 302, _filled(words[4:] + words[:4], 446)),
        (1, 295, 40, "2"),
        (1, 72, 100, "ต่อจากหน้าก่อน"),
    ]
    src = fitz.open()
    for _ in range(2):
        src.new_page(width=595, height=842)
    for pno, x, y, text in lines:
        src[pno].insert_text((x, y), text, fontsize=16, fontname="thsn",
                             fontfile=THSN)
    path = str(tmp_path / "letter.pdf")
    src.save(path)
    src.close()
    d = PdfDocument()
    assert d.open(path) is None
    out = str(tmp_path / "letter.docx")
    stats = d.export_docx(out, layout=False)
    d.close()
    return out, stats


def paragraphs(path):
    """[(text, w:p element)] of the body."""
    return [("".join(t.text or "" for t in p.iter(W + "t")), p)
            for p in body(path).iter(W + "p")]


def para_with(path, needle):
    hits = [(t, p) for t, p in paragraphs(path) if needle in t]
    assert len(hits) == 1, [t for t, _p in hits]
    return hits[0]


class TestFlowParagraphs:
    def test_a_heading_stays_its_own_paragraph(self, letter):
        text, _p = para_with(letter[0], "หัวข้อเรื่อง")
        assert text == "หัวข้อเรื่อง"

    def test_wrapped_lines_join_into_one_paragraph(self, letter):
        """The point of the flowing mode: one paragraph per paragraph, not
        one per PDF line."""
        text, p = para_with(letter[0], "ปิดท้ายย่อหน้าแรก")
        assert text.startswith("การทดสอบ") and text.endswith("ปิดท้ายย่อหน้าแรก")
        # wrapped Thai is joined without inventing a space
        assert " " not in text
        ind = p.find(W + "pPr/" + W + "ind")
        assert int(ind.get(W + "firstLine")) == pytest.approx(dx._tw(36), abs=20)

    def test_a_bullet_gets_a_hanging_indent_and_a_tab(self, letter):
        text, p = para_with(letter[0], "บรรทัดต่อของข้อนี้")
        assert text.startswith("-") and " " not in text[:2]
        ind = p.find(W + "pPr/" + W + "ind")
        assert int(ind.get(W + "hanging")) == pytest.approx(dx._tw(18), abs=20)
        assert p.find(".//" + W + "tab") is not None

    def test_a_paragraph_continues_across_the_page_break(self, letter):
        text, _p = para_with(letter[0], "ต่อจากหน้าก่อน")
        assert text.startswith("ย่อหน้าที่ข้ามหน้า")

    def test_page_numbers_move_to_a_header_field(self, letter):
        out, _stats = letter
        texts = [t for t, _p in paragraphs(out)]
        assert "1" not in texts and "2" not in texts
        with zipfile.ZipFile(out) as z:
            hdr = z.read("word/header1.xml").decode("utf-8")
        assert 'w:instr=" PAGE "' in hdr
        ref = body(out).find(".//" + W + "headerReference")
        assert ref is not None

    def test_the_document_font_is_embedded(self, letter):
        assert letter[1]["fonts"] == ["TH Sarabun New"]


class TestRepeatedFurniture:
    def test_only_page_numbers_and_repeats_count(self):
        def blk(y, text):
            return {"bbox": fitz.Rect(72, y, 300, y + 20),
                    "lines": [{"bbox": fitz.Rect(72, y, 300, y + 20),
                               "spans": [{"text": text}]}]}
        pages = [([blk(20, "บริษัท ตัวอย่าง จำกัด"), blk(30, "หน้า %d" % n),
                   blk(400, "เนื้อหา"), blk(810, "ลับเฉพาะ %d" % n)], 842)
                 for n in (1, 2, 3)]
        pages.append(([blk(20, "หัวเรื่องเฉพาะหน้านี้")], 842))
        got = dx.find_furniture(pages)
        assert got[0] == {(0, 0), (1, 0), (3, 0)}
        assert got[3] == set()


# ----------------------------------------------------------- font embedding
class TestFontEmbedding:
    def test_obfuscation_uses_the_reversed_guid(self):
        key = "{00010203-0405-0607-0809-0A0B0C0D0E0F}"
        out = dx.obfuscate_font(bytes(40), key)
        assert out[:16] == bytes(range(15, -1, -1))
        assert out[16:32] == out[:16] and out[32:] == bytes(8)
        assert dx.obfuscate_font(out, key) == bytes(40)       # XOR undoes itself

    def test_google_docs_sarabun_is_written_as_th_sarabun_new(self, doc):
        """Google Docs' "Sarabun" has TH Sarabun New's widths; the Sarabun we
        ship is the wider 2018 redesign. Going by name would make every line
        of the sample overflow."""
        renames, reject = dx.fit_fonts(doc.doc, list(range(doc.page_count)))
        assert renames.get("Sarabun") == "TH Sarabun New"
        assert "Sarabun" in reject

    def test_embedded_fonts_round_trip(self, exported):
        out, stats, _layout = exported
        assert stats["fonts"]
        R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        with zipfile.ZipFile(out) as z:
            assert b"embedTrueTypeFonts" in z.read("word/settings.xml")
            table = ET.fromstring(z.read("word/fontTable.xml"))
            rels = {r.get("Id"): r.get("Target") for r in
                    ET.fromstring(z.read("word/_rels/fontTable.xml.rels"))}
            for font in table.iter(W + "font"):
                for emb in font:
                    if not emb.tag.startswith(W + "embed"):
                        continue
                    data = z.read("word/" + rels[emb.get(R + "id")])
                    plain = dx.obfuscate_font(data, emb.get(W + "fontKey"))
                    family, _sub, _fs = dx.ttf_info(plain)
                    # Word finds an embedded font by this exact name
                    assert family == font.get(W + "name")


# ------------------------------------------- Word-side rendering of Thai text
class TestThaiLineBreaking:
    def test_thai_runs_are_marked_complex_script(self):
        """<w:cs/> is what switches Word's Thai word breaker on; without it
        Word cuts "เชิงกลยุทธ์" as "เชิงก|ลยุทธ์"."""
        xml = dx.run_xml("ระบบ Smart Hospital ของโรงพยาบาล", "TH SarabunPSK", 16)
        runs = re.findall(r"<w:r>.*?</w:r>", xml)
        texts = [("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", r)), "<w:cs/>" in r)
                 for r in runs]
        assert texts == [("ระบบ", True), (" Smart Hospital ", False),
                         ("ของโรงพยาบาล", True)]

    def test_a_space_before_sara_am_is_dropped(self):
        assert dx.repair_text("ค ำน ำ") == "คำนำ"

    def test_a_real_space_is_kept(self):
        assert dx.repair_text("ทั้งนี้ สอดคล้อง") == "ทั้งนี้ สอดคล้อง"


class TestPageNumbers:
    @pytest.mark.parametrize("token, label", [
        ("12", ("decimal", 12)), ("๑๒", ("thaiNumbers", 12)),
        ("ก", ("thaiLetters", 1)), ("ค", ("thaiLetters", 3)),
        ("iv", ("lowerRoman", 4)), ("XII", ("upperRoman", 12)),
    ])
    def test_printed_numbers_are_understood(self, token, label):
        assert dx.page_label(token) == label

    def test_thai_letter_page_numbers_are_furniture(self):
        assert dx._RE_PAGE_NO.match("ข ")
        assert not dx._RE_PAGE_NO.match("ขอ")


class TestContents:
    def test_a_leader_becomes_a_right_tab(self):
        line = {"bbox": fitz.Rect(72, 100, 520, 118), "_left": 72, "_right": 520,
                "spans": [{"text": "บทที่ 1 บริบท .................... 12", "size": 16,
                           "font": "THSarabunPSK", "flags": 0, "color": 0}]}
        xml = dx._flow_para([[line]], 72, 520, 0, None, "TH SarabunPSK", 16)
        assert '<w:tab w:val="right" w:leader="dot"' in xml
        assert "...." not in xml and "<w:tab/>" in xml

    def test_an_entry_ends_at_its_page_number(self):
        """A contents line runs to the margin, which would otherwise read as a
        wrapped line and glue the next entry on ("85 Roadmap")."""
        def line(y, text):
            return {"bbox": fitz.Rect(72, y, 520, y + 18), "_left": 72,
                    "_right": 520, "spans": [{"text": text, "size": 16}]}
        para = {"rows": [[line(100, "ข้อหนึ่ง ........................ 85")]]}
        assert not dx._continues(para, line(121, "Roadmap แผนปฏิบัติการ"), False)


class TestTables:
    def test_cells_inside_a_cell_are_dropped(self):
        """Word shades a cell line by line; PyMuPDF reads each shaded line as a
        cell of its own inside the real one. The real cell must win."""
        class T:
            bbox = (0, 0, 200, 100)
            cells = [(0, 0, 100, 100), (100, 0, 200, 100),
                     (5, 10, 95, 30), (5, 30, 95, 50)]       # shading artefacts
        parts = dx.table_parts(T, [], [], lambda s: None, "TH SarabunPSK", 16)
        assert parts["xs"] == [0, 100, 200] and len(parts["rows"]) == 1

    def test_a_tall_cell_is_merged_vertically(self):
        class T:
            bbox = (0, 0, 200, 100)
            cells = [(0, 0, 100, 100), (100, 0, 200, 50), (100, 50, 200, 100)]
        parts = dx.table_parts(T, [], [], lambda s: None, "TH SarabunPSK", 16)
        assert 'w:vMerge w:val="restart"' in parts["rows"][0][1]
        assert "<w:vMerge/>" in parts["rows"][1][1]

    def test_a_shaded_cell_keeps_its_colour(self):
        class T:
            bbox = (0, 0, 400, 100)
            cells = [(0, 0, 100, 100), (100, 0, 400, 100)]
        fills = [(fitz.Rect(0, 0, 100, 100), "FFFFCC")]
        parts = dx.table_parts(T, [], fills, lambda s: None, "TH SarabunPSK", 16)
        assert 'w:fill="FFFFCC"' in parts["rows"][0][1]

    def test_a_repeated_header_becomes_a_repeating_row(self):
        a = {"xs": [0, 100], "widths": [100], "rows": [("", "", "หัว"), ("", "", "1")]}
        b = {"xs": [0, 100], "widths": [100], "rows": [("", "", "หัว"), ("", "", "2")]}
        assert dx.table_continues(a, b)
        joined = dx.join_table(a, b)
        assert [r[2] for r in joined["rows"]] == ["หัว", "1", "2"]
        assert "<w:tblHeader/>" in dx.table_xml(joined)


class TestDesignedPages:
    def test_a_cover_is_pinned_and_a_text_page_is_not(self, tmp_path, doc):
        src = fitz.open()
        page = src.new_page(width=595, height=842)
        page.draw_rect(fitz.Rect(0, 300, 595, 842), color=None, fill=(0.1, 0.3, 0.6))
        page.insert_text((72, 200), "2025", fontsize=60)
        assert dx.is_designed(page, dx.page_blocks(page))
        assert not dx.is_designed(doc.doc[1], dx.page_blocks(doc.doc[1]))

    def test_an_oversized_page_is_shrunk_to_fit_word(self):
        assert dx._fit_scale(1057, 1687) == pytest.approx(1584 / 1687)
        assert dx._fit_scale(595, 842) == 1.0


class TestGraphics:
    def _chart_page(self):
        src = fitz.open()
        page = src.new_page(width=595, height=842)
        page.insert_text((72, 100), "ย่อหน้าก่อนกราฟ " * 6, fontsize=16,
                         fontname="thsn", fontfile=THSN)
        for i in range(8):                      # a little bar chart
            page.draw_rect(fitz.Rect(100 + i * 40, 400 - i * 20, 125 + i * 40, 500),
                           color=(0, 0, 0), fill=(0.2, 0.4, 0.8))
        page.draw_line((90, 500), (430, 500))
        return src, page

    def test_line_art_is_found_as_a_region(self):
        src, page = self._chart_page()
        regions = dx.graphic_regions(page)
        assert len(regions) == 1 and regions[0].contains(fitz.Rect(100, 260, 425, 500))

    def test_a_single_rule_is_not_a_region(self):
        src = fitz.open()
        page = src.new_page(width=595, height=842)
        page.draw_line((72, 100), (520, 100))
        assert dx.graphic_regions(page) == []

    def test_a_chart_survives_the_flowing_export_as_a_picture(self, tmp_path):
        src, _page = self._chart_page()
        path = str(tmp_path / "chart.pdf")
        src.save(path)
        d = PdfDocument()
        assert d.open(path) is None
        out = str(tmp_path / "chart.docx")
        stats = d.export_docx(out, layout=False)
        d.close()
        assert stats["images"] == 1
        assert list(body(out).iter(WP + "inline"))
