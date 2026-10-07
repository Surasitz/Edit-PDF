# -*- coding: utf-8 -*-
"""WnyEditPDF widgets: dialogs, page view, thumbnail strip and search bar."""

import os
import subprocess
import sys

import fitz

from PyQt6.QtWidgets import (
    QLabel, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QSpinBox, QDialogButtonBox, QPlainTextEdit, QTabWidget, QLineEdit,
    QComboBox, QFileDialog, QMessageBox, QColorDialog, QToolButton,
    QListWidget, QListWidgetItem, QMenu, QCheckBox, QSlider, QGridLayout,
    QRadioButton, QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QAbstractItemView, QApplication
)
from PyQt6.QtGui import (
    QImage, QPainter, QColor, QPen, QFontDatabase, QFont, QPixmap, QIcon,
    QFontMetrics, QDesktopServices
)
from PyQt6.QtCore import Qt, QRect, QPoint, QBuffer, QIODevice, QSize, QUrl

from .config import (
    ADOBE_BLUE, APP_NAME,
    MODE_VIEW, MODE_ADD_TEXT, MODE_EDIT_TEXT, MODE_MOVE_TEXT, MODE_DELETE_TEXT,
    MODE_HIGHLIGHT, MODE_SIGNATURE, MODE_IMAGE, MODE_WHITEOUT,
    MODE_PEN, MODE_COMMENT, MODE_LINK,
)

TEXT_HANDLE_COLOR = QColor("#0f9d58")   # text resize handle (green)
PEN_COLOR = QColor(20, 30, 115)         # pen colour

IMAGE_COLOR = QColor("#f59f00")   # image/signature outline colour
HANDLE_PX = 8                     # resize-handle size (screen pixels)

_family_cache = {}   # font path -> family name already loaded into Qt


def qt_family(path):
    """Load a font file into Qt (once); return the family name for previews."""
    if not path:
        return None
    if path not in _family_cache:
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _family_cache[path] = fams[0] if fams else None
    return _family_cache[path]


def populate_font_combo(combo, fm, selected=None):
    """Fill a QComboBox with fonts, previewing each font in its own row."""
    combo.blockSignals(True)
    combo.clear()
    for i, name in enumerate(fm.names()):
        combo.addItem(name)
        fam = qt_family(fm.path(name))
        if fam:
            combo.setItemData(i, QFont(fam, 12), Qt.ItemDataRole.FontRole)
    if selected and combo.findText(selected) >= 0:
        combo.setCurrentText(selected)
    combo.blockSignals(False)


def symbol_image(kind, px=120):
    """Build a symbol image (transparent PNG) to stamp onto the document.
    kind: cross / check / dot / circle / dash."""
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(PEN_COLOR, px * 0.10, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    m = px * 0.18
    if kind == "cross":
        p.drawLine(int(m), int(m), int(px - m), int(px - m))
        p.drawLine(int(px - m), int(m), int(m), int(px - m))
    elif kind == "check":
        from PyQt6.QtGui import QPolygon
        pts = [QPoint(int(px*0.16), int(px*0.55)),
               QPoint(int(px*0.42), int(px*0.80)),
               QPoint(int(px*0.86), int(px*0.22))]
        p.drawPolyline(QPolygon(pts))
    elif kind == "dot":
        p.setBrush(PEN_COLOR)
        p.setPen(Qt.PenStyle.NoPen)
        r = px * 0.30
        p.drawEllipse(QPoint(px // 2, px // 2), int(r), int(r))
    elif kind == "circle":
        p.drawEllipse(QPoint(px // 2, px // 2), int(px*0.36), int(px*0.36))
    elif kind == "dash":
        p.drawLine(int(m), px // 2, int(px - m), px // 2)
    p.end()
    return qimage_png_bytes(img)


def qimage_png_bytes(img):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def qr_png_bytes(data, px=600):
    """Generate a QR code for `data` and return it as PNG bytes.

    Uses the `qrcode` library only for the module matrix, then paints the matrix
    into a QImage with PyQt - so no Pillow dependency is pulled into the build.
    Returns None if the qrcode library is unavailable."""
    try:
        import qrcode
    except Exception:
        # fall back to the copy vendored inside the app so QR works even when the
        # qrcode package is not pip-installed on the user's machine
        try:
            import os as _os, sys as _sys
            _vendor = _os.path.join(_os.path.dirname(__file__), "vendor")
            if _vendor not in _sys.path:
                _sys.path.insert(0, _vendor)
            import qrcode
        except Exception:
            return None
    qr = qrcode.QRCode(version=None, box_size=1, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    if n == 0:
        return None
    scale = max(1, px // n)
    size = n * scale
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#000000"))
    for r, row in enumerate(matrix):
        for c, on in enumerate(row):
            if on:
                p.drawRect(c * scale, r * scale, scale, scale)
    p.end()
    return qimage_png_bytes(img)


def stamp_text_image(text, fontpath=None, color=(0.80, 0.13, 0.13), px_h=110):
    """Render an official-style text stamp (coloured text inside a rounded
    rectangle border) as PNG bytes. Used for 'สำเนาถูกต้อง', 'ด่วนที่สุด', etc."""
    lines = [ln for ln in text.split("\n") if ln.strip()] or [text]
    qc = QColor(int(color[0] * 255), int(color[1] * 255), int(color[2] * 255))
    fam = qt_family(fontpath) if fontpath else None
    font = QFont(fam) if fam else QFont()
    font.setPixelSize(int(px_h * 0.5))
    font.setBold(True)
    # measure
    probe = QImage(4, 4, QImage.Format.Format_ARGB32)
    fm = QFontMetrics(font, probe)
    tw = max(fm.horizontalAdvance(ln) for ln in lines)
    th = fm.height() * len(lines)
    pad = int(px_h * 0.28)
    W, H = tw + pad * 2, th + pad * 2
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(qc, max(2, px_h // 28))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = int(px_h * 0.12)
    p.drawRoundedRect(pen.width(), pen.width(),
                      W - pen.width() * 2, H - pen.width() * 2, r, r)
    p.setFont(font)
    y = pad + fm.ascent()
    for ln in lines:
        w = fm.horizontalAdvance(ln)
        p.drawText((W - w) // 2, y, ln)
        y += fm.height()
    p.end()
    return qimage_png_bytes(img)


def crop_transparent(img, pad=6):
    """Trim the transparent border of a QImage to its content; None if empty."""
    x0, y0, x1, y1 = img.width(), img.height(), -1, -1
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 0:
                x0 = min(x0, x); y0 = min(y0, y)
                x1 = max(x1, x); y1 = max(y1, y)
    if x1 < 0:
        return None
    return img.copy(max(0, x0 - pad), max(0, y0 - pad),
                    min(img.width() - max(0, x0 - pad), x1 - x0 + pad * 2),
                    min(img.height() - max(0, y0 - pad), y1 - y0 + pad * 2))


# ============================================================
#  thumbnail strip (drag to reorder pages, Acrobat-style)
# ============================================================
class ThumbnailList(QListWidget):
    """PDF thumbnail strip - press and drag a thumbnail up/down to reorder pages.
    Uses fully manual dragging (not Qt's InternalMove, which spams warnings to
    the console); on release it calls main.reorder_pages(src, dst)."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(4)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)  # disable Qt's own drag
        self.setUniformItemSizes(True)
        self._press_row = None
        self._press_pos = None
        self._dragging = False
        self._drop_row = None        # where the page would land (for the indicator)
        # a small floating label that shows "→ page N" while dragging
        self._drag_label = QLabel(self)
        self._drag_label.setStyleSheet(
            "background: #1473e6; color: #ffffff; padding: 3px 8px;"
            " border-radius: 4px; font-weight: 600;")
        self._drag_label.hide()
        # enable the right-click menu on thumbnails
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    def _show_menu(self, pos):
        """Right-click a page thumbnail -> quick menu: delete/insert/rotate/reorder."""
        it = self.itemAt(pos)
        if it is None:
            return
        row = self.row(it)
        self.setCurrentRow(row)
        self.main.jump_page(row + 1)     # jump to that page first
        m = QMenu(self)
        n = self.count()

        act_del = m.addAction("🗑  ลบหน้านี้")
        act_blank = m.addAction("➕  แทรกหน้าว่างหลังหน้านี้")
        m.addSeparator()
        act_rcw = m.addAction("↻  หมุน 90° ตามเข็ม")
        act_rccw = m.addAction("↺  หมุน 90° ทวนเข็ม")
        m.addSeparator()
        act_up = m.addAction("⬆  เลื่อนหน้านี้ขึ้น")
        act_down = m.addAction("⬇  เลื่อนหน้านี้ลง")
        act_top = m.addAction("⏫  ย้ายไปหน้าแรก")
        act_bottom = m.addAction("⏬  ย้ายไปหน้าสุดท้าย")
        act_up.setEnabled(row > 0)
        act_top.setEnabled(row > 0)
        act_down.setEnabled(row < n - 1)
        act_bottom.setEnabled(row < n - 1)
        if n <= 1:
            act_del.setEnabled(False)    # prevent deleting the last remaining page

        chosen = m.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_del:
            self.main.delete_page()
        elif chosen == act_blank:
            self.main.insert_blank_page()
        elif chosen == act_rcw:
            self.main.rotate_page(90)
        elif chosen == act_rccw:
            self.main.rotate_page(-90)
        elif chosen == act_up:
            self.main.reorder_pages(row, row - 1)
        elif chosen == act_down:
            self.main.reorder_pages(row, row + 1)
        elif chosen == act_top:
            self.main.reorder_pages(row, 0)
        elif chosen == act_bottom:
            self.main.reorder_pages(row, n - 1)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            it = self.itemAt(ev.position().toPoint())
            self._press_row = self.row(it) if it is not None else None
            self._press_pos = ev.position().toPoint()
            self._dragging = False
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        # start dragging only after enough movement (so a click isn't a drag)
        if (self._press_row is not None and self._press_pos is not None
                and (ev.position().toPoint() - self._press_pos).manhattanLength() > 8):
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._dragging:
            self._drop_row = self._drop_index(ev.position().toPoint())
            # floating "→ page N" label follows the cursor
            self._drag_label.setText(f"→ หน้า {self._drop_row + 1}")
            self._drag_label.adjustSize()
            pt = ev.position().toPoint()
            self._drag_label.move(min(pt.x() + 12, self.width() - self._drag_label.width() - 4),
                                  pt.y() + 4)
            self._drag_label.show()
            self._drag_label.raise_()
            self.viewport().update()
        super().mouseMoveEvent(ev)

    def _drop_index(self, pos):
        """Which page index the dragged thumbnail would land on right now."""
        it = self.itemAt(pos)
        if it is not None:
            return self.row(it)
        # below/right of the last item -> drop at the end
        return self.count() - 1

    def paintEvent(self, ev):
        super().paintEvent(ev)
        # draw a blue insertion bar at the drop position while dragging
        if self._dragging and self._drop_row is not None:
            it = self.item(self._drop_row)
            if it is not None:
                from PyQt6.QtGui import QPainter, QPen, QColor
                r = self.visualItemRect(it)
                painter = QPainter(self.viewport())
                painter.setPen(QPen(QColor("#1473e6"), 3))
                # a bar across the top of the target thumbnail
                painter.drawLine(r.left() - 2, r.top() - 2,
                                 r.right() + 2, r.top() - 2)
                painter.setBrush(QColor("#1473e6"))
                painter.drawEllipse(r.left() - 6, r.top() - 5, 7, 7)
                painter.end()

    def mouseReleaseEvent(self, ev):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._drag_label.hide()
        self._drop_row = None
        self.viewport().update()
        if self._dragging and self._press_row is not None:
            it = self.itemAt(ev.position().toPoint())
            dst = self.row(it) if it is not None else self.count() - 1
            src = self._press_row
            self._press_row = self._press_pos = None
            self._dragging = False
            if src >= 0 and dst >= 0 and src != dst:
                self.main.reorder_pages(src, dst)
                return
        self._press_row = self._press_pos = None
        self._dragging = False
        super().mouseReleaseEvent(ev)


# ============================================================
#  add/edit text dialog (font + size + colour all in one box)
# ============================================================
class TextEditDialog(QDialog):
    def __init__(self, parent, fm, title, label, text="", fontsize=16,
                 fontname=None, color=None, bold=False, italic=False):
        super().__init__(parent)
        self.fm = fm
        self.color = QColor(color) if color else QColor(20, 20, 20)
        self.setWindowTitle(title)
        self.setMinimumWidth(490)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        lb = QLabel(label)
        lb.setStyleSheet("color: #6b6f76;")
        lay.addWidget(lb)

        self.edit = QPlainTextEdit()
        self.edit.setPlainText(text)
        self.edit.setMinimumHeight(90)
        lay.addWidget(self.edit)

        row = QHBoxLayout()
        row.addWidget(QLabel("ฟอนต์"))
        self.font_combo = QComboBox()
        self.font_combo.setMinimumWidth(180)
        populate_font_combo(self.font_combo, fm, fontname)
        self.font_combo.addItem("➕ เพิ่มไฟล์ฟอนต์ (.ttf)...")
        self.font_combo.currentTextChanged.connect(self._font_changed)
        row.addWidget(self.font_combo, 1)
        row.addWidget(QLabel("ขนาด"))
        self.spin = QSpinBox()
        self.spin.setRange(4, 200)
        self.spin.setValue(int(round(fontsize)))
        row.addWidget(self.spin)
        # bold / italic toggle buttons
        self.btn_bold = QToolButton()
        self.btn_bold.setText("B")
        self.btn_bold.setToolTip("ตัวหนา")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setChecked(bool(bold))
        self.btn_bold.setStyleSheet("QToolButton { font-weight: 700; padding: 3px 9px; }"
                                    "QToolButton:checked { background: #1473e6; color: #fff; }")
        self.btn_bold.clicked.connect(self._apply_preview)
        row.addWidget(self.btn_bold)
        self.btn_italic = QToolButton()
        self.btn_italic.setText("I")
        self.btn_italic.setToolTip("ตัวเอียง")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setChecked(bool(italic))
        self.btn_italic.setStyleSheet("QToolButton { font-style: italic; padding: 3px 11px; }"
                                      "QToolButton:checked { background: #1473e6; color: #fff; }")
        self.btn_italic.clicked.connect(self._apply_preview)
        row.addWidget(self.btn_italic)
        self.btn_color = QToolButton()
        self.btn_color.setToolTip("สีตัวอักษร")
        self.btn_color.clicked.connect(self._pick_color)
        row.addWidget(self.btn_color)
        lay.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("ตกลง")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._apply_color_button()
        self._apply_preview()
        self.edit.setFocus()

    def _font_changed(self, name):
        if name.startswith("➕"):
            path, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์ฟอนต์", "",
                                                  "Fonts (*.ttf *.otf *.ttc)")
            self.font_combo.blockSignals(True)
            if path:
                disp = self.fm.add(path)
                if self.font_combo.findText(disp) < 0:
                    self.font_combo.insertItem(self.font_combo.count() - 1, disp)
                self.font_combo.setCurrentText(disp)
            else:
                self.font_combo.setCurrentIndex(0)
            self.font_combo.blockSignals(False)
        self._apply_preview()

    def _pick_color(self):
        c = QColorDialog.getColor(self.color, self, "เลือกสีตัวอักษร")
        if c.isValid():
            self.color = c
            self._apply_color_button()
            self._apply_preview()

    def _apply_color_button(self):
        self.btn_color.setText("■")
        self.btn_color.setStyleSheet(
            f"QToolButton {{ color: {self.color.name()}; font-size: 18px;"
            f" border: 1px solid #c9ccd1; border-radius: 5px; padding: 3px 9px; }}")

    def _apply_preview(self):
        """Preview box shows the chosen font, colour, weight and slant."""
        fam = qt_family(self.fm.path(self.font_combo.currentText()))
        f = QFont(fam, 15) if fam else QFont()
        f.setPointSize(15)
        f.setBold(self.btn_bold.isChecked())
        f.setItalic(self.btn_italic.isChecked())
        self.edit.setFont(f)
        self.edit.setStyleSheet(f"font-size: 15px; color: {self.color.name()};")

    def values(self):
        """Return (text, size, font_name, QColor, bold, italic)."""
        return (self.edit.toPlainText(), self.spin.value(),
                self.font_combo.currentText(), self.color,
                self.btn_bold.isChecked(), self.btn_italic.isChecked())


# ============================================================
#  comment dialog (sticky note)
# ============================================================
class SearchBar(QWidget):
    """Floating find/replace bar (stays open) above the document.
    The prev/next buttons step through matches one at a time and highlight them.
    Calls main.search_goto(direction) / search_replace_all() / search_close()."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.setObjectName("searchBar")
        self.setStyleSheet(
            "#searchBar { background: #ffffff; border: 1px solid #c9ccd1;"
            " border-radius: 8px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(6)

        self.edit_find = QLineEdit()
        self.edit_find.setPlaceholderText("ค้นหา...")
        self.edit_find.setFixedWidth(180)
        self.edit_find.textChanged.connect(self._on_text_changed)
        self.edit_find.returnPressed.connect(lambda: self.main.search_goto(1))
        lay.addWidget(self.edit_find)

        self.lbl_count = QLabel("0/0")
        self.lbl_count.setStyleSheet("color: #6b6f76; min-width: 44px;")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_count)

        btn_prev = QToolButton(); btn_prev.setText("◀")
        btn_prev.setToolTip("คำก่อนหน้า")
        btn_prev.clicked.connect(lambda: self.main.search_goto(-1))
        lay.addWidget(btn_prev)
        btn_next = QToolButton(); btn_next.setText("▶")
        btn_next.setToolTip("คำถัดไป")
        btn_next.clicked.connect(lambda: self.main.search_goto(1))
        lay.addWidget(btn_next)

        sep = QLabel("│"); sep.setStyleSheet("color: #c9ccd1;")
        lay.addWidget(sep)

        self.edit_repl = QLineEdit()
        self.edit_repl.setPlaceholderText("แทนที่ด้วย... (เว้นว่าง = ลบ)")
        self.edit_repl.setFixedWidth(180)
        lay.addWidget(self.edit_repl)
        btn_all = QToolButton(); btn_all.setText("แทนที่ทั้งหมด")
        btn_all.clicked.connect(lambda: self.main.search_replace_all())
        lay.addWidget(btn_all)

        btn_close = QToolButton(); btn_close.setText("✕")
        btn_close.setToolTip("ปิด (Esc)")
        btn_close.clicked.connect(lambda: self.main.search_close())
        lay.addWidget(btn_close)
        self.adjustSize()

    def _on_text_changed(self, _):
        self.main.search_update()

    def find(self):
        return self.edit_find.text()

    def repl(self):
        return self.edit_repl.text()

    def set_count(self, cur, total):
        self.lbl_count.setText(f"{cur}/{total}")

    def focus_find(self, preset=""):
        if preset:
            self.edit_find.setText(preset)
        self.edit_find.setFocus()
        self.edit_find.selectAll()


class FindReplaceDialog(QDialog):
    """Find & replace across the whole file.
    result: None = cancelled, ("find", term),
            ("replace_one", term, new), ("replace_all", term, new)."""

    def __init__(self, parent, find_text=""):
        super().__init__(parent)
        self.setWindowTitle("🔍 ค้นหา / แทนที่")
        self.setMinimumWidth(430)
        self.result = None
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("ค้นหา:"))
        self.edit_find = QLineEdit(find_text)
        self.edit_find.setPlaceholderText("คำที่ต้องการค้นหา")
        r1.addWidget(self.edit_find, 1)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("แทนที่ด้วย:"))
        self.edit_repl = QLineEdit()
        self.edit_repl.setPlaceholderText("เว้นว่าง = ลบคำที่พบ")
        r2.addWidget(self.edit_repl, 1)
        lay.addLayout(r2)

        note = QLabel("แทนที่จะพยายามคงฟอนต์/ขนาด/สีเดิมของแต่ละจุด "
                      "และทำทั้งไฟล์ (Ctrl+Z ย้อนกลับได้)")
        note.setStyleSheet("color: #9a9da3;")
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QHBoxLayout()
        btn_find = QPushButton("🔎 หาถัดไป")
        btn_find.clicked.connect(lambda: self._done("find"))
        row.addWidget(btn_find)
        row.addStretch()
        btn_all = QPushButton("แทนที่ทั้งหมด")
        btn_all.clicked.connect(lambda: self._done("replace_all"))
        row.addWidget(btn_all)
        btn_cancel = QPushButton("ปิด")
        btn_cancel.setProperty("flat", True)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        lay.addLayout(row)
        self.edit_find.setFocus()

    def _done(self, action):
        find = self.edit_find.text()
        if not find:
            QMessageBox.information(self, APP_NAME, "กรุณาพิมพ์คำที่จะค้นหาก่อน")
            return
        self.result = (action, find, self.edit_repl.text())
        self.accept()


class WordExportDialog(QDialog):
    """Pick how a PDF should be turned into a Word file.

    The two modes are a genuine trade-off rather than a quality setting, so the
    user has to see both: flowing paragraphs are what people expect a Word file
    to be, so they are the default; frames reproduce the page exactly but leave
    one box per line to retype in. Either way the words themselves are
    identical."""

    def __init__(self, parent=None, tr=None, page_count=1, cur_page=1):
        super().__init__(parent)
        T = tr or (lambda s: s)
        self._T = T
        self.setWindowTitle(T("แปลง PDF เป็น Word"))
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        head = QLabel(T("เลือกรูปแบบไฟล์ Word ที่ต้องการ"))
        head.setStyleSheet("font-weight: 600; font-size: 14px;")
        lay.addWidget(head)

        self.rb_flow = QRadioButton(
            T("พิมพ์แก้ต่อได้ (ข้อความไหลต่อกันแบบ Word ปกติ) (แนะนำ)"))
        self.rb_flow.setChecked(True)
        lay.addWidget(self.rb_flow)
        hint2 = QLabel(T("ได้ย่อหน้าจริงแบบที่พิมพ์เองใน Word ข้อความไหลข้ามหน้าได้\n"
                         "เลขหน้าย้ายไปอยู่หัวกระดาษ — หน้าหลายคอลัมน์อาจเลื่อนได้"))
        hint2.setStyleSheet("color: #6b7280; margin-left: 22px;")
        lay.addWidget(hint2)

        self.chk_tables = QCheckBox(T("แปลงตารางที่มีเส้นให้เป็นตารางของ Word"))
        self.chk_tables.setChecked(True)
        self.chk_tables.setStyleSheet("margin-left: 22px;")
        lay.addWidget(self.chk_tables)
        self.rb_flow.toggled.connect(self.chk_tables.setEnabled)

        self.rb_layout = QRadioButton(T("ล็อกตำแหน่งเหมือนต้นฉบับเป๊ะ"))
        lay.addWidget(self.rb_layout)
        hint1 = QLabel(T("ทุกบรรทัดถูกล็อกไว้ในกรอบตรงตำแหน่งเดิม แก้ได้ทีละบรรทัด\n"
                         "เหมาะกับแบบฟอร์ม ใบเสร็จ ที่ต้องเหมือนต้นฉบับ ไม่ได้จะพิมพ์ต่อ"))
        hint1.setStyleSheet("color: #6b7280; margin-left: 22px;")
        lay.addWidget(hint1)

        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel(T("หน้าที่จะแปลง:")))
        self.pages = QLineEdit()
        self.pages.setPlaceholderText(
            T("เว้นว่าง = ทั้งไฟล์ (%d หน้า) — หรือระบุ เช่น 1-3,5") % page_count)
        row.addWidget(self.pages, 1)
        lay.addLayout(row)

        note = QLabel(T("ฝังฟอนต์ไทยไว้ในไฟล์ Word เปิดเครื่องอื่นตัวอักษรไม่เพี้ยน\n"
                        "หน้าที่เป็นรูปสแกน จะถูกใส่เป็นรูปภาพให้แทน"))
        note.setStyleSheet("color: #6b7280;")
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(T("แปลงเลย"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        """(layout_mode, page_spec_text, want_tables)"""
        return (self.rb_layout.isChecked(), self.pages.text().strip(),
                self.chk_tables.isChecked())


class CompressDialog(QDialog):
    """Shrink PDF files - a whole pile of them in one go.

    Batch is the point, not a bonus: nobody compresses one file. They have a
    folder of scans that a hospital mail server bounces at 10 MB, and they want
    all of them fixed before lunch. So the dialog is a work list - drop files
    on it, pick how hard to squeeze once, and watch each row report what it
    saved. Files are processed one after another (PyMuPDF is happiest on one
    document at a time) but as a single unattended run.

    Nothing is ever written over an input file: each result goes to a new
    ``*_compressed.pdf`` next to the original, or to a folder the user picks.
    """

    def __init__(self, parent=None, tr=None, files=None, names=None):
        super().__init__(parent)
        T = tr or (lambda s: s)
        self._T = T
        self._busy = False
        self._cancel = False
        self.paths = []          # row index -> source path
        self.results = []        # stats dicts, filled in as the run goes
        self.out_files = []      # what we actually wrote
        self.row_out = {}        # table row -> file written for it
        # source path -> the path the result is NAMED after. Used for the
        # document open in the editor with unsaved edits: we compress a temp
        # copy of what is on screen, but the user expects
        # "<their file>_compressed.pdf" next to their file, not a temp name.
        self.name_for = dict(names or {})

        self.setWindowTitle(T("บีบอัด PDF (ลดขนาดไฟล์)"))
        self.setMinimumSize(760, 600)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setSpacing(9)

        head = QLabel(T("ลดขนาดไฟล์ PDF ได้ทีละหลายไฟล์"))
        head.setStyleSheet("font-weight: 600; font-size: 14px;")
        lay.addWidget(head)
        sub = QLabel(T("① ลากไฟล์ PDF มาวาง หรือกด 'เพิ่มไฟล์'   "
                       "② เลือกระดับ   ③ กด 'บีบอัดและบันทึก'\n"
                       "โปรแกรมจะบันทึกเป็นไฟล์ใหม่ให้ทันที ไม่ต้องกดบันทึกเองอีก "
                       "— ไฟล์ต้นฉบับไม่ถูกแก้ และไม่มีการอัปโหลดไฟล์ออกไปไหน"))
        sub.setStyleSheet("color: #6b7280;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # ---------------- the work list ----------------
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            T("ไฟล์"), T("ขนาดเดิม"), T("ขนาดใหม่"), T("ผลลัพธ์"),
            T("บันทึกเป็น")])
        self.table.setToolTip(
            T("ดับเบิลคลิกแถวที่เสร็จแล้ว เพื่อเปิดโฟลเดอร์ที่บันทึกไฟล์ไว้"))
        self.table.cellDoubleClicked.connect(self._show_output)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAcceptDrops(False)          # let drops reach the dialog
        self.table.viewport().setAcceptDrops(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btn_add = QPushButton(T("➕ เพิ่มไฟล์..."))
        self.btn_add.clicked.connect(self._browse_files)
        self.btn_del = QPushButton(T("เอาออก"))
        self.btn_del.setProperty("flat", True)
        self.btn_del.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton(T("ล้างรายการ"))
        self.btn_clear.setProperty("flat", True)
        self.btn_clear.clicked.connect(self._clear)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_del)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        self.lbl_total = QLabel()
        self.lbl_total.setStyleSheet("color: #6b7280;")
        row.addWidget(self.lbl_total)
        lay.addLayout(row)

        # ---------------- how hard to squeeze ----------------
        lay.addWidget(_hline())
        # the hint label exists before the radios are wired: setChecked() below
        # fires toggled straight away, and a slot that raises takes the whole
        # application down with it
        self.hint = QLabel()
        self.hint.setStyleSheet("color: #6b7280; margin-left: 4px;")
        self.hint.setWordWrap(True)

        lvl_row = QHBoxLayout()
        lvl_row.addWidget(QLabel(T("ระดับการบีบอัด:")))
        self.levels = {}
        for key, label in (("light", T("คุณภาพสูง")),
                           ("balanced", T("สมดุล (แนะนำ)")),
                           ("max", T("เล็กที่สุด"))):
            rb = QRadioButton(label)
            rb.toggled.connect(self._show_hint)
            lvl_row.addWidget(rb)
            self.levels[key] = rb
        self.levels["balanced"].setChecked(True)
        lvl_row.addStretch(1)
        lay.addLayout(lvl_row)
        lay.addWidget(self.hint)

        self.chk_gray = QCheckBox(T("แปลงรูปในไฟล์เป็นขาวดำ (เอกสารสแกนขาวดำจะเล็กลงอีกมาก)"))
        lay.addWidget(self.chk_gray)
        self.chk_fonts = QCheckBox(T("ตัดฟอนต์ที่ฝังมาให้เหลือเฉพาะตัวอักษรที่ใช้จริง"))
        self.chk_fonts.setChecked(True)
        self.chk_fonts.setToolTip(
            T("ช่วยได้มากกับหนังสือราชการที่ฝังฟอนต์ไทยมาทั้งชุด\n"
              "ถ้าจะเอาไฟล์ผลลัพธ์ไปพิมพ์ข้อความเพิ่มทีหลัง แนะนำให้เอาเครื่องหมายออก"))
        lay.addWidget(self.chk_fonts)

        # ---------------- where the results go ----------------
        lay.addWidget(_hline())
        where = QLabel(T("บันทึกไฟล์ที่บีบอัดแล้วไว้ที่:"))
        where.setStyleSheet("font-weight: 600;")
        lay.addWidget(where)
        out_row = QHBoxLayout()
        self.rb_same = QRadioButton(T("บันทึกไว้โฟลเดอร์เดียวกับไฟล์ต้นฉบับ"))
        self.rb_same.setChecked(True)
        self.rb_other = QRadioButton(T("โฟลเดอร์อื่น:"))
        self.out_dir = QLineEdit()
        self.out_dir.setReadOnly(True)
        self.out_dir.setEnabled(False)
        self.btn_dir = QPushButton(T("เลือก..."))
        self.btn_dir.setProperty("flat", True)
        self.btn_dir.setEnabled(False)
        self.btn_dir.clicked.connect(self._pick_dir)
        self.rb_other.toggled.connect(self.out_dir.setEnabled)
        self.rb_other.toggled.connect(self.btn_dir.setEnabled)
        self.rb_other.toggled.connect(
            lambda on: on and not self.out_dir.text() and self._pick_dir())
        out_row.addWidget(self.rb_same)
        out_row.addWidget(self.rb_other)
        out_row.addWidget(self.out_dir, 1)
        out_row.addWidget(self.btn_dir)
        lay.addLayout(out_row)
        # live preview of the exact file name that will be written, so the
        # user knows where to look BEFORE pressing the button
        self.lbl_dest = QLabel()
        self.lbl_dest.setStyleSheet("color: #1473e6; margin-left: 4px;")
        self.lbl_dest.setWordWrap(True)
        self.lbl_dest.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.lbl_dest)
        self.rb_same.toggled.connect(self._update_dest)
        self.out_dir.textChanged.connect(self._update_dest)

        # ---------------- progress + buttons ----------------
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)
        self.lbl_status = QLabel(" ")
        self.lbl_status.setStyleSheet("color: #6b7280;")
        lay.addWidget(self.lbl_status)

        bb = QHBoxLayout()
        self.btn_open = QPushButton(T("📂 เปิดโฟลเดอร์ผลลัพธ์"))
        self.btn_open.setProperty("flat", True)
        self.btn_open.setVisible(False)
        self.btn_open.clicked.connect(self._open_folder)
        bb.addWidget(self.btn_open)
        bb.addStretch(1)
        self.btn_close = QPushButton(T("ปิด"))
        self.btn_close.setProperty("flat", True)
        self.btn_close.clicked.connect(self.close)
        self.btn_go = QPushButton(T("บีบอัดและบันทึก"))
        self.btn_go.clicked.connect(self._go)
        bb.addWidget(self.btn_close)
        bb.addWidget(self.btn_go)
        lay.addLayout(bb)

        self._show_hint()
        self.add_files(files or [])

    # ------------------------------------------------------------- the list
    def add_files(self, paths):
        """Add PDFs to the work list, ignoring duplicates and non-PDFs."""
        from .compress import human_size
        have = {os.path.normcase(os.path.abspath(p)) for p in self.paths}
        added = 0
        for p in paths:
            if not p or not p.lower().endswith(".pdf") or not os.path.isfile(p):
                continue
            key = os.path.normcase(os.path.abspath(p))
            if key in have:
                continue
            have.add(key)
            r = self.table.rowCount()
            self.table.insertRow(r)
            shown = self.name_for.get(p, p)
            label = os.path.basename(shown)
            if shown != p:
                label += self._T("  (ฉบับที่แก้ล่าสุด)")
            name = QTableWidgetItem(label)
            name.setToolTip(shown)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(
                human_size(os.path.getsize(p))))
            self.table.setItem(r, 2, QTableWidgetItem("-"))
            self.table.setItem(r, 3, QTableWidgetItem(self._T("รอคิว")))
            self.table.setItem(r, 4, QTableWidgetItem(""))
            self.paths.append(p)
            added += 1
        if added:
            self._reset_results()
        self._refresh_total()
        return added

    def _browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._T("เลือกไฟล์ PDF (เลือกได้หลายไฟล์)"), "", "PDF (*.pdf)")
        self.add_files(paths)

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)
            del self.paths[r]
        if rows:
            # row numbers shifted - the per-row output map no longer lines up
            self.row_out = {}
        self._refresh_total()

    def _clear(self):
        self.table.setRowCount(0)
        self.paths = []
        self.row_out = {}
        self._refresh_total()

    def _reset_results(self):
        """A new run starts from a clean slate of result cells."""
        self.results = []
        self.out_files = []
        self.row_out = {}
        self.btn_open.setVisible(False)
        self.bar.setValue(0)
        for r in range(self.table.rowCount()):
            self.table.item(r, 2).setText("-")
            self._set_result(r, self._T("รอคิว"), "#6b7280")
            self.table.setItem(r, 4, QTableWidgetItem(""))

    def _refresh_total(self):
        from .compress import human_size
        total = sum(os.path.getsize(p) for p in self.paths
                    if os.path.exists(p))
        self.lbl_total.setText(
            self._T("รวม %d ไฟล์ • %s") % (len(self.paths), human_size(total)))
        self.btn_go.setEnabled(bool(self.paths))
        self._update_dest()

    def _update_dest(self, *_):
        """Tell the user exactly where the result will be saved."""
        from .compress import output_path
        T = self._T
        if not hasattr(self, "lbl_dest"):
            return
        if self.rb_other.isChecked() and not self.out_dir.text().strip():
            self.lbl_dest.setText(T("⚠ ยังไม่ได้เลือกโฟลเดอร์ปลายทาง"))
            return
        if not self.paths:
            self.lbl_dest.setText(T("ไฟล์ใหม่จะชื่อ  ชื่อเดิม_compressed.pdf"))
            return
        first = self.name_for.get(self.paths[0], self.paths[0])
        dst = output_path(first, self._target_dir())
        more = (T("  (ไฟล์อื่นตั้งชื่อแบบเดียวกัน)")
                if len(self.paths) > 1 else "")
        self.lbl_dest.setText(T("➜ จะบันทึกเป็น: %s") % dst + more)

    def _set_result(self, row, text, color):
        it = QTableWidgetItem(text)
        it.setForeground(QColor(color))
        self.table.setItem(row, 3, it)

    # ------------------------------------------------------------- options
    def _level(self):
        for key, rb in self.levels.items():
            if rb.isChecked():
                return key
        return "balanced"

    def _show_hint(self):
        T = self._T
        self.hint.setText({
            "light": T("ภาพยังคมเกือบเท่าเดิม เหมาะกับงานที่ต้องพิมพ์ออกมาชัดๆ "
                       "(ลดขนาดได้น้อยกว่าแบบอื่น)"),
            "balanced": T("ลดขนาดได้มาก ภาพยังอ่านง่ายทั้งบนจอและตอนพิมพ์ "
                          "— เหมาะกับเอกสารสแกนทั่วไป"),
            "max": T("ไฟล์เล็กที่สุด เหมาะกับการส่งอีเมลหรืออัปโหลดเข้าระบบ "
                     "ที่จำกัดขนาดไฟล์ (ภาพจะหยาบลงบ้าง)"),
        }[self._level()])

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, self._T("เลือกโฟลเดอร์ปลายทาง"), self.out_dir.text() or "")
        if d:
            self.out_dir.setText(d)
        elif not self.out_dir.text():
            self.rb_same.setChecked(True)

    def _target_dir(self):
        if self.rb_other.isChecked() and self.out_dir.text().strip():
            return self.out_dir.text().strip()
        return None

    # ------------------------------------------------------------ drag/drop
    def dragEnterEvent(self, e):
        if self._busy:
            return
        md = e.mimeData()
        if md.hasUrls() and any(u.toLocalFile().lower().endswith(".pdf")
                                for u in md.urls()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        if self._busy:
            return
        self.add_files([u.toLocalFile() for u in e.mimeData().urls()])
        e.acceptProposedAction()

    # ---------------------------------------------------------------- run
    def _go(self):
        if self._busy:                      # the button doubles as Stop
            self._cancel = True
            self.lbl_status.setText(self._T("กำลังหยุด..."))
            return
        if not self.paths:
            return
        if self.rb_other.isChecked() and not self.out_dir.text().strip():
            self._pick_dir()
            if not self._target_dir():
                return
        out_dir = self._target_dir()
        if out_dir and not os.path.isdir(out_dir):
            QMessageBox.warning(self, self._T("บีบอัด PDF"),
                                self._T("ไม่พบโฟลเดอร์ปลายทาง:\n%s") % out_dir)
            return
        self._run()

    def _set_busy(self, busy):
        self._busy = busy
        self._cancel = False
        for w in (self.btn_add, self.btn_del, self.btn_clear, self.table,
                  self.chk_gray, self.chk_fonts, self.rb_same, self.rb_other,
                  self.btn_close):
            w.setEnabled(not busy)
        for rb in self.levels.values():
            rb.setEnabled(not busy)
        self.btn_dir.setEnabled(not busy and self.rb_other.isChecked())
        self.btn_go.setText(self._T("หยุด") if busy
                            else self._T("บีบอัดและบันทึก"))

    def _run(self):
        from . import compress as cz
        T = self._T
        self._reset_results()
        self._set_busy(True)
        out_dir = self._target_dir()
        level, gray = self._level(), self.chk_gray.isChecked()
        fonts = self.chk_fonts.isChecked()
        n = len(self.paths)
        before_all = after_all = 0

        for row, src in enumerate(list(self.paths)):
            if self._cancel:
                break
            self.table.selectRow(row)
            self._set_result(row, T("กำลังบีบอัด..."), "#1473e6")
            self.lbl_status.setText(
                T("(%d/%d) %s") % (row + 1, n, os.path.basename(src)))
            QApplication.processEvents()

            def tick(done, total, row=row, n=n):
                frac = (row + (done / total if total else 1)) / n
                self.bar.setValue(int(frac * 1000))
                QApplication.processEvents()
                return not self._cancel

            if not os.path.isfile(src):
                self._set_result(row, T("ไม่พบไฟล์ (ถูกย้าย/ลบ?)"), "#d93025")
                continue
            try:
                dst = cz.output_path(self.name_for.get(src, src), out_dir)
                st = cz.compress_file(src, dst, level=level, grayscale=gray,
                                      subset_fonts=fonts, progress=tick)
            except cz.CompressCancelled:
                self._set_result(row, T("ยกเลิกแล้ว"), "#6b7280")
                break
            except Exception as e:
                err = str(e)
                if "locked" in err:
                    msg = T("ไฟล์มีรหัสผ่าน")
                elif isinstance(e, PermissionError) or "ermission" in err:
                    msg = T("บันทึกไม่ได้ (โฟลเดอร์ห้ามเขียน หรือไฟล์เปิดค้างอยู่)")
                else:
                    msg = T("ไม่สำเร็จ")
                self._set_result(row, msg, "#d93025")
                self.table.item(row, 3).setToolTip(err)
                continue

            self.results.append(st)
            self.out_files.append(dst)
            self.row_out[row] = dst
            out_item = QTableWidgetItem(os.path.basename(dst))
            out_item.setToolTip(dst)
            self.table.setItem(row, 4, out_item)
            before_all += st["before"]
            after_all += st["after"]
            self.table.item(row, 2).setText(cz.human_size(st["after"]))
            if st["unchanged"]:
                self._set_result(row, T("เล็กที่สุดแล้ว (บันทึกสำเนาเดิมให้)"),
                                 "#6b7280")
            else:
                self._set_result(row, T("ลดลง %.0f%%") % st["percent"],
                                 "#0f9d58")

        self.bar.setValue(1000 if not self._cancel else self.bar.value())
        self._set_busy(False)

        done = len(self.results)
        if not done:
            self.lbl_status.setText(T("ยังไม่ได้บีบอัดไฟล์ใด"))
            return
        saved = before_all - after_all
        pct = saved * 100.0 / before_all if before_all else 0
        summary = (T("เสร็จแล้ว %d ไฟล์ • จาก %s เหลือ %s (ประหยัด %s / %.0f%%)")
                   % (done, cz.human_size(before_all), cz.human_size(after_all),
                      cz.human_size(saved), pct))
        self.lbl_status.setText(summary)
        self.btn_open.setVisible(True)

        # say plainly that the files are ALREADY saved, and where
        folders = sorted({os.path.dirname(f) for f in self.out_files})
        names = [os.path.basename(f) for f in self.out_files[:6]]
        if len(self.out_files) > 6:
            names.append("…")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(T("บีบอัดเสร็จแล้ว"))
        box.setText(summary + "\n\n"
                    + T("✓ บันทึกไฟล์ใหม่เรียบร้อยแล้ว ไม่ต้องกดบันทึกอีก"))
        box.setInformativeText(T("ไฟล์อยู่ที่:") + "\n" + "\n".join(folders)
                               + "\n\n" + "\n".join(names))
        open_btn = box.addButton(T("📂 เปิดโฟลเดอร์"),
                                 QMessageBox.ButtonRole.ActionRole)
        box.addButton(T("ตกลง"), QMessageBox.ButtonRole.AcceptRole)
        if not getattr(self, "quiet", False):
            box.exec()
            if box.clickedButton() is open_btn:
                self._open_folder()

    def _reveal(self, path):
        """Open the folder holding `path`, with the file selected on Windows."""
        if sys.platform.startswith("win") and os.path.isfile(path):
            try:
                subprocess.Popen(["explorer", "/select,",
                                  os.path.normpath(path)])
                return
            except Exception:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _open_folder(self):
        if self.out_files:
            self._reveal(self.out_files[-1])

    def _show_output(self, row, _col):
        path = self.row_out.get(row)
        if path and os.path.exists(path):
            self._reveal(path)

    def reject(self):
        """Esc: QDialog.reject() bypasses closeEvent and would end exec()
        while a file is still being written. Stop the run instead."""
        if self._busy:
            self._cancel = True
            self.lbl_status.setText(self._T("กำลังหยุด..."))
            return
        super().reject()

    def closeEvent(self, e):
        """Never walk out mid-file: stop the run first, then close."""
        if self._busy:
            self._cancel = True
            e.ignore()
            return
        e.accept()


def _hline():
    line = QLabel()
    line.setFixedHeight(1)
    line.setStyleSheet("background: #e1e3e6;")
    return line


class ScanEnhanceDialog(QDialog):
    """Sliders to brighten / sharpen the contrast of a scanned page and to
    straighten it if the paper was fed in crooked."""

    def __init__(self, parent=None, tr=None):
        super().__init__(parent)
        T = tr or (lambda s: s)
        self.setWindowTitle(T("ปรับแต่งรูปสแกน"))
        self.setMinimumWidth(430)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            T("ปรับเอกสารที่สแกนมามืดหรือเอียง\n"
              "(ใช้กับหน้าที่เป็นรูปสแกนเท่านั้น)")))

        grid = QGridLayout()
        self.sliders = {}
        rows = [
            ("brightness", T("ความสว่าง"), -100, 100, 0),
            ("contrast", T("ความคมชัด"), -100, 100, 0),
            ("angle", T("แก้เอียง (องศา)"), -100, 100, 0),   # /10 -> -10.0..10.0
        ]
        for r, (key, label, lo, hi, init) in enumerate(rows):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            s.setValue(init)
            val = QLabel("0")
            val.setMinimumWidth(44)

            def show(v, key=key, val=val):
                val.setText(f"{v / 10:.1f}°" if key == "angle" else str(v))

            s.valueChanged.connect(show)
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(s, r, 1)
            grid.addWidget(val, r, 2)
            self.sliders[key] = s
        lay.addLayout(grid)

        hint = QLabel(T("เคล็ดลับ: เอกสารมืด → เพิ่มความสว่าง +30 และความคมชัด +25\n"
                        "เอกสารเอียง → ปรับแก้เอียงทีละ 0.5°"))
        hint.setStyleSheet("color: #6b7280;")
        lay.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        """(brightness, contrast, angle_degrees)"""
        return (self.sliders["brightness"].value(),
                self.sliders["contrast"].value(),
                self.sliders["angle"].value() / 10.0)


class CommentDialog(QDialog):
    """Create/read/edit a comment - self.action = "save" | "delete" | None."""

    def __init__(self, parent, text="", author="", allow_delete=False):
        super().__init__(parent)
        self.setWindowTitle("💬 คอมเมนต์" + (f" — {author}" if author else ""))
        self.setMinimumWidth(380)
        self.action = None
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lb = QLabel("ข้อความคอมเมนต์ (จะเห็นในโปรแกรมอ่าน PDF ทั่วไปด้วย):")
        lb.setStyleSheet("color: #6b6f76;")
        lay.addWidget(lb)
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(text)
        self.edit.setMinimumHeight(100)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        if allow_delete:
            btn_del = QPushButton("🗑 ลบคอมเมนต์")
            btn_del.setStyleSheet(
                "QPushButton { background: #e5484d; } QPushButton:hover { background: #f06266; }")
            btn_del.clicked.connect(self._delete)
            row.addWidget(btn_del)
        row.addStretch()
        btn_cancel = QPushButton("ยกเลิก")
        btn_cancel.setProperty("flat", True)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        btn_ok = QPushButton("บันทึก")
        btn_ok.clicked.connect(self._save)
        row.addWidget(btn_ok)
        lay.addLayout(row)
        self.edit.setFocus()

    def _save(self):
        self.action = "save"
        self.accept()

    def _delete(self):
        self.action = "delete"
        self.accept()

    def text(self):
        return self.edit.toPlainText().strip()


# ============================================================
#  signature drawing canvas
# ============================================================
class SignatureCanvas(QWidget):
    def __init__(self, w=540, h=200):
        super().__init__()
        self.setFixedSize(w, h)
        self.image = QImage(w, h, QImage.Format.Format_ARGB32)
        self.image.fill(Qt.GlobalColor.transparent)
        self.last = None
        self.pen_width = 3
        self.pen_color = QColor(15, 15, 20)   # default black (choosable)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_color(self, qcolor):
        self.pen_color = QColor(qcolor)

    def clear(self):
        self.image.fill(Qt.GlobalColor.transparent)
        self.update()

    def mousePressEvent(self, ev):
        self.last = ev.position().toPoint()

    def mouseMoveEvent(self, ev):
        if self.last is not None:
            p = QPainter(self.image)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(self.pen_color, self.pen_width,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            cur = ev.position().toPoint()
            p.drawLine(self.last, cur)
            p.end()
            self.last = cur
            self.update()

    def mouseReleaseEvent(self, ev):
        self.last = None

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        p.setPen(QPen(QColor("#c9ccd1"), 1, Qt.PenStyle.DashLine))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.setPen(QPen(QColor("#e8eaee"), 1))
        p.drawLine(20, self.height() - 42, self.width() - 20, self.height() - 42)
        p.drawImage(0, 0, self.image)
        p.end()

    def png_bytes(self):
        crop = crop_transparent(self.image)
        return qimage_png_bytes(crop) if crop else None


# ============================================================
#  signature dialog: gallery / draw / import / type
# ============================================================
class SignatureDialog(QDialog):
    def __init__(self, parent, font_manager, last_png=None, saved=None):
        super().__init__(parent)
        self.fm = font_manager
        self.last_png = last_png
        self.saved = saved or []       # saved signatures [bytes, ...]
        self.setWindowTitle("เพิ่มลายเซ็น")
        self.result_png = None
        self.result_width = 150
        self.result_save = False       # whether MainWindow should save the new signature
        self.deleted_saved = []        # gallery indices the user deleted

        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        # ---------- tab 0: signature gallery (pick a saved one) ----------
        self.has_gallery = bool(self.saved)
        if self.has_gallery:
            tab0 = QWidget(objectName="tabPage")
            t0 = QVBoxLayout(tab0)
            t0.addWidget(QLabel("เลือกลายเซ็นที่บันทึกไว้ (ดับเบิลคลิกเพื่อใช้ทันที "
                                "/ ปุ่มขวาล่างเพื่อลบออกจากคลัง)"))
            self.gallery = QListWidget()
            self.gallery.setViewMode(QListWidget.ViewMode.IconMode)
            self.gallery.setIconSize(QSize(150, 70))
            self.gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.gallery.setSpacing(8)
            self.gallery.setMovement(QListWidget.Movement.Static)
            for i, png in enumerate(self.saved):
                pm = QPixmap(); pm.loadFromData(png)
                it = QListWidgetItem(QIcon(pm), f"#{i+1}")
                it.setData(Qt.ItemDataRole.UserRole, i)
                self.gallery.addItem(it)
            self.gallery.itemDoubleClicked.connect(lambda _: self._use_gallery())
            t0.addWidget(self.gallery)
            grow = QHBoxLayout()
            btn_use = QPushButton("ใช้ลายเซ็นที่เลือก")
            btn_use.clicked.connect(self._use_gallery)
            grow.addWidget(btn_use)
            grow.addStretch()
            btn_delsig = QPushButton("🗑 ลบออกจากคลัง")
            btn_delsig.setStyleSheet("QPushButton { background:#e5484d; }")
            btn_delsig.clicked.connect(self._delete_gallery)
            grow.addWidget(btn_delsig)
            t0.addLayout(grow)
            self.tabs.addTab(tab0, "🗂 คลังลายเซ็น")

        # ---------- tab: draw ----------
        tab1 = QWidget(objectName="tabPage")
        t1 = QVBoxLayout(tab1)
        t1.addWidget(QLabel("ใช้เมาส์/ปากกา/ทัชแพด เซ็นชื่อในกรอบ"))
        self.canvas = SignatureCanvas()
        t1.addWidget(self.canvas)
        r1 = QHBoxLayout()
        clear = QPushButton("ล้าง")
        clear.setProperty("flat", True)
        clear.clicked.connect(self.canvas.clear)
        r1.addWidget(clear)
        r1.addSpacing(12)
        r1.addWidget(QLabel("สีปากกา:"))
        # quick colour swatches + custom picker
        self._sig_swatches = []
        for label, qc in (("ดำ", QColor(15, 15, 20)),
                          ("น้ำเงิน", QColor(20, 40, 150)),
                          ("แดง", QColor(200, 30, 30))):
            b = QToolButton()
            b.setToolTip(label)
            b.setFixedSize(24, 24)
            b.setStyleSheet(
                f"QToolButton {{ background: {qc.name()}; border: 2px solid #c9ccd1;"
                f" border-radius: 12px; }}")
            b.clicked.connect(lambda _=False, c=qc: self._set_sig_color(c))
            r1.addWidget(b)
            self._sig_swatches.append(b)
        more = QToolButton()
        more.setText("🎨")
        more.setToolTip("เลือกสีอื่น")
        more.clicked.connect(self._pick_sig_color)
        r1.addWidget(more)
        r1.addStretch()
        t1.addLayout(r1)
        self.tabs.addTab(tab1, "✍️ วาดเอง")

        # ---------- tab: import image ----------
        tab2 = QWidget(objectName="tabPage")
        t2 = QVBoxLayout(tab2)
        t2.addWidget(QLabel("เลือกรูปลายเซ็น (.png พื้นหลังโปร่งใสจะสวยที่สุด)"))
        self.img_preview = QLabel("ยังไม่ได้เลือกรูป")
        self.img_preview.setMinimumHeight(160)
        self.img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setStyleSheet(
            "border: 1px dashed #c9ccd1; border-radius: 6px; color: #9a9da3;")
        t2.addWidget(self.img_preview)
        btn_browse = QPushButton("เลือกรูป...")
        btn_browse.clicked.connect(self._browse_image)
        t2.addWidget(btn_browse)
        self._imported_png = None
        self.tabs.addTab(tab2, "🖼 นำเข้ารูป")

        # ---------- tab: type name ----------
        tab3 = QWidget(objectName="tabPage")
        t3 = QVBoxLayout(tab3)
        t3.addWidget(QLabel("พิมพ์ชื่อ แล้วเลือกฟอนต์ลายเซ็น/ลายมือ"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("เช่น สมชาย ใจดี")
        self.name_edit.textChanged.connect(self._update_typed_preview)
        t3.addWidget(self.name_edit)
        self.font_combo = QComboBox()
        populate_font_combo(self.font_combo, self.fm, self.fm.signature_default())
        self.font_combo.currentTextChanged.connect(self._update_typed_preview)
        t3.addWidget(self.font_combo)
        self.typed_preview = QLabel(" ")
        self.typed_preview.setMinimumHeight(110)
        self.typed_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.typed_preview.setStyleSheet(
            "border: 1px dashed #c9ccd1; border-radius: 6px; background: #ffffff;")
        t3.addWidget(self.typed_preview)
        self.tabs.addTab(tab3, "⌨️ พิมพ์ชื่อ")

        # ---------- bottom: size + buttons ----------
        row = QHBoxLayout()
        row.addWidget(QLabel("ความกว้างเมื่อวางลงหน้า (pt)"))
        self.spin_w = QSpinBox()
        self.spin_w.setRange(40, 500)
        self.spin_w.setValue(150)
        row.addWidget(self.spin_w)
        hint = QLabel("(วางแล้วลากมุมเพื่อย่อ-ขยายได้)")
        hint.setStyleSheet("color: #9a9da3;")
        row.addWidget(hint)
        row.addStretch()
        self.chk_save = QCheckBox("บันทึกเข้าคลังไว้ใช้ซ้ำ")
        self.chk_save.setChecked(True)
        row.addWidget(self.chk_save)
        lay.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("ใช้ลายเซ็นนี้")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        btns.accepted.connect(self._ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    # ---------- signature pen colour ----------
    def _set_sig_color(self, qc):
        self.canvas.set_color(qc)

    def _pick_sig_color(self):
        c = QColorDialog.getColor(self.canvas.pen_color, self, "เลือกสีปากกา")
        if c.isValid():
            self.canvas.set_color(c)

    # ---------- signature gallery ----------
    def _use_gallery(self):
        it = self.gallery.currentItem()
        if it is None:
            QMessageBox.information(self, APP_NAME, "กรุณาเลือกลายเซ็นก่อน")
            return
        idx = it.data(Qt.ItemDataRole.UserRole)
        self.result_png = self.saved[idx]
        self.result_width = self.spin_w.value()
        self.result_save = False       # already from the gallery, no need to save again
        self.accept()

    def _delete_gallery(self):
        it = self.gallery.currentItem()
        if it is None:
            return
        idx = it.data(Qt.ItemDataRole.UserRole)
        self.deleted_saved.append(idx)
        self.gallery.takeItem(self.gallery.row(it))

    # ---------- import-image tab ----------
    def _browse_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "เลือกรูปลายเซ็น", "",
                                              "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        with open(path, "rb") as f:
            self._imported_png = f.read()
        pm = QPixmap()
        pm.loadFromData(self._imported_png)
        self.img_preview.setPixmap(
            pm.scaled(420, 150, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation))

    # ---------- type-name tab ----------
    def _typed_image(self):
        name = self.name_edit.text().strip()
        fam = qt_family(self.fm.path(self.font_combo.currentText()))
        if not name or not fam:
            return None
        font = QFont(fam, 56)
        img = QImage(1200, 220, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(font)
        p.setPen(QColor(20, 30, 90))
        p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, name)
        p.end()
        return crop_transparent(img)

    def _update_typed_preview(self):
        img = self._typed_image()
        if img:
            pm = QPixmap.fromImage(img)
            self.typed_preview.setPixmap(
                pm.scaled(440, 100, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation))
        else:
            self.typed_preview.clear()
            self.typed_preview.setText(" ")

    # ---------- OK ----------
    def _ok(self):
        idx = self.tabs.currentIndex()
        if self.has_gallery:
            idx -= 1              # shift index because the gallery tab comes first
        png = None
        from_gallery = False
        if idx == -1:             # gallery tab -> use the selected one
            it = self.gallery.currentItem()
            if it is None:
                QMessageBox.information(self, APP_NAME, "กรุณาเลือกลายเซ็นในคลัง")
                return
            png = self.saved[it.data(Qt.ItemDataRole.UserRole)]
            from_gallery = True
        elif idx == 0:
            png = self.canvas.png_bytes()
            if not png:
                QMessageBox.information(self, APP_NAME, "ยังไม่ได้เซ็นชื่อในกรอบ")
                return
        elif idx == 1:
            png = self._imported_png
            if not png:
                QMessageBox.information(self, APP_NAME, "ยังไม่ได้เลือกรูป")
                return
        else:
            img = self._typed_image()
            if img is None:
                QMessageBox.information(self, APP_NAME, "กรุณาพิมพ์ชื่อก่อน")
                return
            png = qimage_png_bytes(img)
        self.result_png = png
        self.result_width = self.spin_w.value()
        # save to gallery only for newly created signatures (not gallery picks)
        self.result_save = (not from_gallery) and self.chk_save.isChecked()
        self.accept()


# ============================================================
#  PDF page view + mouse handling for every mode
# ============================================================
class PageView(QLabel):
    """Show the PDF page and handle the mouse:
    - dashed box: text (colour per mode) / image-signature (orange)
    - move mode: 4 corner handles on both images (orange) and text (green)
    - pen mode: drag to draw; comment mode: click to drop a note
    - Ctrl+wheel = zoom, wheel in placement mode = adjust stamp size."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        # accept keyboard focus so arrow-key nudging reaches us instead of the
        # scroll area (which would otherwise just scroll the view)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.drag_start = None        # highlight / white-out
        self.drag_rect = None
        self.hover_span = None
        self.hover_img = None
        self.sel_span = None          # item selected for arrow-key nudging (outlined)
        self.sel_img = None
        self.search_term = ""         # last search term (to highlight matches)
        self.move_span = None
        self.move_img = None
        self.move_from = None
        self.move_to = None
        self.resize_img = None        # image being resized
        self.resize_span_target = None  # text being resized
        self.resize_bbox = None       # initial rect (PDF coords)
        self.resize_anchor = None     # fixed opposite corner (PDF coords)
        self.resize_rect = None       # new rect while dragging (PDF coords)
        self.pen_points = None        # pen points while dragging (widget-screen coords)
        self.comment_drag = None      # comment being dragged
        self.comment_from = None
        self.comment_moved = False
        self.cursor_pos = None        # signature/image placement mode

    # ---------- coordinate conversion ----------
    def _offsets(self):
        pm = self.pixmap()
        if pm is None:
            return 0.0, 0.0
        return (self.width() - pm.width()) / 2, (self.height() - pm.height()) / 2

    def to_pdf_point(self, pos, clamp=False):
        pm = self.pixmap()
        if pm is None or not self.main.pdf.is_open():
            return None
        ox, oy = self._offsets()
        x = (pos.x() - ox) / self.main.zoom
        y = (pos.y() - oy) / self.main.zoom
        rect = self.main.pdf.page_rect(self.main.page_index)
        if clamp:
            x = max(0.0, min(x, rect.width))
            y = max(0.0, min(y, rect.height))
        if 0 <= x <= rect.width and 0 <= y <= rect.height:
            return fitz.Point(x, y)
        return None

    def pdf_rect_to_screen(self, r):
        ox, oy = self._offsets()
        z = self.main.zoom
        return QRect(int(r.x0 * z + ox), int(r.y0 * z + oy),
                     int((r.x1 - r.x0) * z), int((r.y1 - r.y0) * z))

    # ---------- resize handles ----------
    def _handle_rects(self, bbox):
        """The 4 corner-handle rects (screen coords) of a box."""
        r = self.pdf_rect_to_screen(bbox)
        h = HANDLE_PX
        return {
            "tl": QRect(r.left() - h // 2, r.top() - h // 2, h, h),
            "tr": QRect(r.right() - h // 2, r.top() - h // 2, h, h),
            "bl": QRect(r.left() - h // 2, r.bottom() - h // 2, h, h),
            "br": QRect(r.right() - h // 2, r.bottom() - h // 2, h, h),
        }

    def _corner_hit(self, bbox, pos):
        """Return the name of the clicked corner (3px hit slop) or None."""
        for name, hr in self._handle_rects(bbox).items():
            if hr.adjusted(-3, -3, 3, 3).contains(pos):
                return name
        return None

    def _begin_resize(self, bbox, corner):
        r = fitz.Rect(bbox)
        self.resize_bbox = r
        self.resize_anchor = {"tl": fitz.Point(r.x1, r.y1),
                              "tr": fitz.Point(r.x0, r.y1),
                              "bl": fitz.Point(r.x1, r.y0),
                              "br": fitz.Point(r.x0, r.y0)}[corner]
        self.resize_rect = fitz.Rect(r)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.update()

    def _resize_rect_from(self, cursor_pdf):
        """Compute the new rect from the fixed corner and the cursor, keeping the ratio."""
        anchor = self.resize_anchor
        r = self.resize_bbox
        ratio = r.height / r.width if r.width else 1.0
        w = max(abs(cursor_pdf.x - anchor.x), 8.0)
        h = w * ratio
        x0 = anchor.x if cursor_pdf.x >= anchor.x else anchor.x - w
        y0 = anchor.y if cursor_pdf.y >= anchor.y else anchor.y - h
        return fitz.Rect(x0, y0, x0 + w, y0 + h)

    # ---------- mouse wheel ----------
    def wheelEvent(self, ev):
        m = self.main
        step = 1 if ev.angleDelta().y() > 0 else -1
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            m.zoom_step(step)
            ev.accept()
            return
        if m.mode in (MODE_SIGNATURE, MODE_IMAGE):
            m.adjust_stamp_width(step * 10)
            self.update()
            ev.accept()
            return
        super().wheelEvent(ev)

    # ---------- mouse ----------
    def mouseMoveEvent(self, ev):
        m = self.main
        pos = ev.position().toPoint()
        if not m.pdf.is_open():
            return super().mouseMoveEvent(ev)

        if self.resize_img or self.resize_span_target:
            pt = self.to_pdf_point(pos, clamp=True)
            if pt:
                self.resize_rect = self._resize_rect_from(pt)
                self.update()
        elif m.mode == MODE_PEN and self.pen_points is not None:
            if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.pen_points:
                # Shift = straight line: keep only the start point + current point
                self.pen_points = [self.pen_points[0], pos]
            else:
                # thin out points that are very close together so a long fast
                # stroke stays smooth (fewer repaints, no dropped line)
                last = self.pen_points[-1]
                if (pos - last).manhattanLength() >= 2:
                    self.pen_points.append(pos)
            self.update()
        elif m.mode == MODE_COMMENT and self.comment_drag is not None:
            if (pos - self.comment_from).manhattanLength() > 5:
                self.comment_moved = True
        elif m.mode in (MODE_EDIT_TEXT, MODE_DELETE_TEXT, MODE_MOVE_TEXT):
            if self.move_span or self.move_img:
                self.move_to = pos
                self.update()
            else:
                pt = self.to_pdf_point(pos)
                span = m.pdf.span_at(m.page_index, pt) if pt else None
                img = None
                if m.mode in (MODE_MOVE_TEXT, MODE_DELETE_TEXT) and pt:
                    img = m.pdf.image_at(m.page_index, pt)
                    if img and span:
                        span = None      # image sits above text, image wins
                # cursor changes when hovering a corner (move mode)
                if m.mode == MODE_MOVE_TEXT and (
                        (self.hover_img and self._corner_hit(self.hover_img["bbox"], pos)) or
                        (self.hover_span and self._corner_hit(
                            fitz.Rect(self.hover_span["bbox"]), pos))):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif m.mode == MODE_MOVE_TEXT:
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
                if span is not self.hover_span or img is not self.hover_img:
                    self.hover_span = span
                    self.hover_img = img
                    self.update()
        elif m.mode in (MODE_SIGNATURE, MODE_IMAGE):
            self.cursor_pos = pos
            self.update()
        elif (m.mode in (MODE_HIGHLIGHT, MODE_WHITEOUT, MODE_LINK)
              or (m.mode == MODE_COMMENT and getattr(m, 'comment_kind', 'note') != 'note')) and self.drag_start:
            self.drag_rect = QRect(self.drag_start, pos).normalized()
            self.update()
        super().mouseMoveEvent(ev)

    def mousePressEvent(self, ev):
        m = self.main
        pos = ev.position().toPoint()
        pt = self.to_pdf_point(pos)
        if m.mode == MODE_ADD_TEXT and pt:
            m.add_text_at(pt)
        elif m.mode == MODE_EDIT_TEXT and pt:
            m.edit_text_at(pt)
        elif m.mode == MODE_DELETE_TEXT and pt:
            m.delete_at(pt)
        elif m.mode == MODE_SIGNATURE and pt:
            m.place_stamp(pt, signature=True)
        elif m.mode == MODE_IMAGE and pt:
            m.place_stamp(pt, signature=False)
        elif m.mode == MODE_PEN and pt:
            self.pen_points = [pos]
        elif m.mode == MODE_COMMENT and pt:
            existing = m.pdf.comment_at(m.page_index, pt)
            kind = getattr(m, "comment_kind", "note")
            if existing:
                # press an existing comment (any kind) -> prime a move-drag
                # (a click without dragging = open it to read/edit)
                self.comment_drag = existing
                self.comment_from = pos
                self.comment_moved = False
            elif kind == "note":
                m.comment_click(pt)          # empty spot -> create a sticky note
            else:
                self.drag_start = pos        # arrow/textbox: drag to draw a new one
        elif m.mode == MODE_VIEW and pt and m.pdf.comment_at(m.page_index, pt):
            m.comment_click(pt)      # view mode can open a comment to read
        elif m.mode == MODE_MOVE_TEXT:
            # Ctrl+click = add/remove the clicked text to a MULTI-selection so
            # several spans can be nudged or dragged together (arranging a
            # heading + subtitle + date line used to take three separate
            # rounds of click-drag)
            if (ev.modifiers() & Qt.KeyboardModifier.ControlModifier) and pt:
                span = m.pdf.span_at(m.page_index, pt)
                if span:
                    m.toggle_multi_select(span)
                return
            # 1) click a corner -> start resizing (image first, then text)
            if self.hover_img:
                corner = self._corner_hit(self.hover_img["bbox"], pos)
                if corner:
                    self.resize_img = self.hover_img
                    self._begin_resize(self.hover_img["bbox"], corner)
                    return
            if self.hover_span:
                bbox = fitz.Rect(self.hover_span["bbox"])
                corner = self._corner_hit(bbox, pos)
                if corner:
                    self.resize_span_target = self.hover_span
                    self._begin_resize(bbox, corner)
                    return
            # 2) click the middle of text/image -> start moving
            if pt:
                span = m.pdf.span_at(m.page_index, pt)
                img = m.pdf.image_at(m.page_index, pt)
                if img and span:
                    span = None
                if span or img:
                    self.move_span = span
                    self.move_img = img
                    self.move_from = pos
                    self.move_to = pos
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    self.update()
                else:
                    m.status("จับไม่โดน — กดค้างให้ตรงกรอบเส้นประ (ข้อความ) "
                             "หรือกรอบสีส้ม (รูป/ลายเซ็น) / ลากมุมเพื่อย่อ-ขยาย")
        elif m.mode in (MODE_HIGHLIGHT, MODE_WHITEOUT, MODE_LINK):
            self.drag_start = pos
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        m = self.main
        pos = ev.position().toPoint()
        if self.resize_img or self.resize_span_target:
            img, span = self.resize_img, self.resize_span_target
            rect, orig = self.resize_rect, self.resize_bbox
            self.resize_img = self.resize_span_target = None
            self.resize_bbox = self.resize_anchor = self.resize_rect = None
            self.hover_img = None
            self.hover_span = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()
            if rect is not None and orig is not None and orig.width > 0:
                if img:
                    m.resize_image_ui(img, rect)
                else:
                    m.resize_text_ui(span, rect.width / orig.width)
        elif m.mode == MODE_PEN and self.pen_points is not None:
            pts = [self.to_pdf_point(p, clamp=True) for p in self.pen_points]
            pts = [(p.x, p.y) for p in pts if p is not None]
            self.pen_points = None
            self.update()
            if len(pts) >= 2:
                m.add_ink_ui(pts)
        elif m.mode == MODE_COMMENT and self.comment_drag is not None:
            c = self.comment_drag
            moved = self.comment_moved
            frm = self.comment_from
            self.comment_drag = None
            self.comment_from = None
            self.comment_moved = False
            if moved and frm is not None:
                dx = (pos.x() - frm.x()) / m.zoom
                dy = (pos.y() - frm.y()) / m.zoom
                m.move_comment_ui(c, dx, dy)
            else:
                m.comment_click(self.to_pdf_point(pos) or fitz.Point(0, 0), c)
        elif m.mode == MODE_MOVE_TEXT and (self.move_span or self.move_img):
            dx = (pos.x() - self.move_from.x()) / m.zoom
            dy = (pos.y() - self.move_from.y()) / m.zoom
            span, img = self.move_span, self.move_img
            self.move_span = self.move_img = None
            self.move_from = self.move_to = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()
            if abs(dx) > 0.8 or abs(dy) > 0.8:
                if span:
                    # dragging a span that belongs to the multi-selection
                    # moves the WHOLE group by the same offset
                    if m.multi_sel and any(
                            s["bbox"] == span["bbox"] and s["text"] == span["text"]
                            for s in m.multi_sel):
                        m.move_multi(dx, dy)
                    else:
                        m.move_text(span, dx, dy)
                else:
                    m.move_image_ui(img, dx, dy)
            else:
                # a light click (no drag) -> select it for arrow-key nudging
                pt = self.to_pdf_point(pos)
                if pt:
                    m.select_item(pt)
        elif (m.mode in (MODE_HIGHLIGHT, MODE_WHITEOUT, MODE_LINK)
              or (m.mode == MODE_COMMENT and getattr(m, 'comment_kind', 'note') != 'note')) and self.drag_start:
            p1 = self.to_pdf_point(self.drag_start)
            p2 = self.to_pdf_point(pos)
            mode = m.mode
            self.drag_start = None
            self.drag_rect = None
            self.update()
            if p1 and p2:
                if mode == MODE_HIGHLIGHT:
                    m.add_highlight(fitz.Rect(p1, p2).normalize())
                elif mode == MODE_WHITEOUT:
                    m.apply_whiteout(fitz.Rect(p1, p2).normalize())
                elif mode == MODE_LINK:
                    m.add_link_ui(fitz.Rect(p1, p2).normalize())
                else:                       # comment arrow / textbox
                    m.place_comment_drag(p1, p2)
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        # forward navigation/nudge keys to the main window so arrow-key moving
        # works even though this widget holds the keyboard focus
        k = ev.key()
        forward = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up,
                   Qt.Key.Key_Down, Qt.Key.Key_Delete, Qt.Key.Key_Escape,
                   Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
        if k in forward:
            self.main.keyPressEvent(ev)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def leaveEvent(self, ev):
        self.cursor_pos = None
        self.hover_span = None
        self.hover_img = None
        self.update()
        super().leaveEvent(ev)

    # ---------- overlay painting ----------
    def _draw_handles(self, painter, bbox, color):
        painter.setPen(QPen(QColor("#ffffff"), 1))
        for hr in self._handle_rects(bbox).values():
            painter.fillRect(hr, color)
            painter.drawRect(hr)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        m = self.main
        if self.pixmap() is None:
            return
        painter = QPainter(self)

        # highlight search matches on this page (translucent yellow)
        if self.search_term and m.pdf.is_open():
            for r in m.pdf.find_on_page(m.page_index, self.search_term):
                sr = self.pdf_rect_to_screen(fitz.Rect(r))
                painter.fillRect(sr, QColor(255, 210, 0, 90))
                painter.setPen(QPen(QColor(230, 160, 0), 1))
                painter.drawRect(sr)

        # outline the arrow-key-selected item
        sel_bbox = None
        if self.sel_span is not None:
            sel_bbox = fitz.Rect(self.sel_span["bbox"])
        elif self.sel_img is not None:
            sel_bbox = self.sel_img["bbox"]
        if sel_bbox is not None:
            r = self.pdf_rect_to_screen(sel_bbox)
            painter.setPen(QPen(QColor(ADOBE_BLUE), 2, Qt.PenStyle.SolidLine))
            painter.fillRect(r, QColor(20, 115, 230, 30))
            painter.drawRect(r)
            for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                painter.fillRect(c.x() - 3, c.y() - 3, 6, 6, QColor(ADOBE_BLUE))

        # outline every member of the multi-selection (Ctrl+click set) in a
        # distinct violet so the user can see exactly which lines will move
        # together before dragging or pressing an arrow key
        for msp in getattr(m, "multi_sel", []):
            r = self.pdf_rect_to_screen(fitz.Rect(msp["bbox"]))
            painter.setPen(QPen(QColor("#8b5cf6"), 2, Qt.PenStyle.SolidLine))
            painter.fillRect(r, QColor(139, 92, 246, 28))
            painter.drawRect(r)

        mode_colors = {MODE_EDIT_TEXT: QColor(ADOBE_BLUE),
                       MODE_MOVE_TEXT: QColor("#0f9d58"),
                       MODE_DELETE_TEXT: QColor("#e5484d")}
        if m.mode in mode_colors and m.pdf.is_open():
            base = mode_colors[m.mode]
            painter.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 130),
                                1, Qt.PenStyle.DashLine))
            for sp in m.pdf.spans(m.page_index):
                painter.drawRect(self.pdf_rect_to_screen(fitz.Rect(sp["bbox"])))
            if m.mode in (MODE_MOVE_TEXT, MODE_DELETE_TEXT):
                painter.setPen(QPen(QColor(IMAGE_COLOR.red(), IMAGE_COLOR.green(),
                                           IMAGE_COLOR.blue(), 170),
                                    1, Qt.PenStyle.DashLine))
                for info in m.pdf.images(m.page_index):
                    painter.drawRect(self.pdf_rect_to_screen(info["bbox"]))
            busy = self.move_span or self.move_img or self.resize_img or self.resize_span_target
            if self.hover_span and not busy:
                r0 = fitz.Rect(self.hover_span["bbox"])
                r = self.pdf_rect_to_screen(r0)
                painter.fillRect(r, QColor(base.red(), base.green(), base.blue(), 40))
                painter.setPen(QPen(base, 2))
                painter.drawRect(r)
                if m.mode == MODE_MOVE_TEXT:      # text resize handles
                    self._draw_handles(painter, r0, TEXT_HANDLE_COLOR)
            if self.hover_img and not busy:
                r = self.pdf_rect_to_screen(self.hover_img["bbox"])
                painter.fillRect(r, QColor(IMAGE_COLOR.red(), IMAGE_COLOR.green(),
                                           IMAGE_COLOR.blue(), 35))
                painter.setPen(QPen(IMAGE_COLOR, 2))
                painter.drawRect(r)
                if m.mode == MODE_MOVE_TEXT:      # image resize handles
                    self._draw_handles(painter, self.hover_img["bbox"], IMAGE_COLOR)

        # rect while resizing
        if (self.resize_img or self.resize_span_target) and self.resize_rect is not None:
            c = IMAGE_COLOR if self.resize_img else TEXT_HANDLE_COLOR
            r = self.pdf_rect_to_screen(self.resize_rect)
            painter.fillRect(r, QColor(c.red(), c.green(), c.blue(), 40))
            painter.setPen(QPen(c, 2, Qt.PenStyle.DashLine))
            painter.drawRect(r)

        # drag ghost
        if (self.move_span or self.move_img) and self.move_from and self.move_to:
            if self.move_span:
                r = self.pdf_rect_to_screen(fitz.Rect(self.move_span["bbox"]))
                c = QColor("#0f9d58")
            else:
                r = self.pdf_rect_to_screen(self.move_img["bbox"])
                c = IMAGE_COLOR
            r.translate(self.move_to - self.move_from)
            painter.fillRect(r, QColor(c.red(), c.green(), c.blue(), 50))
            painter.setPen(QPen(c, 2, Qt.PenStyle.DashLine))
            painter.drawRect(r)

        # pen stroke while dragging (in the chosen colour)
        if self.pen_points and len(self.pen_points) >= 2:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen_qc = getattr(m, "pen_color", None) or PEN_COLOR
            painter.setPen(QPen(pen_qc, max(2, int(2 * m.zoom)),
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            for a, b in zip(self.pen_points, self.pen_points[1:]):
                painter.drawLine(a, b)

        # signature/image preview following the cursor
        if m.mode in (MODE_SIGNATURE, MODE_IMAGE) and self.cursor_pos:
            ghost = m.stamp_preview()
            if ghost is not None:
                w = int(m.stamp_width() * m.zoom)
                h = int(w * ghost.height() / max(1, ghost.width()))
                x = self.cursor_pos.x() - w // 2
                y = self.cursor_pos.y() - h // 2
                painter.setOpacity(0.65)
                painter.drawImage(QRect(x, y, w, h), ghost)
                painter.setOpacity(1.0)
                painter.setPen(QPen(QColor(ADOBE_BLUE), 1, Qt.PenStyle.DashLine))
                painter.drawRect(x, y, w, h)

        # highlight / white-out / link / comment drag box
        if self.drag_rect:
            comment_kind = getattr(m, "comment_kind", "note")
            if m.mode == MODE_WHITEOUT:
                painter.setPen(QPen(QColor("#e5484d"), 1))
                painter.fillRect(self.drag_rect, QColor(255, 255, 255, 170))
                painter.drawRect(self.drag_rect)
            elif m.mode == MODE_LINK:
                painter.setPen(QPen(QColor(ADOBE_BLUE), 1, Qt.PenStyle.DashLine))
                painter.fillRect(self.drag_rect, QColor(20, 115, 230, 40))
                painter.drawRect(self.drag_rect)
            elif m.mode == MODE_COMMENT and comment_kind == "arrow":
                # preview an actual thick arrow from press to current point
                self._draw_arrow(painter, self.drag_start, self.drag_rect,
                                 QColor(ADOBE_BLUE))
            elif m.mode == MODE_COMMENT and comment_kind == "textbox":
                painter.setPen(QPen(QColor(ADOBE_BLUE), 1, Qt.PenStyle.DashLine))
                painter.fillRect(self.drag_rect, QColor(255, 245, 200, 150))
                painter.drawRect(self.drag_rect)
            else:                                   # highlight
                painter.setPen(QColor(255, 180, 0))
                painter.fillRect(self.drag_rect, QColor(255, 220, 60, 80))
                painter.drawRect(self.drag_rect)
        painter.end()

    def _draw_arrow(self, painter, start, rect, color):
        """Draw a thick arrow from `start` to the current drag end point."""
        import math
        if start is None:
            return
        # current end = the rect corner opposite the start
        end = rect.bottomRight() if (rect.topLeft() == start) else rect.topLeft()
        # pick the corner farthest from start as the arrow tip
        corners = [rect.topLeft(), rect.topRight(),
                   rect.bottomLeft(), rect.bottomRight()]
        end = max(corners, key=lambda c: (c.x() - start.x())**2 + (c.y() - start.y())**2)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(color, 3, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawLine(start, end)
        ang = math.atan2(end.y() - start.y(), end.x() - start.x())
        L = 16
        for da in (math.radians(150), math.radians(-150)):
            hx = end.x() + L * math.cos(ang + da)
            hy = end.y() + L * math.sin(ang + da)
            painter.drawLine(end, QPoint(int(hx), int(hy)))
