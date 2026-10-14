# -*- coding: utf-8 -*-
"""The PdfCraft engine bridge (wnyeditpdf/engine.py) and the document-side
helpers the Document menu relies on.

Engine tests run the real pdfcraft-cli and are skipped when it has not been
built (``build.bat`` builds it). Every engine result is opened back in
PyMuPDF: a job that "succeeds" but hands the editor a file it cannot read is
a failure.
"""
import os

import fitz
import pytest

from wnyeditpdf import engine
from wnyeditpdf.document import PdfDocument

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "sample_thai.pdf")

needs_engine = pytest.mark.skipif(not engine.available(),
                                  reason="pdfcraft-cli not built (run build.bat)")


@pytest.fixture(scope="module")
def data():
    with open(FIXTURE, "rb") as f:
        return f.read()


def texts(pdf_bytes):
    with fitz.open("pdf", pdf_bytes) as d:
        return [p.get_text() for p in d]


# ======================================================================
#  Bridge plumbing
# ======================================================================
def test_decode_stream_reads_pretty_printed_values_in_order():
    assert engine._decode_stream('{\n  "a": 1\n}\n[1,\n 2]\n"x"\n') == [{"a": 1}, [1, 2], "x"]
    assert engine._decode_stream("  \n") == []


def test_missing_engine_is_reported_not_crashed(monkeypatch):
    monkeypatch.setattr(engine, "cli_path", lambda: None)
    assert not engine.available()
    with pytest.raises(engine.EngineMissing):
        engine.info(b"%PDF-1.4")


@needs_engine
def test_engine_errors_carry_the_engine_message(tmp_path):
    with pytest.raises(engine.EngineError) as e:
        engine.run([("doc_open", {"path": str(tmp_path / "does-not-exist.pdf")})])
    assert "step" not in str(e.value)          # the "step N (tool):" prefix is stripped
    assert str(e.value)


# ======================================================================
#  Inspection / sanitize / flatten
# ======================================================================
@needs_engine
def test_info_reports_pages_fonts_and_security(data):
    info = engine.info(data, "sample_thai.pdf")
    assert len(info["pages"]) == 7
    assert info["security"]["protected"] is False
    assert any(f["embedded"] for f in info["fonts"])


@needs_engine
def test_thai_marks_are_not_hidden_text(data):
    """Regression: the engine used to count every zero-width glyph - Thai
    tone marks and above/below vowels - as hidden text, and Sanitize then
    deleted about one character in eight of every Thai document."""
    scan = {c["category"]: c["count"] for c in engine.hidden_info(data)["categories"]}
    assert scan["hidden-text"] == 0
    assert texts(engine.remove_hidden(data)) == texts(data)


@needs_engine
def test_remove_hidden_strips_only_the_chosen_categories(data):
    out = engine.remove_hidden(data, ["metadata", "comments"])
    after = {c["category"]: c["count"] for c in engine.hidden_info(out)["categories"]}
    assert after["comments"] == 0
    assert after["bookmarks"] > 0                 # not chosen -> kept
    assert texts(out) == texts(data)


@needs_engine
def test_flatten_keeps_the_text(data):
    out = engine.flatten(data)
    with fitz.open("pdf", out) as d:
        assert d.page_count == 7
        assert not any(list(p.annots()) for p in d)
    assert texts(out) == texts(data)


# ======================================================================
#  Standards
# ======================================================================
@needs_engine
def test_pdfa_convert_makes_a_compliant_file(data):
    assert engine.pdfa_verify(data)["compliant"] is False
    out, rep = engine.pdfa_convert(data)
    assert rep["compliant"]
    assert engine.pdfa_verify(out)["compliant"]
    assert texts(out) == texts(data)


@needs_engine
def test_accessibility_report_is_written(data, tmp_path):
    report = tmp_path / "a11y.html"
    res = engine.accessibility_report(data, str(report))
    assert report.stat().st_size > 0
    assert res["passed"] + res["failed"] + res["manual"] > 0


# ======================================================================
#  Compare
# ======================================================================
@needs_engine
def test_compare_finds_an_added_line_and_a_removed_page(data, tmp_path):
    old = tmp_path / "old.pdf"
    old.write_bytes(data)
    d = fitz.open("pdf", data)
    d[0].insert_text((72, 300), "NEW LINE ADDED", fontsize=14)
    d.delete_page(5)
    new = d.tobytes()
    res = engine.compare(new, str(old))
    assert res["inserted"] >= 1 and res["deleted"] >= 1
    assert any("NEW LINE ADDED" in (c["new"]["text"] or "") for c in res["changes"])

    report = tmp_path / "report.pdf"
    engine.compare_report(new, str(old), str(report))
    assert fitz.open(str(report)).page_count >= 1

    marked = engine.compare_mark(new, str(old))
    with fitz.open("pdf", marked) as m:
        assert sum(len(list(p.annots())) for p in m) >= 2


@needs_engine
def test_identical_files_compare_identical(data, tmp_path):
    old = tmp_path / "same.pdf"
    old.write_bytes(data)
    assert engine.compare(data, str(old))["identical"]


# ======================================================================
#  Forms / split / combine / images
# ======================================================================
@needs_engine
def test_detect_fields_turns_blanks_into_fields():
    f = fitz.open()
    p = f.new_page()
    p.insert_text((72, 100), "Name: ________________________", fontsize=12)
    p.draw_rect(fitz.Rect(72, 170, 84, 182))
    p.insert_text((90, 180), "Agree", fontsize=12)
    out, rep = engine.detect_fields(f.tobytes())
    assert {x["kind"] for x in rep["fields"]} >= {"text", "checkbox"}
    with fitz.open("pdf", out) as d:
        assert len(list(d[0].widgets())) == len(rep["fields"])


@needs_engine
def test_split_names_parts_after_a_thai_file_name(data, tmp_path):
    res = engine.split(data, str(tmp_path), "รายงานประจำปี.pdf", every=3)
    names = sorted(os.listdir(tmp_path))
    assert names == ["รายงานประจำปี-part1.pdf", "รายงานประจำปี-part2.pdf",
                     "รายงานประจำปี-part3.pdf"]
    assert [f["first_page"] for f in res["files"]] == [1, 4, 7]


@needs_engine
def test_create_multiple_joins_pdfs_and_images(data, tmp_path):
    img = tmp_path / "pic.png"
    fitz.open("pdf", data)[0].get_pixmap(dpi=30).save(str(img))
    out = tmp_path / "combined.pdf"
    engine.create_multiple([FIXTURE, str(img)], str(out))
    with fitz.open(str(out)) as d:
        assert d.page_count == 8
        assert [t[1] for t in d.get_toc() if t[0] == 1] == ["sample_thai", "pic"]


@needs_engine
def test_export_all_images(data, tmp_path):
    res = engine.export_all_images(data, str(tmp_path), "sample_thai.pdf")
    assert res["count"] == len([f for f in os.listdir(tmp_path)])


# ======================================================================
#  Digital signatures
# ======================================================================
@pytest.fixture(scope="module")
def digital_id(tmp_path_factory):
    if not engine.available():
        pytest.skip("pdfcraft-cli not built")
    path = str(tmp_path_factory.mktemp("id") / "me.p12")
    engine.create_id(path, "สุรสิทธิ์ ทดสอบ", "secret123", organization="รพ.ทดสอบ", country="TH")
    return path


@needs_engine
def test_id_info_checks_the_password(digital_id):
    assert engine.id_info(digital_id, "secret123")["name"] == "สุรสิทธิ์ ทดสอบ"
    with pytest.raises(engine.EngineError):
        engine.id_info(digital_id, "wrong")


@needs_engine
def test_sign_and_validate(data, digital_id, tmp_path):
    out = tmp_path / "signed.pdf"
    res = engine.sign(data, str(out), digital_id, "secret123", reason="อนุมัติ",
                      location="สระแก้ว", name="sample_thai.pdf")
    assert res["signature"]["signer"] == "สุรสิทธิ์ ทดสอบ"
    signed = out.read_bytes()
    assert texts(signed) == texts(data)

    sigs = engine.signatures(signed)
    assert sigs["count"] == 1
    s = sigs["signatures"][0]
    # intact, but a self-signed ID is not a trusted authority
    assert s["status"] == "unknown" and s["modification"] == "none"
    assert s["reason"] == "อนุมัติ"

    # the PdfDocument helper sees it too (it drives the "saving breaks the
    # signature" warning)
    d = PdfDocument()
    assert d.open(str(out)) is None
    assert d.is_signed()
    d.close()


@needs_engine
def test_tampering_invalidates_the_signature(data, digital_id, tmp_path):
    out = tmp_path / "signed.pdf"
    engine.sign(data, str(out), digital_id, "secret123")
    raw = bytearray(out.read_bytes())
    at = raw.index(b"stream", 200) + 40          # inside the first signed stream
    raw[at] ^= 0xFF
    s = engine.signatures(bytes(raw))["signatures"][0]
    assert s["status"] == "invalid"


@needs_engine
def test_wrong_id_password_fails_cleanly(data, digital_id, tmp_path):
    with pytest.raises(engine.EngineError) as e:
        engine.sign(data, str(tmp_path / "x.pdf"), digital_id, "nope")
    assert "password" in str(e.value)
    assert not (tmp_path / "x.pdf").exists()


# ======================================================================
#  PdfDocument helpers (no engine needed)
# ======================================================================
def test_apply_bytes_is_one_undo_step(doc):
    before = doc.page_count
    d = fitz.open("pdf", doc.doc.tobytes())
    d.delete_page(0)
    doc.apply_bytes(d.tobytes())
    assert doc.page_count == before - 1 and doc.modified
    assert doc.undo()
    assert doc.page_count == before


def test_metadata_round_trip_and_undo(doc):
    old = doc.metadata()
    doc.set_metadata({"title": "รายงานผลการดำเนินงาน", "author": "กลุ่มงานสุขภาพดิจิทัล"})
    assert doc.metadata()["title"] == "รายงานผลการดำเนินงาน"
    assert doc.metadata()["author"] == "กลุ่มงานสุขภาพดิจิทัล"
    doc.undo()
    assert doc.metadata() == old


def test_toc_round_trip_clamps_pages(doc):
    toc = [[1, "บทที่ 1", 1], [2, "หัวข้อย่อย", 2], [1, "ภาคผนวก", 999]]
    doc.set_toc(toc)
    assert doc.toc() == [[1, "บทที่ 1", 1], [2, "หัวข้อย่อย", 2], [1, "ภาคผนวก", doc.page_count]]


def test_unsigned_file_is_not_signed(doc):
    assert not doc.is_signed()


# ======================================================================
#  Thai in form fields, crop, form data, links, protection
# ======================================================================
def _form_pdf():
    f = fitz.open()
    p = f.new_page()
    w = fitz.Widget()
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_name = "name"
    w.rect = fitz.Rect(72, 72, 300, 98)
    p.add_widget(w)
    return f.tobytes()


def _ink(page, rect):
    """How many dark pixels a region holds - 0 means nothing was drawn."""
    pix = page.get_pixmap(dpi=72, clip=rect, colorspace=fitz.csGRAY)
    return sum(1 for b in pix.samples if b < 128)


def test_thai_form_value_is_drawn_with_a_thai_font(tmp_path):
    """Regression: base-14 field appearances have no Thai glyphs, so a Thai
    value used to come out blank (PyMuPDF) or as '?????' (engine)."""
    from conftest import bundled_fonts
    path = tmp_path / "form.pdf"
    path.write_bytes(_form_pdf())
    d = PdfDocument()
    assert d.open(str(path)) is None
    d.bundled_fonts = bundled_fonts()
    d.default_thai_font = d.bundled_fonts["Sarabun-Regular"]
    d.set_form_field(0, d.form_fields(0)[0], "สมชาย ใจดี")
    assert _ink(d.doc[0], fitz.Rect(72, 72, 300, 98)) > 20
    out = tmp_path / "filled.pdf"
    d.save(str(out))
    d.close()
    with fitz.open(str(out)) as r:
        w = next(r[0].widgets())
        assert w.field_value == "สมชาย ใจดี"
        assert "WnyTh" in r.xref_get_key(w.xref, "DA")[1]
        assert "WnyTh" in r.xref_object(r.pdf_catalog())  # the font is in /AcroForm /DR
        assert _ink(r[0], fitz.Rect(72, 72, 300, 98)) > 20


@needs_engine
def test_imported_thai_values_are_redrawn(tmp_path):
    from conftest import bundled_fonts
    xfdf = tmp_path / "vals.xfdf"
    xfdf.write_text('<?xml version="1.0" encoding="UTF-8"?><xfdf xmlns="http://ns.adobe.com/xfdf/">'
                    '<fields><field name="name"><value>นางสาวทดสอบ</value></field></fields></xfdf>',
                    encoding="utf-8")
    out, rep = engine.import_data(_form_pdf(), str(xfdf))
    assert rep["filled_fields"] == 1
    d = PdfDocument()
    d.bundled_fonts = bundled_fonts()
    d.default_thai_font = d.bundled_fonts["Sarabun-Regular"]
    d.doc = fitz.open("pdf", out)
    d.refresh_field_appearances()
    assert next(d.doc[0].widgets()).field_value == "นางสาวทดสอบ"
    assert _ink(d.doc[0], fitz.Rect(72, 72, 300, 98)) > 20


@needs_engine
def test_form_reset_and_export(tmp_path):
    d = fitz.open("pdf", _form_pdf())
    page = d[0]                                  # widgets die with their page proxy
    w = next(page.widgets())
    w.field_value = "abc"
    w.update()
    data = d.tobytes()
    assert [x.field_value for x in fitz.open("pdf", engine.form_reset(data))[0].widgets()] == [""]
    out = tmp_path / "data.xfdf"
    engine.export_data(data, str(out), name="แบบฟอร์ม.pdf")
    text = out.read_text(encoding="utf-8")
    assert "<value>abc</value>" in text and "แบบฟอร์ม.pdf" in text


@needs_engine
def test_crop_one_page(data):
    out = engine.crop(data, [36, 36, 36, 36], pages=[1])
    with fitz.open("pdf", out) as d:
        assert (round(d[0].rect.width), round(d[0].rect.height)) == (540, 720)
        assert (round(d[1].rect.width), round(d[1].rect.height)) == (612, 792)


@needs_engine
def test_links_from_urls(data):
    assert engine.links_from_urls(data)[1]["urls"] == []      # nothing to link: not an error
    f = fitz.open()
    f.new_page().insert_text((72, 100), "See https://www.moph.go.th for details", fontsize=12)
    out, rep = engine.links_from_urls(f.tobytes())
    assert rep["urls"] == ["https://www.moph.go.th"]
    assert fitz.open("pdf", out)[0].get_links()[0]["uri"] == "https://www.moph.go.th"


def test_protect_with_permissions(doc, tmp_path):
    out = str(tmp_path / "locked.pdf")
    doc.save_encrypted(out, "", "owner-secret",
                       permissions=fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT)
    with fitz.open(out) as d:
        assert not d.needs_pass                       # opens without a password...
        assert d.is_encrypted or d.metadata.get("encryption")
        assert not d.permissions & fitz.PDF_PERM_COPY   # ...but copying is denied
        assert d.permissions & fitz.PDF_PERM_PRINT
    out2 = str(tmp_path / "open_pw.pdf")
    doc.save_encrypted(out2, "user-pw")
    with fitz.open(out2) as d:
        assert d.needs_pass and d.authenticate("user-pw")
