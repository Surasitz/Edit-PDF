# -*- coding: utf-8 -*-
"""The Document-menu handlers, driven through the real MainWindow with the
dialogs answered by the test (Qt runs offscreen, settings go to a temp INI
file - never to the user's real settings)."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox  # noqa: E402

from wnyeditpdf import doc_tools, engine  # noqa: E402
from wnyeditpdf import window as window_mod  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "sample_thai.pdf")

needs_engine = pytest.mark.skipif(not engine.available(),
                                  reason="pdfcraft-cli not built (run build.bat)")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(window_mod, "QSettings",
                        lambda *a: QSettings(ini, QSettings.Format.IniFormat))
    # every stray message box answers itself
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    w = window_mod.MainWindow()
    w._open_path(FIXTURE)
    assert w.pdf.is_open()
    yield w
    w.pdf.modified = False
    w.close()


def accept(monkeypatch, cls, **values):
    """Make dialog ``cls`` accept at once and return ``values`` from its getters."""
    monkeypatch.setattr(cls, "exec", lambda self: QDialog.DialogCode.Accepted)
    for getter, value in values.items():
        monkeypatch.setattr(cls, getter, lambda self, v=value: v)


def test_new_menus_are_wired(win):
    menus = {a.text(): a.menu() for a in win.menuBar().actions()}
    doc = [a.text() for a in menus["เอกสาร(&D)"].actions() if a.text()]
    assert len(doc) == 8
    sign = [a.text() for a in menus["ลายเซ็น(&S)"].actions() if a.text()]
    assert any("ลงนามดิจิทัล" in t for t in sign)


def test_properties_edit_is_undoable(win, monkeypatch):
    accept(monkeypatch, doc_tools.PropertiesDialog,
           values={"title": "รายงาน", "author": "ทดสอบ", "subject": "", "keywords": ""})
    old = win.pdf.metadata()
    win.doc_properties()
    assert win.pdf.metadata()["title"] == "รายงาน"
    win.undo()
    assert win.pdf.metadata() == old


def test_bookmarks_dialog_round_trips_the_tree(win, app):
    toc = win.pdf.toc()
    dlg = doc_tools.BookmarksDialog(win, win.T, toc, win.pdf.page_count, 1)
    assert dlg.toc() == toc
    dlg.tree.setCurrentItem(dlg.tree.topLevelItem(0))
    dlg._indent()                    # first item has nothing above it: no-op
    assert dlg.toc() == toc


@needs_engine
def test_sanitize_keeps_thai_text_and_undoes(win, monkeypatch):
    before = [p.get_text() for p in win.pdf.doc]
    accept(monkeypatch, doc_tools.SanitizeDialog, selected=list(engine.HIDDEN_CATEGORIES))
    win.sanitize_document()
    assert [p.get_text() for p in win.pdf.doc] == before
    assert win.pdf.toc() == []                    # bookmarks were chosen, so removed
    win.undo()
    assert win.pdf.toc()


@needs_engine
def test_sign_digital_end_to_end(win, monkeypatch, tmp_path):
    p12 = str(tmp_path / "me.p12")
    engine.create_id(p12, "สุรสิทธิ์ ทดสอบ", "secret123")
    out = str(tmp_path / "signed.pdf")
    accept(monkeypatch, doc_tools.SignDialog, values=dict(
        id=p12, password="secret123", cert=None, reason="อนุมัติ", location="สระแก้ว",
        contact="", visible=True, page=1, position="bottom-right", certify=None))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    win.sign_digital()

    assert os.path.abspath(win.pdf.path) == os.path.abspath(out)   # now editing the signed file
    assert win.pdf.is_signed()
    assert "ลงนามดิจิทัลโดย: สุรสิทธิ์ ทดสอบ" in win.pdf.doc[0].get_text()
    with open(out, "rb") as f:
        s = engine.signatures(f.read())["signatures"][0]
    assert s["status"] == "unknown" and s["modification"] == "none"

    # saving now would break the signature: answering "No" must not write
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    mtime = os.path.getmtime(out)
    win.save_pdf()
    assert os.path.getmtime(out) == mtime


@needs_engine
def test_split_writes_parts(win, monkeypatch, tmp_path):
    parts = tmp_path / "parts"
    accept(monkeypatch, doc_tools.SplitDialog, values={"out_dir": str(parts), "every": 4})
    win.split_document()
    assert sorted(os.listdir(parts)) == ["sample_thai-part1.pdf", "sample_thai-part2.pdf"]


@needs_engine
def test_detect_fields_then_undo(win, monkeypatch):
    f = fitz.open()
    p = f.new_page()
    p.insert_text((72, 100), "ชื่อ: ________________________", fontsize=12,
                  fontfile=win.pdf.default_thai_font, fontname="th")
    win.pdf.apply_bytes(f.tobytes())
    win.detect_form_fields()
    assert win.pdf.has_form()
    win.undo()
    assert not win.pdf.has_form()


def test_command_palette_finds_commands_in_both_languages(win):
    from wnyeditpdf.i18n import EN
    pal = doc_tools.CommandPalette(win, win.T, win.menuBar(), EN)
    pal._filter("ดิจิทัล")                     # sign, validate, create an ID
    assert pal.list.count() >= 3
    pal._filter("pdf/a")                       # English words match the Thai menu
    labels = [pal.list.item(i).text() for i in range(pal.list.count())]
    assert any("PDF/A" in t for t in labels)
    assert all("(&" not in t for t in labels)
    pal.close()


def test_welcome_screen_shows_until_a_file_is_open(app, tmp_path, monkeypatch):
    ini = str(tmp_path / "s.ini")
    monkeypatch.setattr(window_mod, "QSettings",
                        lambda *a: QSettings(ini, QSettings.Format.IniFormat))
    w = window_mod.MainWindow()
    w.render_page()
    assert w.stack.currentWidget() is w.welcome
    w.toggle_language()                        # rebuilds in English without errors
    assert w.stack.currentWidget() is w.welcome
    w._open_path(FIXTURE)
    assert w.stack.currentWidget() is w.scroll
    w.close()


@needs_engine
def test_crop_current_page_then_undo(win, monkeypatch):
    before = win.pdf.doc[0].rect
    accept(monkeypatch, doc_tools.CropDialog, values=([20, 20, 20, 20], False))
    win.crop_pages()
    assert win.pdf.doc[0].rect.width == pytest.approx(before.width - 40, abs=0.5)
    win.undo()
    assert win.pdf.doc[0].rect == before


def test_protect_document_writes_a_restricted_copy(win, monkeypatch, tmp_path):
    out = str(tmp_path / "locked.pdf")
    accept(monkeypatch, doc_tools.ProtectDialog,
           values=("", "perm-pw", fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    win.protect_document()
    with fitz.open(out) as d:
        assert not d.permissions & fitz.PDF_PERM_COPY
    assert win.pdf.path == FIXTURE                # still editing the original
