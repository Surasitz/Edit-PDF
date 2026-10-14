# -*- coding: utf-8 -*-
"""Whole-document tools: digital signatures with a certificate, PDF/A,
comparing two versions, the accessibility checker, removing hidden
information, flattening, automatic form-field detection, splitting and
combining files, exporting embedded images - plus document properties and
bookmarks.

The heavy lifting is done by the bundled PdfCraft engine (see engine.py);
properties and bookmarks are plain PyMuPDF edits. ``DocToolsMixin`` is mixed
into MainWindow, so every handler here can use ``self.pdf``, ``self.T``,
``self.status`` and friends exactly like the code in window.py.
"""

import html
import os
import re
import tempfile
import threading
import time

import fitz

from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressDialog, QPushButton, QRadioButton, QSizePolicy, QSpinBox,
    QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QAbstractItemView, QHeaderView,
)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import Qt, QUrl, QEventLoop, QEvent, QSize

from . import engine
from .catalog import BLUE, GREEN, PURPLE, RED, TEAL
from .config import APP_NAME
from .icons import icon, pixmap

_GREY = "color: #6b7280;"


def run_job(parent, text, fn, *args, **kw):
    """Run ``fn`` in a worker thread behind a busy dialog and return its
    result (or re-raise its error). The engine is a separate process, so the
    thread only waits on it - the window keeps painting meanwhile."""
    box = {}

    def work():
        try:
            box["result"] = fn(*args, **kw)
        except BaseException as e:          # handed back to the caller below
            box["error"] = e

    th = threading.Thread(target=work, daemon=True)
    th.start()
    bar = QProgressDialog(text, None, 0, 0, parent)
    bar.setWindowTitle(APP_NAME)
    bar.setWindowModality(Qt.WindowModality.WindowModal)
    bar.setCancelButton(None)
    bar.setMinimumDuration(400)
    while th.is_alive():
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        th.join(0.03)
    bar.close()
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _esc(s, limit=None):
    s = "" if s is None else str(s)
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return html.escape(s)


def _size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024


def _reveal(path):
    """Open the folder holding ``path`` in Explorer / Finder."""
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


# ======================================================================
#  Dialogs
# ======================================================================
class ReportDialog(QDialog):
    """A read-only HTML report with optional action buttons
    (``buttons``: [(label, callback(dialog))])."""

    def __init__(self, parent, title, body_html, buttons=(), close_text="ปิด"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setHtml(body_html)
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        for label, cb in buttons:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=cb: f(self))
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton(close_text)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)


class PropertiesDialog(QDialog):
    """Title / author / subject / keywords (editable) and what the engine can
    tell about the file: PDF version, fonts and whether they are embedded,
    security, tags, attachments, repairs."""

    LABELS = (("title", "ชื่อเรื่อง"), ("author", "ผู้เขียน"),
              ("subject", "หัวเรื่อง"), ("keywords", "คำสำคัญ"))

    def __init__(self, parent, T, meta, info):
        super().__init__(parent)
        self.setWindowTitle(T("คุณสมบัติเอกสาร"))
        self.resize(640, 600)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edits = {}
        for key, label in self.LABELS:
            e = QLineEdit(meta.get(key, ""))
            form.addRow(T(label) + ":", e)
            self.edits[key] = e
        lay.addLayout(form)

        view = QTextBrowser()
        view.setHtml(self._details(T, info))
        lay.addWidget(view, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText(T("บันทึกค่า"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def _details(T, info):
        if not info:
            return "<p style='color:#6b7280'>%s</p>" % _esc(
                T("ไม่มีรายละเอียดเพิ่มเติม (ไม่พบเอนจิน PdfCraft)"))
        rows = []

        def row(k, v):
            rows.append("<tr><td style='color:#6b7280;padding-right:14px'>%s</td>"
                        "<td>%s</td></tr>" % (_esc(T(k)), v))

        pages = info.get("pages") or []
        row("เวอร์ชัน PDF", _esc(info.get("pdf_version")))
        row("จำนวนหน้า", _esc(len(pages)))
        if pages:
            p = pages[0]
            row("ขนาดหน้าแรก", _esc("%.0f × %.0f pt (%.0f × %.0f mm)" % (
                p["width"], p["height"], p["width"] / 72 * 25.4,
                p["height"] / 72 * 25.4)))
        row("ขนาดไฟล์", _esc(_size(info.get("file_size"))))
        row("สร้างด้วยโปรแกรม", _esc(info.get("creator") or "-"))
        row("ผู้ผลิต PDF", _esc(info.get("producer") or "-"))
        sec = info.get("security") or {}
        if sec.get("protected"):
            parts = [str(sec.get(k)) for k in ("method", "revision") if sec.get(k)]
            perms = sec.get("permissions")
            if isinstance(perms, dict):
                denied = [k for k, v in perms.items() if v is False]
                if denied:
                    parts.append(T("ห้าม: ") + ", ".join(denied))
            row("ความปลอดภัย", _esc(T("มีรหัสผ่าน") + (" — " + "; ".join(parts) if parts else "")))
        else:
            row("ความปลอดภัย", _esc(T("ไม่มีรหัสผ่าน")))
        row("มีแท็กโครงสร้าง (Tagged)", _esc(T("มี") if info.get("tagged") else T("ไม่มี")))
        row("ช่องฟอร์ม", _esc(len(info.get("fields") or [])))
        row("ไฟล์แนบ", _esc(len(info.get("attachments") or [])))
        row("เลเยอร์", _esc(len(info.get("layers") or [])))
        row("JavaScript", _esc(T("มี") if info.get("has_javascript") else T("ไม่มี")))
        out = ["<table>%s</table>" % "".join(rows)]

        fonts = info.get("fonts") or []
        if fonts:
            out.append("<h4>%s (%d)</h4><table>" % (_esc(T("ฟอนต์ในไฟล์")), len(fonts)))
            for f in fonts:
                if f.get("embedded"):
                    state = T("ฝังมาบางส่วน") if f.get("subset") else T("ฝังมาทั้งชุด")
                    color = "#15803d"
                else:
                    state, color = T("ไม่ได้ฝัง — เครื่องอื่นอาจแสดงผลเพี้ยน"), "#b91c1c"
                out.append("<tr><td style='padding-right:14px'>%s</td>"
                           "<td style='color:%s'>%s</td></tr>"
                           % (_esc(f.get("name")), color, _esc(state)))
            out.append("</table>")
        notes = (info.get("repairs") or []) + (info.get("warnings") or [])
        if notes:
            out.append("<h4>%s</h4><ul>%s</ul>" % (
                _esc(T("สิ่งที่ซ่อมให้ตอนเปิดไฟล์")),
                "".join("<li>%s</li>" % _esc(n, 300) for n in notes[:40])))
        return "".join(out)

    def values(self):
        return {k: e.text().strip() for k, e in self.edits.items()}


class BookmarksDialog(QDialog):
    """Edit the bookmark tree: add (at the current page), rename, change the
    page, delete, move up/down and in/out a level. Result: a flat
    [[level, title, page], ...] list for PyMuPDF's set_toc."""

    def __init__(self, parent, T, toc, page_count, cur_page):
        super().__init__(parent)
        self._T = T
        self.page_count = page_count
        self.cur_page = cur_page
        self.setWindowTitle(T("บุ๊กมาร์ก (สารบัญด้านข้าง)"))
        self.resize(620, 520)
        lay = QVBoxLayout(self)
        hint = QLabel(T("ดับเบิลคลิกเพื่อแก้ชื่อหรือเลขหน้า • ลากวางเพื่อจัดลำดับ"))
        hint.setStyleSheet(_GREY)
        lay.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([T("ชื่อบุ๊กมาร์ก"), T("หน้า")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.itemChanged.connect(self._clean_page)
        lay.addWidget(self.tree, 1)
        self._fill(toc)

        row = QHBoxLayout()
        for label, slot in ((T("➕ เพิ่ม (หน้าปัจจุบัน)"), self._add),
                            (T("➕ เพิ่มย่อย"), lambda: self._add(child=True)),
                            (T("ลบ"), self._delete),
                            ("▲", lambda: self._move(-1)), ("▼", lambda: self._move(1)),
                            ("◀", self._outdent), ("▶", self._indent)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("ตกลง"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _item(self, title, page):
        it = QTreeWidgetItem([title, str(page)])
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable
                    | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        return it

    def _fill(self, toc):
        parents = {0: self.tree.invisibleRootItem()}
        for lvl, title, page in toc:
            # a malformed outline may skip levels: hang it on the nearest one
            parent = parents.get(lvl - 1) or parents[max(k for k in parents if k < lvl)]
            it = self._item(title, page)
            parent.addChild(it)
            parents[lvl] = it
            for k in [k for k in parents if k > lvl]:
                del parents[k]
        self.tree.expandAll()

    def _clean_page(self, item, col):
        if col != 1:
            return
        txt = item.text(1).strip()
        n = int(txt) if txt.isdigit() else self.cur_page
        n = max(1, min(n, self.page_count))
        if txt != str(n):
            item.setText(1, str(n))

    def _add(self, child=False):
        it = self._item(self._T("บุ๊กมาร์กใหม่"), self.cur_page)
        cur = self.tree.currentItem()
        if child and cur:
            cur.addChild(it)
            cur.setExpanded(True)
        elif cur and cur.parent():
            cur.parent().insertChild(cur.parent().indexOfChild(cur) + 1, it)
        elif cur:
            self.tree.insertTopLevelItem(self.tree.indexOfTopLevelItem(cur) + 1, it)
        else:
            self.tree.addTopLevelItem(it)
        self.tree.setCurrentItem(it)
        self.tree.editItem(it, 0)

    def _parent(self, it):
        return it.parent() or self.tree.invisibleRootItem()

    def _delete(self):
        it = self.tree.currentItem()
        if it:
            self._parent(it).removeChild(it)

    def _move(self, d):
        it = self.tree.currentItem()
        if not it:
            return
        p = self._parent(it)
        i = p.indexOfChild(it)
        j = i + d
        if 0 <= j < p.childCount():
            p.takeChild(i)
            p.insertChild(j, it)
            self.tree.setCurrentItem(it)

    def _indent(self):
        it = self.tree.currentItem()
        if not it:
            return
        p = self._parent(it)
        i = p.indexOfChild(it)
        if i == 0:
            return                       # nothing above to become the parent
        prev = p.child(i - 1)
        p.takeChild(i)
        prev.addChild(it)
        prev.setExpanded(True)
        self.tree.setCurrentItem(it)

    def _outdent(self):
        it = self.tree.currentItem()
        if not it or not it.parent():
            return
        p = it.parent()
        gp = self._parent(p)
        p.removeChild(it)
        gp.insertChild(gp.indexOfChild(p) + 1, it)
        self.tree.setCurrentItem(it)

    def toc(self):
        out = []

        def walk(item, lvl):
            for i in range(item.childCount()):
                c = item.child(i)
                page = int(c.text(1)) if c.text(1).isdigit() else 1
                # titles go back verbatim: tidying them would make pressing
                # OK on an untouched tree rewrite the document's bookmarks
                out.append([lvl, c.text(0), page])
                walk(c, lvl + 1)

        walk(self.tree.invisibleRootItem(), 1)
        return out


SANITIZE_LABELS = {
    "metadata": ("ข้อมูลเมตา (ผู้สร้าง โปรแกรม วันที่)", True),
    "attachments": ("ไฟล์แนบ", True),
    "comments": ("คอมเมนต์และมาร์กอัป", False),
    "form-fields": ("ช่องฟอร์ม (ค่าที่กรอกยังมองเห็นเหมือนเดิม)", False),
    "hidden-text": ("ข้อความที่มองไม่เห็น หรืออยู่นอกหน้ากระดาษ", True),
    "hidden-layers": ("เลเยอร์ที่ซ่อนไว้", True),
    "bookmarks": ("บุ๊กมาร์ก", False),
    "links-actions-scripts": ("ลิงก์ แอ็กชัน และ JavaScript", True),
    "private-data": ("ข้อมูลส่วนตัวของโปรแกรมที่สร้างไฟล์", True),
}


class SanitizeDialog(QDialog):
    """Pick which kinds of hidden information to strip before sending a file
    outside the organisation. Counts come from the engine's scan."""

    def __init__(self, parent, T, scan):
        super().__init__(parent)
        self.setWindowTitle(T("ลบข้อมูลแฝงในเอกสาร"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        head = QLabel(T("เลือกสิ่งที่จะลบออก ก่อนส่งไฟล์ออกนอกหน่วยงาน"))
        head.setStyleSheet("font-weight: 600; font-size: 14px;")
        lay.addWidget(head)
        self.checks = {}
        counts = {c["category"]: c["count"] for c in scan.get("categories", [])}
        for cat in engine.HIDDEN_CATEGORIES:
            label, default = SANITIZE_LABELS[cat]
            n = counts.get(cat, 0)
            cb = QCheckBox("%s  (%d)" % (T(label), n))
            cb.setChecked(default and n > 0)
            cb.setEnabled(n > 0)
            lay.addWidget(cb)
            self.checks[cat] = cb
        note = QLabel(T("ข้อความและรูปที่มองเห็นบนหน้าจะไม่ถูกแตะ • กด Ctrl+Z ย้อนกลับได้"))
        note.setStyleSheet(_GREY)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("ลบข้อมูลที่เลือก"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def selected(self):
        return [c for c, cb in self.checks.items() if cb.isChecked()]


class SplitDialog(QDialog):
    """How to cut the document into several files."""

    def __init__(self, parent, T, page_count, has_bookmarks, out_dir, stem):
        super().__init__(parent)
        self._T = T
        self.setWindowTitle(T("แยกไฟล์ PDF เป็นหลายไฟล์"))
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)

        r1 = QHBoxLayout()
        self.rb_every = QRadioButton(T("ทุก ๆ"))
        self.rb_every.setChecked(True)
        self.every = QSpinBox()
        self.every.setRange(1, max(1, page_count))
        self.every.setValue(1)
        r1.addWidget(self.rb_every)
        r1.addWidget(self.every)
        r1.addWidget(QLabel(T("หน้า ต่อ 1 ไฟล์")))
        r1.addStretch(1)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        self.rb_before = QRadioButton(T("เริ่มไฟล์ใหม่ที่หน้า:"))
        self.before = QLineEdit()
        self.before.setPlaceholderText(T("เช่น 4, 10"))
        r2.addWidget(self.rb_before)
        r2.addWidget(self.before, 1)
        lay.addLayout(r2)

        self.rb_bm = QRadioButton(T("ตามบุ๊กมาร์กระดับบนสุด (ตั้งชื่อไฟล์ตามบุ๊กมาร์ก)"))
        self.rb_bm.setEnabled(has_bookmarks)
        lay.addWidget(self.rb_bm)

        r3 = QHBoxLayout()
        self.rb_size = QRadioButton(T("ไฟล์ละไม่เกิน"))
        self.max_mb = QDoubleSpinBox()
        self.max_mb.setRange(0.1, 2000)
        self.max_mb.setValue(10)
        self.max_mb.setSuffix(" MB")
        r3.addWidget(self.rb_size)
        r3.addWidget(self.max_mb)
        r3.addWidget(QLabel(T("(เช่น ขนาดสูงสุดที่ส่งอีเมลได้)")))
        r3.addStretch(1)
        lay.addLayout(r3)

        lay.addSpacing(6)
        r4 = QHBoxLayout()
        r4.addWidget(QLabel(T("บันทึกไว้ที่:")))
        self.out = QLineEdit(out_dir)
        b = QPushButton(T("เลือก..."))
        b.clicked.connect(self._browse)
        r4.addWidget(self.out, 1)
        r4.addWidget(b)
        lay.addLayout(r4)
        note = QLabel(T("ได้ไฟล์ชื่อ %s-part1.pdf, %s-part2.pdf, … ไฟล์ที่เปิดอยู่ไม่ถูกแก้ไข")
                      % (stem, stem))
        note.setStyleSheet(_GREY)
        note.setWordWrap(True)
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("แยกไฟล์"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, self._T("เลือกโฟลเดอร์"), self.out.text())
        if d:
            self.out.setText(d)

    def values(self):
        """dict of engine.split keyword arguments (plus out_dir)."""
        v = {"out_dir": self.out.text().strip()}
        if self.rb_every.isChecked():
            v["every"] = self.every.value()
        elif self.rb_before.isChecked():
            v["before"] = [int(x) for x in self.before.text().replace(" ", "").split(",")
                           if x.isdigit()]
        elif self.rb_bm.isChecked():
            v["bookmarks"] = True
        else:
            v["max_mb"] = self.max_mb.value()
        return v


class CombineDialog(QDialog):
    """A work list of PDFs, images and text files to join, in order, into a
    new PDF with one bookmark per file."""

    FILTER = "PDF / รูปภาพ / ข้อความ (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.gif *.bmp *.jp2 *.txt)"

    def __init__(self, parent, T, files):
        super().__init__(parent)
        self._T = T
        self.setWindowTitle(T("รวมหลายไฟล์เป็น PDF ใหม่"))
        self.resize(620, 460)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        head = QLabel(T("ลากไฟล์มาวาง หรือกด 'เพิ่มไฟล์' แล้วจัดลำดับ — รองรับ PDF, "
                        "รูปภาพ (PNG/JPG/TIFF/GIF/BMP) และไฟล์ข้อความ .txt"))
        head.setWordWrap(True)
        lay.addWidget(head)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self.list, 1)
        for f in files:
            self._add_path(f)

        row = QHBoxLayout()
        for label, slot in ((T("➕ เพิ่มไฟล์..."), self._browse), (T("เอาออก"), self._remove),
                            ("▲", lambda: self._move(-1)), ("▼", lambda: self._move(1))):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        note = QLabel(T("แต่ละไฟล์จะมีบุ๊กมาร์กของตัวเอง บุ๊กมาร์กเดิมในไฟล์ถูกเก็บไว้ด้านใต้"))
        note.setStyleSheet(_GREY)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("รวมไฟล์..."))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add_path(self, path):
        if os.path.isfile(path):
            self.list.addItem(path)

    def _browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, self._T("เลือกไฟล์"), "",
                                                self._T(self.FILTER))
        for f in files:
            self._add_path(f)

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def _move(self, d):
        r = self.list.currentRow()
        j = r + d
        if r < 0 or not 0 <= j < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(j, it)
        self.list.setCurrentRow(j)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            self._add_path(u.toLocalFile())

    def _ok(self):
        if self.list.count() < 1:
            QMessageBox.information(self, APP_NAME, self._T("ยังไม่ได้เลือกไฟล์"))
            return
        self.accept()

    def files(self):
        return [self.list.item(i).text() for i in range(self.list.count())]


class CreateIdDialog(QDialog):
    """Create a self-signed digital ID (.p12) for signing inside the
    organisation. It proves the file was not changed after signing; proving
    WHO signed needs a certificate from a trusted authority."""

    def __init__(self, parent, T):
        super().__init__(parent)
        self._T = T
        self.setWindowTitle(T("สร้างใบรับรองดิจิทัลส่วนตัว"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.org = QLineEdit()
        self.unit = QLineEdit()
        self.email = QLineEdit()
        self.country = QLineEdit("TH")
        self.country.setMaxLength(2)
        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.years = QSpinBox()
        self.years.setRange(1, 50)
        self.years.setValue(5)
        for label, w in (("ชื่อ-นามสกุล *", self.name), ("หน่วยงาน", self.org),
                         ("กลุ่มงาน/แผนก", self.unit), ("อีเมล", self.email),
                         ("ประเทศ (2 ตัวอักษร)", self.country),
                         ("รหัสผ่าน (อย่างน้อย 6 ตัว) *", self.pw1),
                         ("ยืนยันรหัสผ่าน *", self.pw2), ("อายุใบรับรอง (ปี)", self.years)):
            form.addRow(T(label) + ":", w)
        lay.addLayout(form)
        note = QLabel(T("ใบรับรองที่สร้างเองยืนยันได้ว่าเอกสารไม่ถูกแก้ไขหลังลงนาม\n"
                        "แต่การยืนยันตัวบุคคลตามกฎหมายต้องใช้ใบรับรองจากผู้ให้บริการออกใบรับรอง (CA)\n"
                        "เก็บไฟล์ .p12 และรหัสผ่านไว้เป็นความลับ"))
        note.setStyleSheet(_GREY)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("สร้างและบันทึก..."))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        T = self._T
        if not self.name.text().strip():
            return QMessageBox.warning(self, APP_NAME, T("กรุณากรอกชื่อ"))
        if len(self.pw1.text()) < 6:
            return QMessageBox.warning(self, APP_NAME, T("รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร"))
        if self.pw1.text() != self.pw2.text():
            return QMessageBox.warning(self, APP_NAME, T("รหัสผ่านทั้งสองช่องไม่ตรงกัน"))
        self.accept()

    def values(self):
        return dict(name=self.name.text().strip(), organization=self.org.text().strip(),
                    unit=self.unit.text().strip(), email=self.email.text().strip(),
                    country=self.country.text().strip().upper(),
                    password=self.pw1.text(), years=self.years.value())


class SignDialog(QDialog):
    """Sign the document with a digital ID: a .p12/.pfx file or a
    certificate in the Windows store (e.g. one on a USB token)."""

    POSITIONS = (("bottom-right", "มุมล่างขวา"), ("bottom-left", "มุมล่างซ้าย"),
                 ("top-right", "มุมบนขวา"), ("top-left", "มุมบนซ้าย"))
    REASONS = ("อนุมัติ", "รับรองสำเนาถูกต้อง", "ผู้จัดทำเอกสาร", "ตรวจสอบแล้ว")

    def __init__(self, parent, T, win_ids, page_count, cur_page, settings):
        super().__init__(parent)
        self._T = T
        self.settings = settings
        self.win_ids = win_ids
        self.setWindowTitle(T("ลงนามดิจิทัลด้วยใบรับรอง"))
        self.setMinimumWidth(580)
        lay = QVBoxLayout(self)

        head = QLabel(T("ใบรับรองที่ใช้ลงนาม"))
        head.setStyleSheet("font-weight: 600;")
        lay.addWidget(head)
        self.rb_file = QRadioButton(T("ไฟล์ใบรับรอง (.p12 / .pfx)"))
        lay.addWidget(self.rb_file)
        r = QHBoxLayout()
        self.path = QLineEdit(settings.value("sign/id_path", "") or "")
        b = QPushButton(T("เลือก..."))
        b.clicked.connect(self._browse)
        r.addSpacing(22)
        r.addWidget(self.path, 1)
        r.addWidget(b)
        lay.addLayout(r)
        r = QHBoxLayout()
        r.addSpacing(22)
        r.addWidget(QLabel(T("รหัสผ่าน:")))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        r.addWidget(self.pw, 1)
        lay.addLayout(r)

        self.rb_win = QRadioButton(T("ใบรับรองใน Windows (รวมถึงบัตร/โทเคน USB)"))
        lay.addWidget(self.rb_win)
        r = QHBoxLayout()
        r.addSpacing(22)
        self.win = QComboBox()
        for i in win_ids:
            c = i.get("certificate") or {}
            self.win.addItem("%s — %s (%s %s)" % (
                c.get("name", "?"), c.get("issuer", ""), T("หมดอายุ"),
                (c.get("valid_to") or "")[:10]), i.get("id"))
        r.addWidget(self.win, 1)
        lay.addLayout(r)
        if not win_ids:
            self.rb_win.setEnabled(False)
            self.win.setEnabled(False)
        use_win = settings.value("sign/source", "file") == "windows" and win_ids
        (self.rb_win if use_win else self.rb_file).setChecked(True)
        if use_win:
            idx = self.win.findData(settings.value("sign/win_id", ""))
            if idx >= 0:
                self.win.setCurrentIndex(idx)

        r = QHBoxLayout()
        new = QPushButton(T("🪪 ยังไม่มีใบรับรอง? สร้างใหม่..."))
        new.setProperty("flat", True)
        new.clicked.connect(self._create)
        r.addWidget(new)
        r.addStretch(1)
        lay.addLayout(r)

        lay.addSpacing(6)
        form = QFormLayout()
        self.reason = QComboBox()
        self.reason.setEditable(True)
        self.reason.addItems([T(x) for x in self.REASONS])
        self.reason.setCurrentText(settings.value("sign/reason", T(self.REASONS[0])) or "")
        self.location = QLineEdit(settings.value("sign/location", "") or "")
        self.contact = QLineEdit(settings.value("sign/contact", "") or "")
        form.addRow(T("เหตุผล:"), self.reason)
        form.addRow(T("สถานที่:"), self.location)
        form.addRow(T("ติดต่อ (ไม่บังคับ):"), self.contact)
        lay.addLayout(form)

        self.chk_box = QCheckBox(T("แสดงกรอบ 'ลงนามดิจิทัลโดย…' บนหน้า"))
        self.chk_box.setChecked(settings.value("sign/visible", "true") == "true")
        lay.addWidget(self.chk_box)
        r = QHBoxLayout()
        r.addSpacing(22)
        r.addWidget(QLabel(T("หน้า")))
        self.page = QSpinBox()
        self.page.setRange(1, max(1, page_count))
        self.page.setValue(cur_page)
        r.addWidget(self.page)
        self.pos = QComboBox()
        for key, label in self.POSITIONS:
            self.pos.addItem(T(label), key)
        idx = self.pos.findData(settings.value("sign/position", "bottom-right"))
        self.pos.setCurrentIndex(max(0, idx))
        r.addWidget(self.pos)
        r.addStretch(1)
        lay.addLayout(r)
        self.chk_box.toggled.connect(self.page.setEnabled)
        self.chk_box.toggled.connect(self.pos.setEnabled)
        self.page.setEnabled(self.chk_box.isChecked())
        self.pos.setEnabled(self.chk_box.isChecked())

        self.chk_certify = QCheckBox(T("ล็อกเอกสาร: ห้ามแก้ไขใด ๆ หลังลงนาม (Certify)"))
        lay.addWidget(self.chk_certify)

        note = QLabel(T("การลงนามจะบันทึกเป็นไฟล์ใหม่ทันที หลังลงนามแล้วถ้าแก้ไขไฟล์ ลายเซ็นจะใช้ไม่ได้"))
        note.setStyleSheet(_GREY)
        note.setWordWrap(True)
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("ลงนามและบันทึก..."))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, self._T("เลือกไฟล์ใบรับรอง"),
                                           self.path.text(),
                                           "Digital ID (*.p12 *.pfx)")
        if p:
            self.path.setText(p)
            self.rb_file.setChecked(True)

    def _create(self):
        T = self._T
        dlg = CreateIdDialog(self, T)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        safe = "".join(ch for ch in v["name"] if ch not in '\\/:*?"<>|').strip() or "my-id"
        start = os.path.join(os.path.expanduser("~"), "Documents", safe + ".p12")
        path, _ = QFileDialog.getSaveFileName(self, T("บันทึกใบรับรองเป็น"), start,
                                              "Digital ID (*.p12)")
        if not path:
            return
        if not path.lower().endswith((".p12", ".pfx")):
            path += ".p12"
        try:
            run_job(self, T("กำลังสร้างใบรับรอง..."), engine.create_id, path, **v)
        except engine.EngineError as e:
            QMessageBox.critical(self, APP_NAME, T("สร้างใบรับรองไม่สำเร็จ:\n%s") % e)
            return
        self.path.setText(path)
        self.pw.setText(v["password"])
        self.rb_file.setChecked(True)
        QMessageBox.information(self, APP_NAME,
                                T("สร้างใบรับรองแล้ว:\n%s\n\nเก็บไฟล์นี้และรหัสผ่านไว้ให้ดี") % path)

    def _ok(self):
        T = self._T
        if self.rb_file.isChecked():
            if not os.path.isfile(self.path.text().strip()):
                return QMessageBox.warning(self, APP_NAME, T("กรุณาเลือกไฟล์ใบรับรอง (.p12 / .pfx)"))
        elif self.win.currentIndex() < 0:
            return QMessageBox.warning(self, APP_NAME, T("กรุณาเลือกใบรับรอง"))
        s = self.settings
        s.setValue("sign/source", "file" if self.rb_file.isChecked() else "windows")
        s.setValue("sign/id_path", self.path.text().strip())
        s.setValue("sign/win_id", self.win.currentData() or "")
        s.setValue("sign/reason", self.reason.currentText())
        s.setValue("sign/location", self.location.text())
        s.setValue("sign/contact", self.contact.text())
        s.setValue("sign/visible", "true" if self.chk_box.isChecked() else "false")
        s.setValue("sign/position", self.pos.currentData())
        self.accept()

    def values(self):
        if self.rb_file.isChecked():
            ref, pw, cert = self.path.text().strip(), self.pw.text(), None
        else:
            i = self.win.currentIndex()
            ref, pw = self.win.currentData(), ""
            cert = (self.win_ids[i].get("certificate") or {}) if i >= 0 else {}
        return dict(id=ref, password=pw, cert=cert,
                    reason=self.reason.currentText().strip(),
                    location=self.location.text().strip(),
                    contact=self.contact.text().strip(),
                    visible=self.chk_box.isChecked(), page=self.page.value(),
                    position=self.pos.currentData(),
                    certify="no_changes" if self.chk_certify.isChecked() else None)


class CropDialog(QDialog):
    """Trim the page margins (scanned pages with black borders, slides with
    wide white frames). Only the visible area changes; nothing is deleted, so
    'reset' is always possible."""

    def __init__(self, parent, T, cur_page, page_count):
        super().__init__(parent)
        self.setWindowTitle(T("ครอบตัดหน้า (Crop)"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(T("ตัดขอบกระดาษออก (มิลลิเมตร):")))
        form = QFormLayout()
        self.m = {}
        for key, label in (("top", "บน"), ("bottom", "ล่าง"), ("left", "ซ้าย"), ("right", "ขวา")):
            sb = QDoubleSpinBox()
            sb.setRange(0, 500)
            sb.setDecimals(1)
            sb.setSuffix(" mm")
            sb.setValue(10)
            form.addRow(T(label) + ":", sb)
            self.m[key] = sb
        lay.addLayout(form)
        self.rb_cur = QRadioButton(T("เฉพาะหน้านี้ (หน้า %d)") % cur_page)
        self.rb_cur.setChecked(True)
        self.rb_all = QRadioButton(T("ทุกหน้า (%d หน้า)") % page_count)
        lay.addWidget(self.rb_cur)
        lay.addWidget(self.rb_all)
        note = QLabel(T("ซ่อนเฉพาะส่วนขอบ เนื้อหาไม่ถูกลบ • กด Ctrl+Z ย้อนกลับได้"))
        note.setStyleSheet(_GREY)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("ครอบตัด"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        """([left, bottom, right, top] in points, all_pages)"""
        pt = {k: sb.value() / 25.4 * 72 for k, sb in self.m.items()}
        return [pt["left"], pt["bottom"], pt["right"], pt["top"]], self.rb_all.isChecked()


class ProtectDialog(QDialog):
    """Password to open the file, and/or restrictions (no printing, no
    copying, no editing) lifted only by a separate permissions password."""

    def __init__(self, parent, T):
        super().__init__(parent)
        self._T = T
        self.setWindowTitle(T("ตั้งรหัสผ่านและสิทธิ์การใช้งาน"))
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)

        self.chk_open = QCheckBox(T("ต้องใส่รหัสผ่านก่อนเปิดไฟล์"))
        self.chk_open.setChecked(True)
        lay.addWidget(self.chk_open)
        f1 = QFormLayout()
        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw1b = QLineEdit()
        self.pw1b.setEchoMode(QLineEdit.EchoMode.Password)
        f1.addRow(T("รหัสผ่านเปิดไฟล์:"), self.pw1)
        f1.addRow(T("ยืนยันรหัสผ่าน:"), self.pw1b)
        lay.addLayout(f1)
        self.chk_open.toggled.connect(self.pw1.setEnabled)
        self.chk_open.toggled.connect(self.pw1b.setEnabled)

        lay.addSpacing(8)
        self.chk_perm = QCheckBox(T("จำกัดสิทธิ์ (ห้ามพิมพ์ / ห้ามคัดลอก / ห้ามแก้ไข)"))
        lay.addWidget(self.chk_perm)
        f2 = QFormLayout()
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        f2.addRow(T("รหัสผ่านสิทธิ์ (ปลดล็อกข้อจำกัด):"), self.pw2)
        lay.addLayout(f2)
        self.allow = {}
        for key, label, default in (("print", "อนุญาตให้พิมพ์", True),
                                    ("copy", "อนุญาตให้คัดลอกข้อความและรูป", False),
                                    ("annotate", "อนุญาตให้กรอกฟอร์มและใส่คอมเมนต์", True),
                                    ("modify", "อนุญาตให้แก้ไขเนื้อหาและจัดหน้า", False)):
            cb = QCheckBox(T(label))
            cb.setChecked(default)
            cb.setStyleSheet("margin-left: 22px;")
            lay.addWidget(cb)
            self.allow[key] = cb
        widgets = [self.pw2, *self.allow.values()]
        for wdg in widgets:
            wdg.setEnabled(False)
            self.chk_perm.toggled.connect(wdg.setEnabled)

        note = QLabel(T("เข้ารหัสแบบ AES-256 • บันทึกเป็นไฟล์ใหม่ ไฟล์ที่เปิดอยู่ไม่ถูกล็อก"))
        note.setStyleSheet(_GREY)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("บันทึกไฟล์ที่ล็อก..."))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        T = self._T
        if not (self.chk_open.isChecked() or self.chk_perm.isChecked()):
            return QMessageBox.warning(self, APP_NAME, T("เลือกอย่างน้อยหนึ่งอย่าง"))
        if self.chk_open.isChecked():
            if not self.pw1.text():
                return QMessageBox.warning(self, APP_NAME, T("กรุณาตั้งรหัสผ่านเปิดไฟล์"))
            if self.pw1.text() != self.pw1b.text():
                return QMessageBox.warning(self, APP_NAME, T("รหัสผ่านทั้งสองช่องไม่ตรงกัน"))
        if self.chk_perm.isChecked():
            if not self.pw2.text():
                return QMessageBox.warning(self, APP_NAME, T("กรุณาตั้งรหัสผ่านสิทธิ์"))
            if self.chk_open.isChecked() and self.pw2.text() == self.pw1.text():
                return QMessageBox.warning(self, APP_NAME,
                                           T("รหัสผ่านสิทธิ์ต้องไม่ซ้ำกับรหัสผ่านเปิดไฟล์"))
        self.accept()

    def values(self):
        """(open_password or "", permissions_password or None, permission flags)"""
        user = self.pw1.text() if self.chk_open.isChecked() else ""
        if not self.chk_perm.isChecked():
            return user, None, -1                   # everything allowed
        perm = fitz.PDF_PERM_ACCESSIBILITY
        if self.allow["print"].isChecked():
            perm |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
        if self.allow["copy"].isChecked():
            perm |= fitz.PDF_PERM_COPY
        if self.allow["annotate"].isChecked():
            perm |= fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM
        if self.allow["modify"].isChecked():
            perm |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE
        return user, self.pw2.text(), perm


class HeaderFooterDialog(QDialog):
    """Header and footer lines (left / centre / right) with page numbers,
    the date and Bates numbers, written in the chosen Thai font."""

    def __init__(self, parent, T, page_count, bates=False):
        super().__init__(parent)
        self._T = T
        self.page_count = page_count
        self.setWindowTitle(T("หัวกระดาษ / ท้ายกระดาษ"))
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for c, label in enumerate(("ซ้าย", "กลาง", "ขวา")):
            h = QLabel(T(label))
            h.setStyleSheet("font-weight: 600;")
            grid.addWidget(h, 0, c + 1)
        self.edits = {}
        for r, (row, label) in enumerate((("t", "หัวกระดาษ"), ("b", "ท้ายกระดาษ"))):
            grid.addWidget(QLabel(T(label) + ":"), r + 1, 0)
            for c, col in enumerate("lcr"):
                e = QLineEdit()
                grid.addWidget(e, r + 1, c + 1)
                self.edits[row + col] = e
        lay.addLayout(grid)
        hint = QLabel(T("ใส่รหัสได้: {n} = เลขหน้า, {total} = จำนวนหน้า, {date} = วันที่, {bates} = เลข Bates"))
        hint.setStyleSheet(_GREY)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        form = QFormLayout()
        self.size = QSpinBox()
        self.size.setRange(6, 48)
        self.size.setValue(14)
        form.addRow(T("ขนาดตัวอักษร:"), self.size)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(3, 60)
        self.margin.setValue(10)
        self.margin.setSuffix(" mm")
        form.addRow(T("ระยะจากขอบกระดาษ:"), self.margin)
        self.pages = QLineEdit()
        self.pages.setPlaceholderText(T("เว้นว่าง = ทุกหน้า (%d หน้า) — หรือระบุ เช่น 2-10") % page_count)
        form.addRow(T("หน้า:"), self.pages)
        lay.addLayout(form)

        self.chk_bates = QCheckBox(T("ใส่เลข Bates (เลขเรียงต่อเนื่องสำหรับเอกสารคดี / เอกสารแนบ)"))
        lay.addWidget(self.chk_bates)
        brow = QHBoxLayout()
        brow.addSpacing(22)
        self.prefix = QLineEdit(T("เอกสาร-"))
        self.start = QSpinBox()
        self.start.setRange(0, 99999999)
        self.start.setValue(1)
        self.digits = QSpinBox()
        self.digits.setRange(1, 12)
        self.digits.setValue(6)
        for label, w in ((T("คำนำหน้า"), self.prefix), (T("เริ่มที่"), self.start),
                         (T("จำนวนหลัก"), self.digits)):
            brow.addWidget(QLabel(label))
            brow.addWidget(w)
        lay.addLayout(brow)
        for w in (self.prefix, self.start, self.digits):
            w.setEnabled(False)
            self.chk_bates.toggled.connect(w.setEnabled)
        if bates:
            self.chk_bates.setChecked(True)
            self.edits["br"].setText("{bates}")
        else:
            self.edits["bc"].setText(T("หน้า {n} จาก {total}"))

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("ใส่ลงในหน้า"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        if not any(e.text().strip() for e in self.edits.values()):
            return QMessageBox.warning(self, APP_NAME, self._T("ยังไม่ได้ใส่ข้อความ"))
        if self.chk_bates.isChecked() and not any("{bates}" in e.text() for e in self.edits.values()):
            self.edits["br"].setText((self.edits["br"].text() + " {bates}").strip())
        self.accept()

    def values(self):
        texts = {k: e.text() for k, e in self.edits.items() if e.text().strip()}
        bates = None
        if self.chk_bates.isChecked():
            bates = (self.prefix.text(), self.start.value(), self.digits.value())
        return texts, self.size.value(), self.margin.value() / 25.4 * 72, self.pages.text().strip(), bates


class PageLabelsDialog(QDialog):
    """PDF page labels: the numbers a viewer shows for pages, such as
    i, ii, iii for the front matter and 1, 2, 3 from the first chapter."""

    STYLES = (("D", "1, 2, 3"), ("r", "i, ii, iii"), ("R", "I, II, III"),
              ("a", "a, b, c"), ("A", "A, B, C"), ("", "ไม่มีเลข (ใช้คำนำหน้าอย่างเดียว)"))

    def __init__(self, parent, T, cur_page, page_count, current_labels):
        super().__init__(parent)
        self.setWindowTitle(T("ป้ายเลขหน้า"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        info = QLabel(T("เปลี่ยนเลขที่โปรแกรมอ่าน PDF แสดงในช่องเลขหน้า (เนื้อหาบนหน้าไม่เปลี่ยน)\n"
                        "ตัวอย่าง: หน้าคำนำเป็น i, ii แล้วเริ่มบทที่ 1 เป็นหน้า 1"))
        info.setStyleSheet(_GREY)
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.start_page = QSpinBox()
        self.start_page.setRange(1, max(1, page_count))
        self.start_page.setValue(cur_page)
        self.style = QComboBox()
        for key, label in self.STYLES:
            self.style.addItem(T(label), key)
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText(T("เช่น ภาคผนวก-"))
        self.first = QSpinBox()
        self.first.setRange(1, 99999)
        form.addRow(T("เริ่มที่หน้า (ลำดับจริง):"), self.start_page)
        form.addRow(T("รูปแบบ:"), self.style)
        form.addRow(T("คำนำหน้า:"), self.prefix)
        form.addRow(T("เริ่มนับจาก:"), self.first)
        lay.addLayout(form)
        now = QLabel(T("ตอนนี้: ") + ", ".join(current_labels[:12]) + (" …" if len(current_labels) > 12 else ""))
        now.setStyleSheet(_GREY)
        now.setWordWrap(True)
        lay.addWidget(now)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("ตกลง"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        return (self.start_page.value() - 1, self.style.currentData(),
                self.prefix.text(), self.first.value())


class FindRedactDialog(QDialog):
    """Find a word or number - an ID card number, a patient's name - and
    remove every occurrence for good."""

    def __init__(self, parent, T, counter):
        super().__init__(parent)
        self._T = T
        self.counter = counter
        self.setWindowTitle(T("ค้นหาแล้วลบข้อมูลถาวร"))
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(T("คำหรือตัวเลขที่จะลบออกจากทั้งไฟล์:")))
        self.query = QLineEdit()
        self.query.setPlaceholderText(T("เช่น เลขบัตรประชาชน ชื่อผู้ป่วย เบอร์โทร"))
        self.query.textChanged.connect(self._count)
        lay.addWidget(self.query)
        self.found = QLabel(" ")
        self.found.setStyleSheet(_GREY)
        lay.addWidget(self.found)
        row = QHBoxLayout()
        row.addWidget(QLabel(T("ปิดทับด้วยสี:")))
        self.rb_black = QRadioButton(T("ดำ"))
        self.rb_black.setChecked(True)
        self.rb_white = QRadioButton(T("ขาว"))
        row.addWidget(self.rb_black)
        row.addWidget(self.rb_white)
        row.addStretch(1)
        lay.addLayout(row)
        warn = QLabel(T("ข้อความใต้กรอบจะถูกลบออกจากไฟล์จริง ไม่ใช่แค่ปิดทับ "
                        "คัดลอกหรือค้นหาไม่เจออีก • กด Ctrl+Z ย้อนกลับได้ก่อนบันทึก"))
        warn.setStyleSheet("color: #b45309;")
        warn.setWordWrap(True)
        lay.addWidget(warn)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        self.ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(T("ลบทุกจุด"))
        self.ok.setEnabled(False)
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _count(self, text):
        n = self.counter(text.strip()) if text.strip() else 0
        self.found.setText(self._T("พบ %d จุด") % n if text.strip() else " ")
        self.ok.setEnabled(n > 0)

    def values(self):
        return self.query.text().strip(), ((1, 1, 1) if self.rb_white.isChecked() else (0, 0, 0))


class CommentListDialog(QDialog):
    """Every comment in the file in one table; double-click to go there."""

    KINDS = {"Text": "โน้ต", "FreeText": "กล่องข้อความ", "Line": "เส้น / ลูกศร",
             "Square": "สี่เหลี่ยม", "Circle": "วงรี", "Polygon": "รูปหลายเหลี่ยม",
             "PolyLine": "เส้นหลายช่วง", "Highlight": "ไฮไลท์", "Underline": "ขีดเส้นใต้",
             "Squiggly": "เส้นหยัก", "StrikeOut": "ขีดฆ่า", "Stamp": "ตราประทับ",
             "Caret": "แทรกข้อความ", "Ink": "ปากกา", "FileAttachment": "ไฟล์แนบ",
             "Sound": "เสียง"}

    def __init__(self, parent, T, comments, goto):
        super().__init__(parent)
        from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem
        self.setWindowTitle(T("รายการคอมเมนต์ทั้งหมด (%d)") % len(comments))
        self.resize(760, 480)
        lay = QVBoxLayout(self)
        table = QTableWidget(len(comments), 4)
        table.setHorizontalHeaderLabels([T("หน้า"), T("ชนิด"), T("ผู้เขียน"), T("ข้อความ")])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = table.horizontalHeader()
        for c in (0, 1, 2):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for r, (pno, kind, author, text, _date) in enumerate(comments):
            for c, val in enumerate((str(pno + 1), T(self.KINDS.get(kind, kind)), author,
                                     (text or "").replace("\n", " "))):
                table.setItem(r, c, QTableWidgetItem(val))
        table.cellDoubleClicked.connect(lambda r, _c: (goto(comments[r][0]), self.accept()))
        lay.addWidget(table, 1)
        hint = QLabel(T("ดับเบิลคลิกเพื่อไปที่หน้านั้น"))
        hint.setStyleSheet(_GREY)
        lay.addWidget(hint)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText(T("ปิด"))
        close.rejected.connect(self.reject)
        lay.addWidget(close)


def _plain(text):
    """Menu text without its accelerator: 'File(&F)' -> 'File'."""
    text = re.sub(r"\(&\w\)", "", text)
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


class CommandPalette(QDialog):
    """Ctrl+K: type a few letters - Thai or English - and run any command
    from any menu, without hunting through the menu bar."""

    def __init__(self, parent, T, menubar, english=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("palette")
        self.resize(620, 430)
        self.entries = []                     # (label, path, haystack, action)
        english = english or {}
        thai = {v: k for k, v in english.items()}   # match Thai words in the English UI too

        def walk(menu, path):
            for a in menu.actions():
                if a.isSeparator():
                    continue
                if a.menu():
                    walk(a.menu(), path + [_plain(a.text())])
                elif a.text() and a.isVisible():
                    label = _plain(a.text())
                    hay = " ".join([label, " ".join(path), english.get(a.text(), ""),
                                    thai.get(a.text(), "")]).lower()
                    self.entries.append((label, " › ".join(path), hay, a))

        for top in menubar.actions():
            if top.menu():
                walk(top.menu(), [_plain(top.text())])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.edit = QLineEdit()
        self.edit.setObjectName("paletteEdit")
        self.edit.setPlaceholderText(T("พิมพ์ชื่อคำสั่ง เช่น ลายเซ็น, บีบอัด, word, pdf/a ..."))
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.itemActivated.connect(self._run)
        lay.addWidget(self.list, 1)
        hint = QLabel(T("↑ ↓ เลือก • Enter ทำคำสั่ง • Esc ปิด"))
        hint.setStyleSheet(_GREY)
        lay.addWidget(hint)
        self._filter("")
        self.edit.setFocus()

    def _filter(self, text):
        words = text.lower().split()
        self.list.clear()
        for label, path, hay, action in self.entries:
            if all(w in hay for w in words):
                it = QListWidgetItem("%s   —   %s" % (label, path))
                it.setData(Qt.ItemDataRole.UserRole, action)
                it.setToolTip(path)
                if not action.isEnabled():
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if k == Qt.Key.Key_Down else -1)
                if 0 <= row < self.list.count():
                    self.list.setCurrentRow(row)
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run(self.list.currentItem())
                return True
        return super().eventFilter(obj, ev)

    def _run(self, item):
        if item is None:
            return
        action = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if action is not None and action.isEnabled():
            action.trigger()


class WelcomePanel(QWidget):
    """What the window shows before a file is open: a big Open button, the
    recent files and the tools people come for, one click each."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("welcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(40, 30, 40, 30)
        self.rebuild()

    def rebuild(self):
        while self.outer.count():
            item = self.outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            elif item.layout() is not None:
                QWidget().setLayout(item.layout())     # drop the old layout
        win, T = self.win, self.win.T
        self.outer.addStretch(1)

        card = QFrame()
        card.setObjectName("welcomeCard")
        card.setMaximumWidth(860)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(12)

        title = QLabel("WnyEditPDF")
        title.setObjectName("welcomeTitle")
        lay.addWidget(title)
        sub = QLabel(T("อ่าน แก้ไข ลงนาม และจัดการ PDF ภาษาไทยครบในโปรแกรมเดียว — ทำงานในเครื่อง ไม่ส่งไฟล์ออกไปไหน"))
        sub.setObjectName("welcomeSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        row = QHBoxLayout()
        open_btn = QPushButton("  " + T("เปิดไฟล์ PDF"))
        open_btn.setObjectName("welcomeOpen")
        open_btn.setIcon(icon("folder-open", "#ffffff", 20))
        open_btn.setIconSize(QSize(20, 20))
        open_btn.clicked.connect(win.open_pdf)
        row.addWidget(open_btn)
        drop = QLabel(T("หรือลากไฟล์ PDF มาวางที่นี่  •  Ctrl+K ค้นหาเครื่องมือทั้งหมด"))
        drop.setObjectName("welcomeSub")
        row.addWidget(drop, 1)
        lay.addLayout(row)

        recent = [p for p in win._recent_list() if os.path.isfile(p)][:5]
        if recent:
            head = QLabel(T("ไฟล์ล่าสุด"))
            head.setObjectName("welcomeHead")
            lay.addWidget(head)
            for p in recent:
                b = QPushButton("  %s     %s" % (os.path.basename(p), os.path.dirname(p)))
                b.setObjectName("welcomeRecent")
                b.setIcon(icon("file-text", "#e03e3e", 18))
                b.setToolTip(p)
                b.clicked.connect(lambda _=False, path=p: self._open_recent(path))
                lay.addWidget(b)

        head = QLabel(T("เครื่องมือยอดนิยม"))
        head.setObjectName("welcomeHead")
        lay.addWidget(head)
        grid = QGridLayout()
        grid.setSpacing(10)
        tools = (
            (("files", PURPLE), "รวมหลายไฟล์", "PDF, รูปภาพ, ข้อความ รวมเป็น PDF เดียว", win.combine_files, False),
            (("gauge", RED), "บีบอัด PDF", "ลดขนาดไฟล์ได้ทีละหลายไฟล์", win.compress_pdfs, False),
            (("file-text", BLUE), "แปลงเป็น Word", "ภาษาไทยไม่เพี้ยน แก้ต่อได้", win.export_word, True),
            (("signature", TEAL), "ลงนามดิจิทัล", "ด้วยใบรับรอง .p12 บัตร หรือโทเคน", win.sign_digital, True),
            (("shield-check", TEAL), "ตรวจลายเซ็น", "ไฟล์ถูกแก้หลังลงนามหรือไม่", win.verify_signatures, True),
            (("git-compare", BLUE), "เปรียบเทียบเอกสาร", "หาจุดต่างของสองเวอร์ชัน", win.compare_versions, True),
            (("file-check", GREEN), "PDF/A เก็บถาวร", "ตรวจและแปลงไฟล์เพื่อเก็บถาวร", win.pdfa_check, True),
            (("brush-cleaning", BLUE), "ลบข้อมูลแฝง", "ก่อนส่งไฟล์ออกนอกหน่วยงาน", win.sanitize_document, True),
        )
        for i, (art, name, desc, fn, needs) in enumerate(tools):
            grid.addWidget(self._card(art, T(name), T(desc), fn, needs), i // 4, i % 4)
        lay.addLayout(grid)

        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(card, 10)
        h.addStretch(1)
        self.outer.addLayout(h)
        self.outer.addStretch(2)

    def _card(self, art, name, desc, fn, needs_file):
        """A tool tile: bold name over a grey line of explanation that wraps
        instead of being cut off; the whole tile is one click target."""
        b = QPushButton()
        b.setObjectName("welcomeTool")
        b.setMinimumHeight(78)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(b)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(pixmap(art[0], art[1], 22))
        title = QLabel(name)
        title.setObjectName("toolName")
        head.addWidget(glyph)
        head.addWidget(title, 1)
        lay.addLayout(head)
        text = QLabel(desc)
        text.setObjectName("toolDesc")
        text.setWordWrap(True)
        for lbl in (glyph, title, text):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(text)
        lay.addStretch(1)
        b.setToolTip(desc)
        b.clicked.connect(lambda _=False: self._tool(fn, needs_file))
        return b

    def _open_recent(self, path):
        if self.win.confirm_discard():
            self.win._open_path(path)

    def _tool(self, fn, needs_file):
        if needs_file and not self.win.pdf.is_open():
            self.win.open_pdf()
            if not self.win.pdf.is_open():
                return
        fn()


# ======================================================================
#  The menu actions
# ======================================================================
class DocToolsMixin:
    """Handlers for the Document menu and the engine-backed File / Page /
    Signature entries. Mixed into MainWindow."""

    # ---------------- plumbing ----------------
    def _engine_ready(self):
        if engine.available():
            return True
        QMessageBox.warning(
            self, APP_NAME,
            self.T("ไม่พบเอนจิน PdfCraft (pdfcraft-cli.exe)\n\n"
                   "ถ้ารันจากซอร์สโค้ด ให้ build ด้วย build.bat ก่อน"))
        return False

    def _doc_ready(self):
        if not self.pdf.is_open():
            self.need_file()
            return False
        return self._engine_ready()

    def _engine_failed(self, what, err):
        QMessageBox.critical(self, APP_NAME, self.T("%s ไม่สำเร็จ:\n%s") % (self.T(what), err))

    def _doc_bytes(self):
        return self.pdf.doc.tobytes()

    def _doc_name(self):
        return os.path.basename(self.pdf.path or "document.pdf")

    def _doc_stem(self):
        return os.path.splitext(self._doc_name())[0]

    def _doc_folder(self):
        if self.pdf.path:
            return os.path.dirname(os.path.abspath(self.pdf.path))
        return os.path.join(os.path.expanduser("~"), "Documents")

    def _apply_engine_result(self, data, msg):
        self.pdf.apply_bytes(data)
        self._drop_stale_selection()
        self.refresh_all()
        self.status(msg)

    def _confirm_break_signature(self):
        """Saving rewrites the whole file, which invalidates every digital
        signature in it. Say so before it happens."""
        if not self.pdf.is_signed():
            return True
        ans = QMessageBox.warning(
            self, APP_NAME,
            self.T("ไฟล์นี้มีลายเซ็นดิจิทัล\n\nถ้าบันทึกการแก้ไข ลายเซ็นเดิมจะใช้ไม่ได้ "
                   "(ตรวจสอบแล้วจะขึ้นว่าเอกสารถูกแก้ไข)\n\nต้องการบันทึกต่อหรือไม่?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return ans == QMessageBox.StandardButton.Yes

    # ---------------- properties & bookmarks (PyMuPDF) ----------------
    def doc_properties(self):
        if not self.pdf.is_open():
            return self.need_file()
        info = None
        if engine.available():
            try:
                info = run_job(self, self.T("กำลังอ่านข้อมูลเอกสาร..."),
                               engine.info, self._doc_bytes(), self._doc_name())
            except engine.EngineError:
                info = None              # details are a bonus; editing still works
        dlg = PropertiesDialog(self, self.T, self.pdf.metadata(), info)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg.values()
        if new != self.pdf.metadata():
            self.pdf.set_metadata(new)
            self._update_undo_buttons()
            self.status(self.T("บันทึกคุณสมบัติเอกสารแล้ว ✓ (กดบันทึกไฟล์เพื่อเก็บถาวร)"))

    def edit_bookmarks(self):
        if not self.pdf.is_open():
            return self.need_file()
        dlg = BookmarksDialog(self, self.T, self.pdf.toc(), self.pdf.page_count,
                              self.page_index + 1)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        toc = dlg.toc()
        if toc != self.pdf.toc():
            self.pdf.set_toc(toc)
            self._update_undo_buttons()
            self.status(self.T("ปรับบุ๊กมาร์กแล้ว %d รายการ ✓") % len(toc))

    # ---------------- compare ----------------
    def compare_versions(self):
        if not self._doc_ready():
            return
        T = self.T
        old, _ = QFileDialog.getOpenFileName(self, T("เลือกไฟล์เวอร์ชันเก่าที่จะเทียบ"),
                                             self._doc_folder(), "PDF Files (*.pdf)")
        if not old:
            return
        n, need_pw = self.pdf.peek_page_count(old)
        pw = None
        if need_pw:
            from PyQt6.QtWidgets import QInputDialog
            pw, ok = QInputDialog.getText(self, T("ไฟล์มีรหัสผ่าน"), T("กรอกรหัสผ่าน:"),
                                          QLineEdit.EchoMode.Password)
            if not ok:
                return
        data = self._doc_bytes()
        try:
            res = run_job(self, T("กำลังเปรียบเทียบเอกสาร..."), engine.compare, data, old, pw)
        except engine.EngineError as e:
            return self._engine_failed("เปรียบเทียบ", e)

        kinds = {"replaced": ("ข้อความถูกแก้", "#1d4ed8"), "inserted": ("ข้อความเพิ่ม", "#15803d"),
                 "deleted": ("ข้อความถูกลบ", "#b91c1c")}
        body = ["<h3>%s</h3>" % _esc(T("เทียบกับ: %s") % os.path.basename(old))]
        if res.get("identical"):
            body.append("<p><b>%s</b></p>" % _esc(T("ข้อความในสองไฟล์เหมือนกันทุกคำ")))
        else:
            body.append("<p>%s</p>" % _esc(
                T("แก้ไข %d จุด • เพิ่ม %d จุด • ลบ %d จุด") % (
                    res.get("replaced", 0), res.get("inserted", 0), res.get("deleted", 0))))
            body.append("<table cellpadding='4' style='border-collapse:collapse'>")
            body.append("<tr style='background:#f3f4f6'><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>"
                        % tuple(_esc(T(x)) for x in ("ชนิด", "หน้า", "เดิม", "ใหม่")))
            for ch in res.get("changes", []):
                label, color = kinds.get(ch.get("kind"), (ch.get("kind"), "#111"))
                o, n_ = ch.get("old") or {}, ch.get("new") or {}
                page = n_.get("page") or o.get("page") or ""
                body.append("<tr><td style='color:%s'><b>%s</b></td><td>%s</td>"
                            "<td><s>%s</s></td><td>%s</td></tr>"
                            % (color, _esc(T(label)), _esc(page), _esc(o.get("text"), 200),
                               _esc(n_.get("text"), 200)))
            body.append("</table>")
        if res.get("visual"):
            body.append("<p>%s</p>" % _esc(T("พบส่วนที่หน้าตาต่างกัน (รูป/เส้น) %d จุด")
                                           % len(res["visual"])))

        def save_report(dlg):
            out, _ = QFileDialog.getSaveFileName(
                dlg, T("บันทึกรายงานเปรียบเทียบ"),
                os.path.join(self._doc_folder(), self._doc_stem() + "_compare.pdf"),
                "PDF Files (*.pdf)")
            if not out:
                return
            try:
                run_job(dlg, T("กำลังสร้างรายงาน..."), engine.compare_report, data, old, out, pw)
            except engine.EngineError as e:
                return self._engine_failed("สร้างรายงาน", e)
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

        def mark(dlg):
            try:
                marked = run_job(dlg, T("กำลังใส่คอมเมนต์..."), engine.compare_mark, data, old, pw)
            except engine.EngineError as e:
                return self._engine_failed("ใส่คอมเมนต์", e)
            dlg.accept()
            self._apply_engine_result(marked, T("ใส่จุดที่ต่างกันเป็นคอมเมนต์แล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))

        buttons = [] if res.get("identical") else [
            (T("📄 บันทึกรายงาน PDF..."), save_report),
            (T("💬 ใส่จุดที่ต่างเป็นคอมเมนต์ในไฟล์นี้"), mark)]
        ReportDialog(self, T("ผลการเปรียบเทียบเอกสาร"), "".join(body), buttons,
                     T("ปิด")).exec()

    # ---------------- PDF/A ----------------
    def pdfa_check(self):
        if not self._doc_ready():
            return
        T = self.T
        data = self._doc_bytes()
        try:
            res = run_job(self, T("กำลังตรวจมาตรฐาน PDF/A..."), engine.pdfa_verify, data)
        except engine.EngineError as e:
            return self._engine_failed("ตรวจ PDF/A", e)

        def issues_html(r):
            rows = []
            for i in r.get("issues", []):
                fix = T("แก้อัตโนมัติได้") if i.get("fixable") else T("ต้องแก้ที่ต้นฉบับ")
                page = (T("หน้า %s") % i["page"]) if i.get("page") else ""
                rows.append("<li><b>%s</b> %s — %s <i style='color:#6b7280'>(%s)</i></li>"
                            % (_esc(i.get("clause")), _esc(page), _esc(i.get("message")), _esc(fix)))
            return "<ul>%s</ul>" % "".join(rows) if rows else ""

        declared = (res.get("declared") or {}).get("pdfa")
        head = (T("✅ ไฟล์นี้เป็นไปตามมาตรฐาน %s") % res.get("level") if res.get("compliant")
                else T("❌ ไฟล์นี้ยังไม่เป็นไปตามมาตรฐาน %s") % res.get("level"))
        body = ("<h3>%s</h3><p>%s</p>%s<p style='color:#6b7280'>%s</p>" % (
            _esc(head), _esc(T("ไฟล์ประกาศตัวเองว่าเป็น: %s") % (declared or "-")),
            issues_html(res),
            _esc(T("PDF/A คือมาตรฐานไฟล์สำหรับเก็บถาวรระยะยาว ใช้กับระบบสารบรรณอิเล็กทรอนิกส์"))))

        def convert(dlg):
            try:
                out, rep = run_job(dlg, T("กำลังแปลงเป็น PDF/A..."), engine.pdfa_convert, data)
            except engine.EngineError as e:
                return self._engine_failed("แปลง PDF/A", e)
            dlg.accept()
            self._apply_engine_result(out, T("แปลงเป็น PDF/A แล้ว — กดบันทึกเพื่อเก็บไฟล์ (Ctrl+Z ย้อนกลับได้)"))
            if rep.get("compliant"):
                QMessageBox.information(self, APP_NAME,
                                        T("แปลงเป็น %s เรียบร้อย ✓\n\nกด 'บันทึกเป็น...' เพื่อเก็บเป็นไฟล์ใหม่")
                                        % rep.get("level"))
            else:
                ReportDialog(self, T("ผลการแปลง PDF/A"),
                             "<h3>%s</h3>%s" % (_esc(T("แก้ไขได้บางส่วน ยังเหลือปัญหาที่ต้องแก้ที่ต้นฉบับ:")),
                                                issues_html(rep)), close_text=T("ปิด")).exec()

        buttons = [] if res.get("compliant") else [(T("🛠 แปลงเป็น PDF/A-2b"), convert)]
        ReportDialog(self, T("ตรวจมาตรฐาน PDF/A"), body, buttons, T("ปิด")).exec()

    # ---------------- accessibility ----------------
    def accessibility_check(self):
        if not self._doc_ready():
            return
        T = self.T
        report = os.path.join(tempfile.gettempdir(), "wny_accessibility_%s.html" % int(time.time()))
        try:
            res = run_job(self, T("กำลังตรวจการเข้าถึง..."), engine.accessibility_report,
                          self._doc_bytes(), report, self._doc_name())
        except engine.EngineError as e:
            return self._engine_failed("ตรวจการเข้าถึง", e)
        failed = [r for r in res.get("results", []) if r.get("status") == "failed"]
        body = ["<h3>%s</h3>" % _esc(T("ผ่าน %d • ไม่ผ่าน %d • ต้องตรวจด้วยตนเอง %d") % (
            res.get("passed", 0), res.get("failed", 0), res.get("manual", 0)))]
        if failed:
            body.append("<p>%s</p><ul>" % _esc(T("ข้อที่ไม่ผ่าน:")))
            for r in failed:
                body.append("<li><b>%s</b> <span style='color:#6b7280'>(%s)</span></li>"
                            % (_esc(r.get("name")), _esc(r.get("category"))))
            body.append("</ul>")
        body.append("<p style='color:#6b7280'>%s</p>" % _esc(
            T("ตรวจตามหลักการเข้าถึงสำหรับผู้พิการ (เช่น โปรแกรมอ่านหน้าจอ) — "
              "รายงานฉบับเต็มเป็นภาษาอังกฤษ")))
        ReportDialog(self, T("ตรวจการเข้าถึง (Accessibility)"), "".join(body),
                     [(T("🌐 เปิดรายงานฉบับเต็ม"),
                       lambda _d: QDesktopServices.openUrl(QUrl.fromLocalFile(report)))],
                     T("ปิด")).exec()

    # ---------------- sanitize / flatten / form fields ----------------
    def sanitize_document(self):
        if not self._doc_ready():
            return
        T = self.T
        data = self._doc_bytes()
        try:
            scan = run_job(self, T("กำลังค้นหาข้อมูลแฝง..."), engine.hidden_info, data)
        except engine.EngineError as e:
            return self._engine_failed("ค้นหาข้อมูลแฝง", e)
        if not scan.get("total"):
            QMessageBox.information(self, APP_NAME, T("ไม่พบข้อมูลแฝงในเอกสารนี้ ✓"))
            return
        dlg = SanitizeDialog(self, T, scan)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected():
            return
        try:
            out = run_job(self, T("กำลังลบข้อมูลแฝง..."), engine.remove_hidden, data, dlg.selected())
        except engine.EngineError as e:
            return self._engine_failed("ลบข้อมูลแฝง", e)
        self._apply_engine_result(out, T("ลบข้อมูลแฝงแล้ว ✓ — กดบันทึกเพื่อเก็บไฟล์ (Ctrl+Z ย้อนกลับได้)"))

    def flatten_document(self):
        if not self._doc_ready():
            return
        T = self.T
        dlg = QDialog(self)
        dlg.setWindowTitle(T("ทำให้แบนราบ (Flatten)"))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(T("ฝังคอมเมนต์และช่องฟอร์มลงในเนื้อหน้า\n"
                               "พิมพ์และเปิดดูได้เหมือนเดิมทุกโปรแกรม แต่จะแก้ไขไม่ได้อีก")))
        cb_c = QCheckBox(T("คอมเมนต์ / ลายเส้น / ตราประทับ"))
        cb_c.setChecked(True)
        cb_f = QCheckBox(T("ช่องฟอร์มที่กรอกแล้ว"))
        cb_f.setChecked(True)
        lay.addWidget(cb_c)
        lay.addWidget(cb_f)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("ทำให้แบนราบ"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ยกเลิก"))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted or not (cb_c.isChecked() or cb_f.isChecked()):
            return
        try:
            out = run_job(self, T("กำลังทำให้แบนราบ..."), engine.flatten,
                          self._doc_bytes(), cb_c.isChecked(), cb_f.isChecked())
        except engine.EngineError as e:
            return self._engine_failed("Flatten", e)
        self._apply_engine_result(out, T("ทำให้แบนราบแล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))

    def detect_form_fields(self):
        if not self._doc_ready():
            return
        T = self.T
        try:
            out, rep = run_job(self, T("กำลังหาช่องว่างในแบบฟอร์ม..."),
                               engine.detect_fields, self._doc_bytes())
        except engine.EngineError as e:
            return self._engine_failed("สร้างช่องกรอก", e)
        fields = rep.get("fields", [])
        if not fields:
            QMessageBox.information(self, APP_NAME,
                                    T("ไม่พบช่องว่างที่เป็นช่องกรอก (เส้นใต้ ____ หรือกล่องสี่เหลี่ยม)"))
            return
        self._apply_engine_result(out, T("สร้างช่องกรอกแล้ว %d ช่อง ✓ (Ctrl+Z ย้อนกลับได้)") % len(fields))
        QMessageBox.information(self, APP_NAME,
                                T("สร้างช่องกรอกอัตโนมัติ %d ช่อง\n\n"
                                  "กรอกได้จากเมนู เครื่องมือ → กรอกฟอร์ม\n"
                                  "หรือคลิกที่ช่องในโหมดแก้ข้อความ") % len(fields))

    # ---------------- split / combine / images ----------------
    def split_document(self):
        if not self._doc_ready():
            return
        T = self.T
        has_bm = any(lvl == 1 for lvl, _t, _p in self.pdf.toc())
        dlg = SplitDialog(self, T, self.pdf.page_count, has_bm, self._doc_folder(), self._doc_stem())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        if "before" in v and not v["before"]:
            return QMessageBox.warning(self, APP_NAME, T("กรุณาระบุเลขหน้า เช่น 4, 10"))
        out_dir = v.pop("out_dir")
        try:
            os.makedirs(out_dir, exist_ok=True)
            res = run_job(self, T("กำลังแยกไฟล์..."), engine.split, self._doc_bytes(),
                          out_dir, self._doc_name(), **v)
        except (OSError, engine.EngineError) as e:
            return self._engine_failed("แยกไฟล์", e)
        files = res.get("files", [])
        self.status(T("แยกเป็น %d ไฟล์แล้ว ✓") % len(files))
        if files and QMessageBox.question(
                self, APP_NAME,
                T("แยกเป็น %d ไฟล์เรียบร้อย\n\nเปิดโฟลเดอร์ที่บันทึกไว้หรือไม่?") % len(files)
        ) == QMessageBox.StandardButton.Yes:
            _reveal(out_dir)

    def combine_files(self):
        if not self._engine_ready():
            return
        T = self.T
        start, tmpdir = [], None
        if self.pdf.is_open() and self.pdf.path:
            if self.pdf.modified:
                # combine exactly what is on screen, under the file's own name
                # (the engine names each file's bookmark after it)
                tmpdir = tempfile.mkdtemp(prefix="wny_combine_")
                snap = os.path.join(tmpdir, self._doc_name())
                self.pdf.doc.save(snap, garbage=1)
                start.append(snap)
            else:
                start.append(self.pdf.path)
        try:
            dlg = CombineDialog(self, T, start)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            files = dlg.files()
            out, _ = QFileDialog.getSaveFileName(
                self, T("บันทึกไฟล์ที่รวมแล้วเป็น"),
                os.path.join(self._doc_folder(), T("รวมไฟล์") + ".pdf"), "PDF Files (*.pdf)")
            if not out:
                return
            if not out.lower().endswith(".pdf"):
                out += ".pdf"
            if any(os.path.abspath(out) == os.path.abspath(f) for f in files):
                return QMessageBox.warning(self, APP_NAME,
                                           T("ห้ามบันทึกทับไฟล์ที่อยู่ในรายการ — กรุณาตั้งชื่อใหม่"))
            try:
                run_job(self, T("กำลังรวมไฟล์..."), engine.create_multiple, files, out)
            except engine.EngineError as e:
                return self._engine_failed("รวมไฟล์", e)
        finally:
            if tmpdir:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
        self.status(T("รวม %d ไฟล์แล้ว: %s ✓") % (len(files), os.path.basename(out)))
        if QMessageBox.question(self, APP_NAME, T("รวมไฟล์เรียบร้อย\n\nเปิดไฟล์ที่รวมแล้วหรือไม่?")
                                ) == QMessageBox.StandardButton.Yes and self.confirm_discard():
            self._open_path(out)

    def export_embedded_images(self):
        if not self._doc_ready():
            return
        T = self.T
        folder = QFileDialog.getExistingDirectory(self, T("เลือกโฟลเดอร์ที่จะบันทึกรูป"),
                                                  self._doc_folder())
        if not folder:
            return
        try:
            res = run_job(self, T("กำลังดึงรูปภาพ..."), engine.export_all_images,
                          self._doc_bytes(), folder, self._doc_name())
        except engine.EngineError as e:
            return self._engine_failed("ดึงรูปภาพ", e)
        n, skipped = res.get("count", 0), len(res.get("skipped", []))
        msg = T("บันทึกรูปภาพแล้ว %d รูป") % n
        if skipped:
            msg += "\n" + T("ข้ามไป %d รูป (รูปแบบที่ยังอ่านไม่ได้ เช่น JPEG 2000 / JBIG2)") % skipped
        self.status(msg.replace("\n", " • "))
        if n and QMessageBox.question(self, APP_NAME, msg + "\n\n" + T("เปิดโฟลเดอร์หรือไม่?")
                                      ) == QMessageBox.StandardButton.Yes:
            _reveal(folder)
        elif not n:
            QMessageBox.information(self, APP_NAME, msg)

    # ---------------- digital signatures ----------------
    def _stamp_signature_box(self, data, name, page, position, reason):
        """Draw the visible 'digitally signed by' box with OUR Thai fonts
        (the engine's own appearance can only draw Latin text) on a copy of
        the document. The certificate signature itself is invisible and
        covers the whole file, this box included."""
        T = self.T
        doc = fitz.open("pdf", data)
        try:
            pg = doc[max(0, min(page - 1, doc.page_count - 1))]
            now = time.localtime()
            if self.lang == "en":
                when = time.strftime("%Y-%m-%d %H:%M", now)
            else:                                    # Thai documents use the Buddhist year
                when = "%02d/%02d/%d %02d:%02d น." % (now.tm_mday, now.tm_mon,
                                                      now.tm_year + 543, now.tm_hour, now.tm_min)
            lines = [T("ลงนามดิจิทัลโดย: %s") % name, T("วันที่: %s") % when]
            if reason:
                lines.append(T("เหตุผล: %s") % reason)
            fonts = [self.pdf.default_thai_font, self.current_font_path]
            size, lh = 13.0, 15.0
            try:
                f = self.pdf._cached_font(fonts[0])
                w = max(f.text_length(s, fontsize=size) for s in lines) + 18
            except Exception:
                w = 230
            w = max(170.0, min(w, pg.rect.width - 72))
            h = lh * len(lines) + 10
            m = 36
            x0 = m if position.endswith("left") else pg.rect.width - m - w
            y0 = m if position.startswith("top") else pg.rect.height - m - h
            box = fitz.Rect(x0, y0, x0 + w, y0 + h)
            pg.draw_rect(box, color=(0.08, 0.27, 0.62), fill=(0.94, 0.96, 1.0),
                         width=0.9, fill_opacity=0.92)
            for i, s in enumerate(lines):
                self.pdf._insert_text_chain(pg, (x0 + 9, y0 + 5 + lh * (i + 1) - 3.5), s,
                                            size, (0.05, 0.16, 0.42), fonts)
            return doc.tobytes(garbage=3, deflate=True)
        finally:
            doc.close()

    def sign_digital(self):
        if not self._doc_ready():
            return
        T = self.T
        try:
            win_ids = run_job(self, T("กำลังโหลดรายการใบรับรอง..."), engine.windows_ids)
        except engine.EngineError:
            win_ids = []
        dlg = SignDialog(self, T, win_ids, self.pdf.page_count, self.page_index + 1, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        cert = v["cert"]
        if cert is None:                 # a .p12 file: open it now to check the password
            try:
                cert = run_job(self, T("กำลังเปิดใบรับรอง..."), engine.id_info, v["id"], v["password"])
            except engine.EngineError as e:
                return self._engine_failed("เปิดใบรับรอง", e)
        out, _ = QFileDialog.getSaveFileName(
            self, T("บันทึกไฟล์ที่ลงนามแล้วเป็น"),
            os.path.join(self._doc_folder(), self._doc_stem() + "_signed.pdf"), "PDF Files (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        data = self._doc_bytes()
        try:
            if v["visible"]:
                data = self._stamp_signature_box(data, cert.get("name") or "-", v["page"],
                                                 v["position"], v["reason"])
            res = run_job(self, T("กำลังลงนาม..."), engine.sign, data, out, v["id"],
                          v["password"], reason=v["reason"], location=v["location"],
                          contact=v["contact"], certify=v["certify"], name=self._doc_name())
        except engine.EngineError as e:
            return self._engine_failed("การลงนาม", e)
        except Exception as e:
            return self._engine_failed("การลงนาม", e)
        # The signed file already holds every edit made so far, so switching
        # to it loses nothing - and it is the file the user now cares about.
        self.pdf.modified = False
        self._open_path(out)
        sig = res.get("signature") or {}
        self.status(T("ลงนามดิจิทัลแล้ว ✓ %s — หากแก้ไขไฟล์นี้อีก ลายเซ็นจะใช้ไม่ได้")
                    % os.path.basename(out))
        QMessageBox.information(
            self, APP_NAME,
            T("ลงนามเรียบร้อย ✓\n\nผู้ลงนาม: %s\nอัลกอริทึม: %s\nบันทึกที่: %s")
            % (sig.get("signer") or cert.get("name") or "-", sig.get("algorithm") or "-", out))

    SIG_STATUS = {
        "valid": ("✅", "ถูกต้อง — เอกสารไม่ถูกแก้ไขหลังลงนาม และเชื่อถือผู้ลงนามได้", "#15803d"),
        "unknown": ("⚠️", "เอกสารไม่ถูกแก้ไขหลังลงนาม แต่ยังยืนยันตัวผู้ลงนามไม่ได้ "
                          "(ใบรับรองไม่ได้ออกโดยหน่วยงานที่เครื่องนี้เชื่อถือ เช่น ใบรับรองที่สร้างเอง)",
                    "#b45309"),
        "invalid": ("❌", "ไม่ถูกต้อง — เอกสารถูกแก้ไขหลังลงนาม หรือลายเซ็นเสียหาย", "#b91c1c"),
        "unsigned": ("▫️", "ช่องลายเซ็นว่าง ยังไม่ได้ลงนาม", "#6b7280"),
    }
    SIG_CHANGES = {
        "none": "ไม่มีการแก้ไขหลังลงนาม",
        "allowed": "มีการเปลี่ยนแปลงหลังลงนามที่ผู้ลงนามอนุญาต (เช่น กรอกฟอร์ม เพิ่มคอมเมนต์)",
        "disallowed": "มีการแก้ไขหลังลงนามที่ไม่ได้รับอนุญาต",
    }

    def verify_signatures(self):
        if not self._doc_ready():
            return
        T = self.T
        if self.pdf.modified:
            QMessageBox.information(self, APP_NAME,
                                    T("ไฟล์มีการแก้ไขที่ยังไม่บันทึก — จะตรวจจากไฟล์ที่บันทึกไว้"))
        try:
            with open(self.pdf.path, "rb") as f:     # signatures cover the bytes ON DISK
                data = f.read()
        except (OSError, TypeError):
            data = self._doc_bytes()
        trust = [p for p in (self.settings.value("sign/trusted", [], type=list) or [])
                 if os.path.isfile(p)]
        try:
            res = run_job(self, T("กำลังตรวจสอบลายเซ็น..."), engine.signatures, data, trust)
        except engine.EngineError as e:
            return self._engine_failed("ตรวจสอบลายเซ็น", e)
        if not res.get("count"):
            QMessageBox.information(self, APP_NAME, T("ไฟล์นี้ไม่มีลายเซ็นดิจิทัล"))
            return
        body = []
        for s in res.get("signatures", []):
            icon, text, color = self.SIG_STATUS.get(s.get("status"), ("?", s.get("status"), "#111"))
            c = s.get("certificate") or {}
            body.append("<h3 style='color:%s'>%s %s</h3><table>" % (color, icon, _esc(T(text))))
            for k, val in (("ผู้ลงนาม", s.get("signer") or c.get("name")),
                           ("ออกโดย", c.get("issuer")),
                           ("วันที่ลงนาม", s.get("date")),
                           ("เหตุผล", s.get("reason")), ("สถานที่", s.get("location")),
                           ("อัลกอริทึม", s.get("algorithm")),
                           ("ใบรับรองใช้ได้ถึง", c.get("valid_to")),
                           ("การแก้ไขหลังลงนาม", T(self.SIG_CHANGES.get(s.get("modification"), "-"))),
                           ("ประเภท", T("รับรองเอกสาร (Certify)") if s.get("certify") else T("ลงนามอนุมัติ"))):
                if val:
                    body.append("<tr><td style='color:#6b7280;padding-right:14px'>%s</td><td>%s</td></tr>"
                                % (_esc(T(k)), _esc(val, 300)))
            body.append("</table><p style='color:#6b7280;font-size:11px'>%s</p>" % _esc(s.get("summary"), 400))
        if trust:
            body.append("<p style='color:#6b7280'>%s</p>" % _esc(
                T("ใบรับรองที่ตั้งให้เชื่อถือ: %s") % ", ".join(os.path.basename(p) for p in trust)))

        def add_trust(dlg):
            paths, _ = QFileDialog.getOpenFileNames(
                dlg, T("เลือกใบรับรองที่เชื่อถือ (เช่น ใบรับรองหลักของหน่วยงาน)"), "",
                "Certificates (*.cer *.crt *.pem *.der *.p7b *.p7c)")
            if not paths:
                return
            keep = list(dict.fromkeys(trust + paths))
            self.settings.setValue("sign/trusted", keep)
            dlg.accept()
            self.verify_signatures()

        ReportDialog(self, T("ตรวจสอบลายเซ็นดิจิทัล"), "".join(body),
                     [(T("🔐 เพิ่มใบรับรองที่เชื่อถือ..."), add_trust)], T("ปิด")).exec()

    def create_digital_id(self):
        if not self._engine_ready():
            return
        T = self.T
        dlg = CreateIdDialog(self, T)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        safe = "".join(ch for ch in v["name"] if ch not in '\\/:*?"<>|').strip() or "my-id"
        path, _ = QFileDialog.getSaveFileName(
            self, T("บันทึกใบรับรองเป็น"),
            os.path.join(os.path.expanduser("~"), "Documents", safe + ".p12"), "Digital ID (*.p12)")
        if not path:
            return
        if not path.lower().endswith((".p12", ".pfx")):
            path += ".p12"
        try:
            run_job(self, T("กำลังสร้างใบรับรอง..."), engine.create_id, path, **v)
        except engine.EngineError as e:
            return self._engine_failed("สร้างใบรับรอง", e)
        self.settings.setValue("sign/id_path", path)
        self.settings.setValue("sign/source", "file")
        QMessageBox.information(self, APP_NAME,
                                T("สร้างใบรับรองแล้ว:\n%s\n\nเก็บไฟล์นี้และรหัสผ่านไว้ให้ดี") % path)

    # ---------------- printing (Qt) ----------------
    def print_document(self):
        """Print through the system's own print dialog. Each page is rendered
        by PyMuPDF at the printer's resolution (capped at 300 dpi) and fitted
        to the paper; a landscape page on portrait paper is turned to fit."""
        if not self.pdf.is_open():
            return self.need_file()
        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QImage, QPainter, QTransform
        from PyQt6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter
        T = self.T
        n = self.pdf.page_count
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self._doc_name())
        printer.setFromTo(1, n)
        dlg = QPrintDialog(printer, self)
        dlg.setOption(QAbstractPrintDialog.PrintDialogOption.PrintPageRange, True)
        dlg.setOption(QAbstractPrintDialog.PrintDialogOption.PrintCurrentPage, True)
        dlg.setMinMax(1, n)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rng = printer.printRange()
        if rng == QPrinter.PrintRange.CurrentPage:
            pages = [self.page_index]
        elif rng == QPrinter.PrintRange.PageRange and printer.fromPage() > 0:
            pages = list(range(printer.fromPage() - 1, min(printer.toPage(), n)))
        else:
            pages = list(range(n))
        dpi = max(96, min(printer.resolution(), 300))
        bar = QProgressDialog(T("กำลังพิมพ์..."), T("ยกเลิก"), 0, len(pages), self)
        bar.setWindowTitle(APP_NAME)
        bar.setWindowModality(Qt.WindowModality.WindowModal)
        bar.setMinimumDuration(300)
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, APP_NAME, T("เริ่มพิมพ์ไม่ได้ — ตรวจสอบเครื่องพิมพ์"))
            return
        try:
            for i, pno in enumerate(pages):
                if bar.wasCanceled():
                    printer.abort()
                    break
                if i:
                    printer.newPage()
                pix = self.pdf.doc[pno].get_pixmap(dpi=dpi, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888)
                area = painter.viewport()
                if (img.width() > img.height()) != (area.width() > area.height()):
                    img = img.transformed(QTransform().rotate(90))
                scale = min(area.width() / img.width(), area.height() / img.height())
                w, h = int(img.width() * scale), int(img.height() * scale)
                x = area.x() + (area.width() - w) // 2
                y = area.y() + (area.height() - h) // 2
                painter.drawImage(QRect(x, y, w, h), img)
                bar.setValue(i + 1)
                QApplication.processEvents()
        finally:
            painter.end()
            bar.close()
        self.status(T("ส่งไปพิมพ์แล้ว %d หน้า ✓") % len(pages))

    # ---------------- crop ----------------
    def crop_pages(self):
        if not self._doc_ready():
            return
        T = self.T
        dlg = CropDialog(self, T, self.page_index + 1, self.pdf.page_count)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        margins, all_pages = dlg.values()
        r = self.pdf.doc[self.page_index].rect
        if margins[0] + margins[2] >= r.width - 10 or margins[1] + margins[3] >= r.height - 10:
            return QMessageBox.warning(self, APP_NAME, T("ขอบที่ตัดกว้างเกินขนาดหน้า"))
        try:
            out = run_job(self, T("กำลังครอบตัดหน้า..."), engine.crop, self._doc_bytes(),
                          margins, None if all_pages else [self.page_index + 1])
        except engine.EngineError as e:
            return self._engine_failed("ครอบตัดหน้า", e)
        self._apply_engine_result(out, T("ครอบตัดหน้าแล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))

    # ---------------- password & permissions ----------------
    def protect_document(self):
        if not self.pdf.is_open():
            return self.need_file()
        T = self.T
        dlg = ProtectDialog(self, T)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        user, owner, perm = dlg.values()
        path, _ = QFileDialog.getSaveFileName(
            self, T("บันทึกไฟล์ที่ล็อกเป็น"),
            os.path.join(self._doc_folder(), self._doc_stem() + "_protected.pdf"),
            "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.pdf.save_encrypted(path, user, owner, permissions=perm)
        except Exception as e:
            return QMessageBox.critical(self, APP_NAME, T("บันทึกไม่สำเร็จ:\n%s") % e)
        self.status(T("บันทึกไฟล์ที่ล็อกแล้ว: %s ✓") % os.path.basename(path))

    # ---------------- form data & links ----------------
    def form_reset_all(self):
        if not self._doc_ready():
            return
        T = self.T
        if not self.pdf.has_form():
            return QMessageBox.information(self, APP_NAME, T("ไฟล์นี้ไม่มีช่องฟอร์ม"))
        if QMessageBox.question(self, APP_NAME, T("ล้างค่าที่กรอกในทุกช่องของฟอร์มหรือไม่?")
                                ) != QMessageBox.StandardButton.Yes:
            return
        try:
            out = run_job(self, T("กำลังล้างฟอร์ม..."), engine.form_reset, self._doc_bytes())
        except engine.EngineError as e:
            return self._engine_failed("ล้างฟอร์ม", e)
        self._apply_engine_result(out, T("ล้างค่าในฟอร์มแล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))

    def form_export_data(self):
        if not self._doc_ready():
            return
        T = self.T
        path, _ = QFileDialog.getSaveFileName(
            self, T("ส่งออกข้อมูลฟอร์มและคอมเมนต์"),
            os.path.join(self._doc_folder(), self._doc_stem() + ".xfdf"),
            "XFDF (*.xfdf);;FDF (*.fdf);;CSV (*.csv);;XML (*.xml)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".xfdf"
        what = "fields" if path.lower().endswith((".csv", ".xml", ".txt")) else "all"
        try:
            run_job(self, T("กำลังส่งออก..."), engine.export_data, self._doc_bytes(), path,
                    what, self._doc_name())
        except engine.EngineError as e:
            return self._engine_failed("ส่งออกข้อมูล", e)
        self.status(T("ส่งออกข้อมูลแล้ว: %s ✓") % os.path.basename(path))

    def form_import_data(self):
        if not self._doc_ready():
            return
        T = self.T
        path, _ = QFileDialog.getOpenFileName(
            self, T("นำเข้าข้อมูลฟอร์มและคอมเมนต์"), self._doc_folder(),
            T("ข้อมูลฟอร์ม") + " (*.xfdf *.fdf *.xml *.csv *.txt)")
        if not path:
            return
        try:
            out, rep = run_job(self, T("กำลังนำเข้า..."), engine.import_data,
                               self._doc_bytes(), path)
        except engine.EngineError as e:
            return self._engine_failed("นำเข้าข้อมูล", e)
        self.pdf.apply_bytes(out)
        self.pdf.refresh_field_appearances()       # Thai values need our fonts
        self._drop_stale_selection()
        self.refresh_all()
        self.status(T("นำเข้าแล้ว: กรอก %d ช่อง, คอมเมนต์ %d รายการ ✓ (Ctrl+Z ย้อนกลับได้)")
                    % (rep.get("filled_fields", 0), rep.get("comments", 0)))

    def auto_links(self):
        if not self._doc_ready():
            return
        T = self.T
        try:
            out, rep = run_job(self, T("กำลังหาที่อยู่เว็บ..."), engine.links_from_urls,
                               self._doc_bytes())
        except engine.EngineError as e:
            return self._engine_failed("สร้างลิงก์", e)
        urls = rep.get("urls", [])
        if not urls:
            return QMessageBox.information(
                self, APP_NAME, T("ไม่พบที่อยู่เว็บ (http://, https://, www.) ที่ยังไม่มีลิงก์"))
        self._apply_engine_result(out, T("สร้างลิงก์แล้ว %d ลิงก์ ✓ (Ctrl+Z ย้อนกลับได้)") % len(urls))

    # ---------------- command palette ----------------
    def show_command_palette(self):
        from .i18n import EN
        pal = CommandPalette(self, self.T, self.menuBar(), EN)
        geo = self.geometry()
        pal.move(geo.x() + (geo.width() - pal.width()) // 2, geo.y() + 90)
        pal.exec()

    # ---------------- shared helpers ----------------
    def _done(self, msg):
        self._drop_stale_selection()
        self.refresh_all()
        self.status(msg)

    def _ask_pages(self, title, default=""):
        """Ask for a page range; None = cancelled, [] = invalid."""
        from PyQt6.QtWidgets import QInputDialog
        T = self.T
        text, ok = QInputDialog.getText(self, title,
                                        T("หน้า (เช่น 3 หรือ 2-5, 8):"),
                                        text=default or str(self.page_index + 1))
        if not ok:
            return None
        return [n - 1 for n in self._parse_pages(text, self.pdf.page_count)]

    # ---------------- new documents ----------------
    def create_blank(self):
        from PyQt6.QtWidgets import QInputDialog
        T = self.T
        sizes = [(T("A4 แนวตั้ง"), 595.28, 841.89), (T("A4 แนวนอน"), 841.89, 595.28),
                 (T("A5 แนวตั้ง"), 419.53, 595.28), ("Letter", 612, 792)]
        label, ok = QInputDialog.getItem(self, T("สร้างเอกสารเปล่า"), T("ขนาดกระดาษ:"),
                                         [s[0] for s in sizes], 0, False)
        if not ok:
            return
        count, ok = QInputDialog.getInt(self, T("สร้างเอกสารเปล่า"), T("จำนวนหน้า:"), 1, 1, 500)
        if not ok or not self.confirm_discard():
            return
        _l, w, h = next(s for s in sizes if s[0] == label)
        self.pdf.open_bytes(self.pdf.blank_pdf(w, h, count))
        self.page_index = 0
        self._done(T("สร้างเอกสารเปล่า %d หน้าแล้ว — กดบันทึกเพื่อตั้งชื่อไฟล์") % count)

    def create_from_clipboard(self):
        from PyQt6.QtCore import QBuffer, QIODevice
        T = self.T
        img = QApplication.clipboard().image()
        if img.isNull():
            return QMessageBox.information(
                self, APP_NAME, T("คลิปบอร์ดไม่มีรูปภาพ\n\nคัดลอกรูปหรือกด PrtSc / Win+Shift+S ก่อน"))
        if not self.confirm_discard():
            return
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        self.pdf.open_bytes(self.pdf.image_pdf(bytes(buf.data())))
        self.page_index = 0
        self._done(T("สร้าง PDF จากภาพในคลิปบอร์ดแล้ว — กดบันทึกเพื่อตั้งชื่อไฟล์"))

    def export_html(self):
        if not self.pdf.is_open():
            return self.need_file()
        T = self.T
        path, _ = QFileDialog.getSaveFileName(
            self, T("บันทึกเป็นเว็บเพจ"),
            os.path.join(self._doc_folder(), self._doc_stem() + ".html"), "HTML (*.html)")
        if not path:
            return
        if not path.lower().endswith((".html", ".htm")):
            path += ".html"
        try:
            self.pdf.export_html(path)
        except Exception as e:
            return QMessageBox.critical(self, APP_NAME, T("ส่งออกไม่สำเร็จ:\n%s") % e)
        self.status(T("บันทึกเป็นเว็บเพจแล้ว: %s ✓") % os.path.basename(path))

    def remove_security(self):
        if not self.pdf.is_open():
            return self.need_file()
        T = self.T
        if not self.pdf.is_password_protected():
            return QMessageBox.information(self, APP_NAME, T("ไฟล์นี้ไม่ได้ล็อกรหัสผ่าน"))
        path, _ = QFileDialog.getSaveFileName(
            self, T("บันทึกสำเนาที่ไม่มีรหัสผ่าน"),
            os.path.join(self._doc_folder(), self._doc_stem() + "_unlocked.pdf"), "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.pdf.save_unencrypted(path)
        except Exception as e:
            return QMessageBox.critical(self, APP_NAME, T("บันทึกไม่สำเร็จ:\n%s") % e)
        self.status(T("บันทึกสำเนาที่ไม่มีรหัสผ่านแล้ว: %s ✓") % os.path.basename(path))

    # ---------------- pages ----------------
    def duplicate_page(self):
        if not self.pdf.is_open():
            return self.need_file()
        self.pdf.duplicate_page(self.page_index)
        self.page_index += 1
        self._done(self.T("ทำซ้ำหน้าแล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))

    def replace_pages(self):
        if not self._doc_ready():
            return
        T = self.T
        path, _ = QFileDialog.getOpenFileName(self, T("เลือกไฟล์ที่มีหน้าใหม่"),
                                              self._doc_folder(), "PDF Files (*.pdf)")
        if not path:
            return
        n_other, need_pw = self.pdf.peek_page_count(path)
        if need_pw or not n_other:
            return QMessageBox.warning(self, APP_NAME, T("เปิดไฟล์นี้ไม่ได้ (มีรหัสผ่านหรือไฟล์เสีย)"))
        pages = self._ask_pages(T("แทนที่หน้า"))
        if pages is None:
            return
        if not pages or len(pages) > n_other:
            return QMessageBox.warning(self, APP_NAME,
                                       T("เลขหน้าไม่ถูกต้อง หรือไฟล์ใหม่มีไม่ถึง %d หน้า") % max(1, len(pages)))
        try:
            out = run_job(self, T("กำลังแทนที่หน้า..."), engine.replace_pages, self._doc_bytes(),
                          [p + 1 for p in pages], path)
        except engine.EngineError as e:
            return self._engine_failed("แทนที่หน้า", e)
        self._apply_engine_result(out, T("แทนที่ %d หน้าแล้ว ✓ (Ctrl+Z ย้อนกลับได้)") % len(pages))

    def page_labels_ui(self):
        if not self.pdf.is_open():
            return self.need_file()
        T = self.T
        labels = [self.pdf.doc[i].get_label() or str(i + 1) for i in range(self.pdf.page_count)]
        dlg = PageLabelsDialog(self, T, self.page_index + 1, self.pdf.page_count, labels)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        start, style, prefix, first = dlg.values()
        self.pdf.set_page_label(start, style, prefix, first)
        self._done(T("ตั้งป้ายเลขหน้าแล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))

    # ---------------- headers, footers, background ----------------
    def header_footer_ui(self, bates=False):
        if not self.pdf.is_open():
            return self.need_file()
        T = self.T
        dlg = HeaderFooterDialog(self, T, self.pdf.page_count, bates)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        texts, size, margin, spec, bates_spec = dlg.values()
        pages = None
        if spec:
            pages = [n - 1 for n in self._parse_pages(spec, self.pdf.page_count)]
            if not pages:
                return QMessageBox.warning(self, APP_NAME, T("รูปแบบหน้าไม่ถูกต้องหรืออยู่นอกช่วง"))
        now = time.localtime()
        months = ("ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.",
                  "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.")
        date_text = (time.strftime("%Y-%m-%d", now) if self.lang == "en" else
                     "%d %s %d" % (now.tm_mday, months[now.tm_mon - 1], now.tm_year + 543))
        try:
            self.pdf.header_footer(self.current_font_path, texts, size=size, margin=margin,
                                   pages=pages, bates=bates_spec, date_text=date_text)
        except Exception as e:
            return QMessageBox.critical(self, APP_NAME, T("ใส่หัว/ท้ายกระดาษไม่สำเร็จ:\n%s") % e)
        self._done(T("ใส่หัว/ท้ายกระดาษแล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))

    def add_background(self):
        if not self.pdf.is_open():
            return self.need_file()
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QColorDialog
        T = self.T
        c = QColorDialog.getColor(QColor("#fff8e1"), self, T("เลือกสีพื้นหลัง"),
                                  QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not c.isValid():
            return
        box = QMessageBox(self)
        box.setWindowTitle(T("สีพื้นหลัง"))
        box.setText(T("ใส่สีพื้นหลังที่หน้าไหน?"))
        cur = box.addButton(T("เฉพาะหน้านี้"), QMessageBox.ButtonRole.AcceptRole)
        every = box.addButton(T("ทุกหน้า"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(T("ยกเลิก"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() not in (cur, every):
            return
        pages = None if box.clickedButton() is every else [self.page_index]
        self.pdf.add_background((c.redF(), c.greenF(), c.blueF()), c.alphaF(), pages)
        self._done(T("ใส่สีพื้นหลังแล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))

    # ---------------- comments ----------------
    def comment_list(self):
        if not self.pdf.is_open():
            return self.need_file()
        T = self.T
        comments = self.pdf.all_comments()
        if not comments:
            return QMessageBox.information(self, APP_NAME, T("ไฟล์นี้ยังไม่มีคอมเมนต์"))

        def goto(pno):
            self.page_index = pno
            self.render_page()

        CommentListDialog(self, T, comments, goto).exec()

    # ---------------- redaction ----------------
    def find_and_redact(self):
        if not self.pdf.is_open():
            return self.need_file()
        T = self.T

        def count(q):
            return sum(len(self.pdf.find_on_page(p, q)) for p in range(self.pdf.page_count))

        dlg = FindRedactDialog(self, T, count)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        query, fill = dlg.values()
        n = self.pdf.redact_text(query, fill)
        self._done(T("ลบข้อมูลถาวรแล้ว %d จุด ✓ (Ctrl+Z ย้อนกลับได้ก่อนบันทึก)") % n)

    def redact_pages_ui(self):
        if not self.pdf.is_open():
            return self.need_file()
        T = self.T
        pages = self._ask_pages(T("ลบทั้งหน้า"))
        if pages is None:
            return
        if not pages:
            return QMessageBox.warning(self, APP_NAME, T("รูปแบบหน้าไม่ถูกต้องหรืออยู่นอกช่วง"))
        if QMessageBox.question(
                self, APP_NAME,
                T("ลบทุกอย่างบน %d หน้าออกถาวร (ข้อความ รูป คอมเมนต์) แล้วปิดด้วยสีดำ?\n"
                  "หน้ายังอยู่ เลขหน้าไม่เลื่อน") % len(pages)) != QMessageBox.StandardButton.Yes:
            return
        self.pdf.redact_pages(pages)
        self._done(T("ลบข้อมูลทั้งหน้าแล้ว %d หน้า ✓ (Ctrl+Z ย้อนกลับได้ก่อนบันทึก)") % len(pages))
