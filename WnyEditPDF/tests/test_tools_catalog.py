# -*- coding: utf-8 -*-
"""The tool catalogue, the Acrobat/PdfCraft-style frame built from it, and the
tools that came over from the PdfCraft catalogue (headers and footers, Bates
numbers, page labels, markup, shapes, redaction, form fields, ...)."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtGui import QKeySequence  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox  # noqa: E402

from wnyeditpdf import catalog, doc_tools  # noqa: E402
from wnyeditpdf import window as window_mod  # noqa: E402
from wnyeditpdf.config import MODE_COMMENT, MODE_FORM, MODE_HIGHLIGHT, resource_path  # noqa: E402
from wnyeditpdf.i18n import EN  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "sample_thai.pdf")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(window_mod, "QSettings",
                        lambda *a: QSettings(ini, QSettings.Format.IniFormat))
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    w = window_mod.MainWindow()
    w.resize(1400, 900)
    w.show()
    w._open_path(FIXTURE)
    yield w
    w.pdf.modified = False
    w.close()


def accept(monkeypatch, cls, **values):
    monkeypatch.setattr(cls, "exec", lambda self: QDialog.DialogCode.Accepted)
    for getter, value in values.items():
        monkeypatch.setattr(cls, getter, lambda self, v=value: v)


def items():
    for g in catalog.GROUPS:
        for _title, its in g.sections:
            yield g, its


# ======================================================================
#  The catalogue
# ======================================================================
def test_every_tool_runs_a_real_method():
    missing = {i.method for _g, its in items() for i in its
               if not hasattr(window_mod.MainWindow, i.method)}
    assert not missing


def test_every_icon_is_bundled():
    gone = [n for n in catalog.icons_used()
            if not os.path.isfile(resource_path(os.path.join("wnyeditpdf", "assets", "icons", n + ".svg")))]
    assert not gone


def test_every_label_has_an_english_translation():
    labels = {catalog.TABS[i][1] for i in range(len(catalog.TABS))}
    for g in catalog.GROUPS:
        labels |= {g.label, g.desc}
        for title, its in g.sections:
            labels.add(title)
            labels |= {i.label for i in its}
    assert sorted(label for label in labels if label not in EN) == []


# ======================================================================
#  The frame
# ======================================================================
def test_tabs_drive_the_tool_panel_and_read_mode(win, app):
    assert win.tool_panel.isVisible() and win.rail.isVisible() and win.thumbs.isVisible()
    win.set_tab("edit")
    assert win.tool_panel.view == ("groups", ["edit", "organize"], "แก้ไข")
    win.set_tab("read")
    assert not win.tool_panel.isVisible() and not win.rail.isVisible() and not win.thumbs.isVisible()
    win.set_tab("all")
    assert win.tool_panel.isVisible() and win.tool_panel.view[0] == "home"
    win.hide_tool_panel()
    assert not win.tool_panel.isVisible()
    win.set_tab("sign")                       # a tab brings the panel back
    assert win.tool_panel.isVisible()


def test_long_tool_lists_scroll_instead_of_squashing(win, app):
    win.set_tab("edit")
    app.processEvents()
    body = win.tool_panel.scroll.widget()
    assert body.height() >= body.layout().minimumSize().height()
    assert win.tool_panel.scroll.verticalScrollBar().maximum() > 0


def test_hidden_menu_bar_keeps_its_shortcuts(win):
    assert not win.menuBar().isVisible()
    keys = {a.shortcut().toString() for a in win.actions()}
    for k in ("Ctrl+O", "Ctrl+S", "Ctrl+P", "Ctrl+K", "Ctrl+Z", "Ctrl+D"):
        assert QKeySequence(k).toString() in keys
    n = len(win.actions())
    win.toggle_language()                     # rebuilt, not duplicated
    win.toggle_language()
    assert len(win.actions()) == n


def test_run_tool_asks_for_a_file_first(app, tmp_path, monkeypatch):
    ini = str(tmp_path / "s.ini")
    monkeypatch.setattr(window_mod, "QSettings",
                        lambda *a: QSettings(ini, QSettings.Format.IniFormat))
    w = window_mod.MainWindow()
    asked = []
    monkeypatch.setattr(w, "open_pdf", lambda: asked.append(True))
    w.run_tool(catalog.BY_ID["organize"].sections[0][1][0])     # rotate: needs a document
    assert asked == [True]
    w.close()


# ======================================================================
#  Tools from the PdfCraft catalogue
# ======================================================================
def test_header_footer_with_bates_numbers(win, monkeypatch):
    accept(monkeypatch, doc_tools.HeaderFooterDialog,
           values=({"tc": "รายงานประจำปี", "br": "{bates}"}, 12, 28, "1-2", ("สสจ-", 7, 4)))
    win.header_footer_ui()
    assert "รายงานประจำปี" in win.pdf.doc[0].get_text()
    assert "สสจ-0007" in win.pdf.doc[0].get_text()
    assert "สสจ-0008" in win.pdf.doc[1].get_text()
    assert "สสจ-" not in win.pdf.doc[2].get_text()
    win.undo()
    assert "สสจ-0007" not in win.pdf.doc[0].get_text()


def test_page_labels(win, monkeypatch):
    accept(monkeypatch, doc_tools.PageLabelsDialog, values=(0, "r", "", 1))
    win.page_labels_ui()
    accept(monkeypatch, doc_tools.PageLabelsDialog, values=(2, "D", "", 1))
    win.page_labels_ui()
    assert [win.pdf.doc[i].get_label() for i in range(4)] == ["i", "ii", "1", "2"]


def test_duplicate_page_and_background(win, monkeypatch):
    n = win.pdf.page_count
    win.duplicate_page()
    assert win.pdf.page_count == n + 1 and win.page_index == 1
    # this Google Docs file paints an opaque white page first: an underlay
    # would never show, the Multiply tint must
    def darkest(pix):
        return min(sum(pix.pixel(x, y)) for x in range(0, pix.width, 2) for y in range(0, pix.height, 2))

    text = fitz.Rect(60, 300, 560, 330)
    before = darkest(win.pdf.doc[0].get_pixmap(dpi=72, clip=text))
    win.pdf.add_background((1, 0.85, 0.85), 1.0, [0])
    corner = win.pdf.doc[0].get_pixmap(dpi=36).pixel(3, 3)
    assert corner[0] > 240 and corner[1] < 230            # pink paper
    after = darkest(win.pdf.doc[0].get_pixmap(dpi=72, clip=text))
    assert after <= before + 30                            # black text stays black


def test_markup_kinds_and_shapes(win):
    win.set_markup("underline")
    assert win.mode == MODE_HIGHLIGHT
    win.add_highlight(fitz.Rect(60, 470, 560, 520))
    win._set_comment_kind("oval")
    assert win.mode == MODE_COMMENT
    win.place_comment_drag((100, 100), (220, 160))
    kinds = [t for p, t, *_ in win.pdf.all_comments() if p == 0]
    assert "Underline" in kinds and "Circle" in kinds


def test_find_and_redact_removes_the_text(win, monkeypatch):
    accept(monkeypatch, doc_tools.FindRedactDialog, values=("Showcase", (0, 0, 0)))
    win.find_and_redact()
    assert "Showcase" not in "".join(p.get_text() for p in win.pdf.doc)
    win.undo()
    assert "Showcase" in win.pdf.doc[0].get_text()


def test_redact_pages(win, monkeypatch):
    monkeypatch.setattr(win, "_ask_pages", lambda *a, **k: [6])
    win.redact_pages_ui()
    assert win.pdf.doc[6].get_text().strip() == ""
    assert win.pdf.page_count == 7


def test_add_form_fields_by_drag(win, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", True)))
    for kind in ("text", "checkbox", "signature"):
        win.set_form_kind(kind)
        assert win.mode == MODE_FORM
        win.add_form_field_ui(fitz.Rect(72, 600, 260, 622))
    types = sorted(w.field_type_string for w in win.pdf.doc[0].widgets())
    assert types == ["CheckBox", "Signature", "Text"]


def test_blank_and_clipboard_documents(win, monkeypatch, app):
    from PyQt6.QtGui import QImage, QColor
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(win, "confirm_discard", lambda: True)
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (a[3][1], True)))
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (3, True)))
    win.create_blank()
    assert win.pdf.page_count == 3 and win.pdf.path is None
    assert win.pdf.doc[0].rect.width > win.pdf.doc[0].rect.height          # A4 landscape
    img = QImage(192, 96, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    QApplication.clipboard().setImage(img)
    win.create_from_clipboard()
    assert win.pdf.page_count == 1
    assert round(win.pdf.doc[0].rect.width) == 144                           # 192 px at 96 dpi


def test_export_html_keeps_thai(win, tmp_path, monkeypatch):
    out = str(tmp_path / "page.html")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    win.export_html()
    html = open(out, encoding="utf-8").read()
    assert 'lang="th"' in html and "หลักการ" in html and "แก้ว" in html
