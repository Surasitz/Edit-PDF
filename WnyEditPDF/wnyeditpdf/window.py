# -*- coding: utf-8 -*-
"""MainWindow - the main WnyEditPDF window; wires the UI to PdfDocument."""

if __package__ in (None, ""):          # run directly, not via main.py
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    import wnyeditpdf                   # register the package first
    __package__ = "app"

import os
import sys
import fitz

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox, QToolBar,
    QLabel, QScrollArea, QInputDialog, QLineEdit, QWidget, QSizePolicy,
    QStatusBar, QListWidget, QListWidgetItem, QSplitter, QSpinBox,
    QComboBox, QToolButton, QDialog, QMenu, QProgressDialog
)
from PyQt6.QtGui import (
    QAction, QPixmap, QImage, QColor, QIcon, QKeySequence, QPalette
)
from PyQt6.QtCore import Qt, QSize, QSettings, QLocale

from .config import (
    APP_NAME, VERSION, ORG_NAME, STYLE, CANVAS_GRAY, ADOBE_BLUE, resource_path,
    MODE_VIEW, MODE_EDIT_TEXT, MODE_MOVE_TEXT, MODE_DELETE_TEXT,
    MODE_ADD_TEXT, MODE_HIGHLIGHT, MODE_SIGNATURE, MODE_IMAGE, MODE_WHITEOUT,
    MODE_PEN, MODE_COMMENT, MODE_LINK,
)
from .fonts import FontManager
from .document import PdfDocument
from .i18n import tr as _tr
from .docx_export import ExportCancelled
from .widgets import (PageView, TextEditDialog, SignatureDialog, CommentDialog,
                      FindReplaceDialog, SearchBar,
                      ThumbnailList, symbol_image, qr_png_bytes,
                      stamp_text_image, ScanEnhanceDialog, WordExportDialog,
                      CompressDialog)

MAX_RECENT = 6


# lock digits to Arabic (0-9) app-wide so Thai digits never appear
_ARABIC_LOCALE = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.pdf = PdfDocument()
        self.fm = FontManager()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.lang = self.settings.value("lang", "th") or "th"

        self.page_index = 0
        self.zoom = 1.5
        self.mode = MODE_VIEW
        self.multi_sel = []   # Ctrl+click group selection (spans)
        QLocale.setDefault(_ARABIC_LOCALE)   # Arabic digits app-wide
        self.text_color = QColor(20, 20, 20)
        self.highlight_color = QColor(255, 235, 60)   # highlight colour (yellow)
        self.font_size = 16
        self.current_font = self.fm.default_name()
        # full (non-subset) Thai font as a safety net when rewriting text
        for _cand in ("TH SarabunPSK", "TH Sarabun New", "Sarabun (Google)"):
            if _cand in self.fm:
                self.pdf.default_thai_font = self.fm.path(_cand)
                break
        else:
            self.pdf.default_thai_font = self.fm.path(self.fm.default_name())
        # let document know all full fonts, to match family when an embedded subset fails
        self.pdf.bundled_fonts = {n: self.fm.path(n) for n in self.fm.names()}

        self.signature_png = None     # current signature (PNG bytes)
        self.saved_signatures = self._load_signatures()   # persistent signature gallery
        self.selection = None         # item selected for arrow-key nudging
        self._last_find = ""          # last search term
        self.comment_kind = "note"    # note / arrow / textbox
        self.pen_color = QColor(20, 30, 115)   # pen colour (choosable)
        self.signature_width = 150
        self.image_png = None         # image to place (bytes)
        self.image_width = 200
        self._ghost_cache = {}        # bytes -> QImage cache for the cursor preview

        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        # app icon from the logo (look in app/ and the project root)
        for _ic in ("wnyeditpdf/assets/logo.png", "assets/logo.png", "logo.png"):
            _p = resource_path(_ic)
            if os.path.exists(_p):
                self.setWindowIcon(QIcon(_p))
                break
        self.resize(1360, 880)
        self.setAcceptDrops(True)      # allow dropping a PDF file onto the window
        self._build_ui()
        self._update_undo_buttons()

    # ---------- drag & drop a PDF file onto the window ----------
    def dragEnterEvent(self, ev):
        md = ev.mimeData()
        if md.hasUrls() and any(u.toLocalFile().lower().endswith(".pdf")
                                for u in md.urls()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        pdfs = [u.toLocalFile() for u in ev.mimeData().urls()
                if u.toLocalFile().lower().endswith(".pdf")]
        if not pdfs:
            ev.ignore()
            return
        ev.acceptProposedAction()
        if not self.confirm_discard():
            return
        self._open_path(pdfs[0])       # open the first PDF dropped
        if len(pdfs) > 1:
            self.status("ลากมาหลายไฟล์ — เปิดไฟล์แรก "
                        "(ใช้ ไฟล์ → รวม PDF เพื่อรวมไฟล์อื่น)")

    # ======================================================
    #  UI
    # ======================================================
    def _build_ui(self):
        # --- left thumbnail strip ---
        self.thumbs = ThumbnailList(self)
        self.thumbs.setIconSize(QSize(112, 150))
        self.thumbs.setFixedWidth(168)
        self.thumbs.currentRowChanged.connect(self._thumb_clicked)

        # --- page display area ---
        self.page_view = PageView(self)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.page_view)
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for wdg in (self.page_view, self.scroll.viewport()):
            pal = wdg.palette()
            pal.setColor(QPalette.ColorRole.Window, QColor(CANVAS_GRAY))
            wdg.setPalette(pal)
            wdg.setAutoFillBackground(True)

        split = QSplitter()
        split.addWidget(self.thumbs)
        split.addWidget(self.scroll)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        # floating search bar (hidden until Ctrl+F)
        self.search_bar = SearchBar(self)
        self.search_bar.setParent(self.scroll)
        self.search_bar.hide()
        self._search_hits = []      # [(pno, rect), ...] every match in the file
        self._search_idx = -1       # currently focused match

        self.setStatusBar(QStatusBar())
        self.status(self.T("ยินดีต้อนรับสู่ WnyEditPDF — เปิดไฟล์ PDF เพื่อเริ่มใช้งาน (Ctrl+O)"))

        self._build_menus()
        self._build_toolbars()

    def T(self, text):
        """Translate a UI string to the current language."""
        return _tr(text, self.lang)

    def toggle_language(self):
        """Switch Thai <-> English and rebuild the menus/toolbars."""
        self.lang = "en" if self.lang == "th" else "th"
        self.settings.setValue("lang", self.lang)
        # remove existing toolbars then rebuild everything in the new language
        for tb in list(self.findChildren(QToolBar)):
            self.removeToolBar(tb)
            tb.deleteLater()
        self._build_menus()
        self._build_toolbars()
        if self.pdf.is_open():
            self.refresh_all()

    def _build_menus(self):
        # avoid duplicate/garbled menus on some systems: always use Qt's menu bar and clear first
        self.menuBar().setNativeMenuBar(False)
        self.menuBar().clear()
        # ---------- File ----------
        m_file = self.menuBar().addMenu(self.T("ไฟล์(&F)"))
        self._act(m_file, self.T("เปิด..."), self.open_pdf, "Ctrl+O")
        self.menu_recent = m_file.addMenu(self.T("เปิดไฟล์ล่าสุด"))
        self._rebuild_recent_menu()
        m_file.addSeparator()
        self._act(m_file, self.T("บันทึก"), self.save_pdf, "Ctrl+S")
        self._act(m_file, self.T("บันทึกเป็น..."), self.save_as_pdf, "Ctrl+Shift+S")
        self._act(m_file, self.T("บันทึกแบบมีรหัสผ่าน..."), self.save_encrypted)
        m_file.addSeparator()
        self._act(m_file, self.T("🕘 ประวัติเวอร์ชัน (กู้คืนไฟล์เก่า)..."),
                  self.show_version_history)
        m_file.addSeparator()
        self._act(m_file, self.T("รวม PDF (เลือกหน้า + ตำแหน่งแทรก)..."), self.merge_pdf)
        self._act(m_file, self.T("🗜 บีบอัด PDF ลดขนาดไฟล์ (ทีเดียวหลายไฟล์)..."),
                  self.compress_pdfs)
        self._act(m_file, self.T("ส่งออกหน้านี้เป็น PNG..."), self.export_png)
        self._act(m_file, self.T("📝 แปลงเป็น Word (.docx)..."), self.export_word)
        self._act(m_file, self.T("ดึงข้อความทั้งไฟล์เป็น .txt..."), self.export_text)
        m_file.addSeparator()
        self._act(m_file, self.T("ออกจากโปรแกรม"), self.close, "Ctrl+Q")

        # ---------- Edit ----------
        m_edit = self.menuBar().addMenu(self.T("แก้ไข(&E)"))
        self.act_undo = self._act(m_edit, self.T("↶ เลิกทำ (Undo)"), self.undo, "Ctrl+Z")
        self.act_redo = self._act(m_edit, self.T("↷ ทำซ้ำ (Redo)"), self.redo, "Ctrl+Y")
        m_edit.addSeparator()
        self._act(m_edit, self.T("ค้นหา / แทนที่..."), self.search_text, "Ctrl+F")

        # ---------- Page ----------
        m_page = self.menuBar().addMenu(self.T("หน้า(&P)"))
        self._act(m_page, self.T("หมุน 90° ตามเข็ม"), lambda: self.rotate_page(90))
        self._act(m_page, self.T("หมุน 90° ทวนเข็ม"), lambda: self.rotate_page(-90))
        m_page.addSeparator()
        self._act(m_page, self.T("เลื่อนหน้านี้ขึ้น (ไปก่อนหน้า)"), lambda: self.move_page(-1))
        self._act(m_page, self.T("เลื่อนหน้านี้ลง (ไปทีหลัง)"), lambda: self.move_page(1))
        m_page.addSeparator()
        self._act(m_page, self.T("ลบหน้านี้"), self.delete_page)
        self._act(m_page, self.T("แทรกหน้าว่างหลังหน้านี้"), self.insert_blank_page)
        self._act(m_page, self.T("แยกช่วงหน้าเป็นไฟล์ใหม่..."), self.extract_pages)

        # ---------- Tools ----------
        m_tools = self.menuBar().addMenu(self.T("เครื่องมือ(&T)"))
        self._act(m_tools, self.T("🖼 แทรกรูปภาพ (PNG/JPG)..."), self.tool_image)
        sym = m_tools.addMenu(self.T("🔖 แสตมป์สัญลักษณ์"))
        for kind, label in (("check", self.T("✔️  เครื่องหมายถูก")),
                            ("cross", self.T("❌  กากบาท")),
                            ("dot", self.T("⚫  จุด")),
                            ("circle", self.T("⭕  วงกลมล้อมรอบ")),
                            ("dash", self.T("➖  ขีดเส้น/ขีดฆ่า"))):
            self._act(sym, label, lambda _=False, k=kind: self.tool_symbol(k))
        self._act(m_tools, self.T("💧 ใส่ลายน้ำทุกหน้า..."), self.add_watermark)
        self._act(m_tools, self.T("📋 กรอกฟอร์ม (เลือกจากรายการช่อง)"), self.fill_form_dialog)
        self._act(m_tools, self.T("⬜ ปิดทับพื้นที่ (ลากคลุม)"), lambda: self.change_mode(MODE_WHITEOUT))
        self._act(m_tools, self.T("🔗 เพิ่มลิงก์ (ลากคลุมพื้นที่)"), lambda: self.change_mode(MODE_LINK))
        self._act(m_tools, self.T("🔗 ใส่ลิงก์บนข้อความ (คลิกข้อความ)"), self.tool_link_on_text)
        self._act(m_tools, self.T("🔢 ใส่เลขหน้าอัตโนมัติ..."), self.add_page_numbers_ui)
        m_tools.addSeparator()
        self._act(m_tools, self.T("📋 ตราประทับข้อความ (สำเนาถูกต้อง/ด่วน/วันที่)..."), self.tool_stamp)
        self._act(m_tools, self.T("🔳 สร้าง QR Code..."), self.tool_qr)
        m_tools.addSeparator()
        self._act(m_tools, self.T("🔆 ปรับแต่งรูปสแกน (สว่าง/คมชัด/แก้เอียง)..."),
                  self.tool_enhance_scan)

        # ---------- Signature ----------
        m_sign = self.menuBar().addMenu(self.T("ลายเซ็น(&S)"))
        self._act(m_sign, self.T("✍️ สร้าง/เลือกลายเซ็น (วาด / นำเข้ารูป / พิมพ์ชื่อ)..."), self.tool_signature)

        # ---------- Help ----------
        m_help = self.menuBar().addMenu(self.T("ช่วยเหลือ(&H)"))
        self._act(m_help, f'{self.T("เกี่ยวกับ")} {APP_NAME}', self.about)

    def _build_toolbars(self):
        # ============ row 1: file / navigation / zoom ============
        tb1 = QToolBar()
        tb1.setMovable(False)
        self.addToolBar(tb1)

        self._act(tb1, self.T("📂 เปิด"), self.open_pdf)
        self._act(tb1, self.T("💾 บันทึก"), self.save_pdf)
        tb1.addSeparator()

        self.btn_undo = QToolButton(text="↶")
        self.btn_undo.setToolTip("เลิกทำ (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo)
        tb1.addWidget(self.btn_undo)
        self.btn_redo = QToolButton(text="↷")
        self.btn_redo.setToolTip("ทำซ้ำ (Ctrl+Y)")
        self.btn_redo.clicked.connect(self.redo)
        tb1.addWidget(self.btn_redo)
        tb1.addSeparator()

        self._act(tb1, "◀", self.prev_page)
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(58)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.setLocale(_ARABIC_LOCALE)   # keep the page box in Arabic digits
        self.page_spin.valueChanged.connect(self.jump_page)
        tb1.addWidget(self.page_spin)
        self.page_total = QLabel(" / 0  ")
        tb1.addWidget(self.page_total)
        self._act(tb1, "▶", self.next_page)
        tb1.addSeparator()

        self._act(tb1, "−", lambda: self.set_zoom(self.zoom / 1.2))
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setFixedWidth(86)
        for z in ("50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"):
            self.zoom_combo.addItem(z)
        self.zoom_combo.setCurrentText("150%")
        self.zoom_combo.activated.connect(
            lambda _: self._apply_zoom_text(self.zoom_combo.currentText()))
        self.zoom_combo.lineEdit().returnPressed.connect(
            lambda: self._apply_zoom_text(self.zoom_combo.currentText()))
        tb1.addWidget(self.zoom_combo)
        self._act(tb1, "+", lambda: self.set_zoom(self.zoom * 1.2))
        self._act(tb1, self.T("พอดีหน้า"), self.fit_page)
        tb1.addSeparator()
        self._act(tb1, self.T("🔎 ค้นหา/แทนที่"), self.search_text)

        # ============ row 2: editing tools ============
        self.addToolBarBreak()
        tb2 = QToolBar()
        tb2.setMovable(False)
        self.addToolBar(tb2)

        self.mode_buttons = {}
        for mode, label, tip in (
            (MODE_VIEW, "🖱 เลือก", "โหมดดู / คลิกไอคอนคอมเมนต์เพื่ออ่าน"),
            (MODE_EDIT_TEXT, "✏️ แก้ข้อความ", "คลิกข้อความเดิมเพื่อแก้ไข (เลือกฟอนต์/ขนาด/สีในกล่อง)"),
            (MODE_MOVE_TEXT, "✥ ขยับ/ย่อขยาย", "ลากข้อความหรือรูปไปวางที่ใหม่ / ลากมุมเพื่อย่อ-ขยาย / Ctrl+คลิก เลือกหลายข้อความขยับพร้อมกัน"),
            (MODE_DELETE_TEXT, "🗑 ลบ", "คลิกข้อความ รูป ลายเซ็น เส้นปากกา หรือคอมเมนต์ เพื่อลบ"),
            (MODE_ADD_TEXT, "＋ เพิ่มข้อความ", "คลิกตำแหน่งว่างเพื่อพิมพ์ข้อความใหม่"),
            (MODE_HIGHLIGHT, "🖍 ไฮไลท์", "ลากคลุมข้อความเพื่อไฮไลท์"),
            (MODE_PEN, "🖊 ปากกา", "ลากเมาส์วาดเส้นอิสระ (วงกลม/ขีดเส้นใต้เอกสาร)"),
            (MODE_SIGNATURE, "✍️ ลายเซ็น", "เลือก/สร้างลายเซ็น แล้วคลิกวางบนหน้า"),
            (MODE_IMAGE, "🖼 รูปภาพ", "เลือกรูป แล้วคลิกวางบนหน้า"),
            (MODE_COMMENT, "💬 คอมเมนต์", "คลิกบนหน้าเพื่อวางโน้ต / คลิกไอคอนเดิมเพื่อแก้"),
            (MODE_WHITEOUT, "⬜ ปิดทับ", "ลากคลุมพื้นที่เพื่อลบ/ปิดทับด้วยสีขาว"),
        ):
            btn = QToolButton()
            btn.setText(self.T(label))
            btn.setToolTip(self.T(tip))
            btn.setCheckable(True)
            if mode == MODE_SIGNATURE:
                btn.clicked.connect(self.tool_signature)   # open the picker every time
            elif mode == MODE_IMAGE:
                btn.clicked.connect(self.tool_image)       # open the picker every time
            elif mode == MODE_HIGHLIGHT:
                # highlight button doubles as a colour dropdown (swatches + custom)
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
                btn.clicked.connect(lambda _, md=mode: self.change_mode(md))
                btn.setMenu(self._make_highlight_menu())
            elif mode == MODE_COMMENT:
                # comment button doubles as a style dropdown (note / arrow / textbox)
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
                btn.clicked.connect(lambda _, md=mode: self.change_mode(md))
                btn.setMenu(self._make_comment_menu())
            elif mode == MODE_PEN:
                # pen button doubles as a colour dropdown
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
                btn.clicked.connect(lambda _, md=mode: self.change_mode(md))
                btn.setMenu(self._make_pen_menu())
            else:
                btn.clicked.connect(lambda _, md=mode: self.change_mode(md))
            tb2.addWidget(btn)
            self.mode_buttons[mode] = btn
        self.mode_buttons[MODE_VIEW].setChecked(True)
        self._refresh_hl_swatch()
        self._refresh_pen_swatch()

        # push the flag button to the far right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb2.addWidget(spacer)
        self.btn_lang = QToolButton()
        # show the flag of the language you will switch TO, styled to stand out
        self.btn_lang.setText("🇬🇧 EN" if self.lang == "th" else "🇹🇭 ไทย")
        self.btn_lang.setToolTip("คลิกเพื่อสลับภาษา ไทย/อังกฤษ\nSwitch language")
        self.btn_lang.setStyleSheet(
            "QToolButton { background: #1473e6; color: #ffffff; font-weight: 700;"
            " padding: 5px 14px; border-radius: 6px; margin: 0 4px; }"
            "QToolButton:hover { background: #0d5fc4; }")
        self.btn_lang.clicked.connect(self.toggle_language)
        tb2.addWidget(self.btn_lang)

    # named highlight colours shown in the dropdown
    HL_COLORS = [("เหลือง", "#ffeb3c"), ("เขียว", "#a5f36b"),
                 ("ฟ้า", "#7ecbff"), ("ชมพู", "#ff9ecb"),
                 ("ส้ม", "#ffc266")]

    def _make_comment_menu(self):
        from PyQt6.QtGui import QAction
        m = QMenu(self)
        for kind, label in (("note", "📌 โน้ต (คลิกวาง)"),
                            ("arrow", "➶ ลูกศรชี้ (ลาก)"),
                            ("textbox", "▭ กล่องข้อความ (ลาก)")):
            act = QAction(self.T(label), self)
            act.triggered.connect(lambda _=False, k=kind: self._set_comment_kind(k))
            m.addAction(act)
        return m

    def _set_comment_kind(self, kind):
        self.comment_kind = kind
        self.change_mode(MODE_COMMENT)
        how = {"note": "คลิกบนหน้าเพื่อวางโน้ต",
               "arrow": "ลากจากต้นทางไปปลายทางเพื่อวางลูกศรชี้",
               "textbox": "ลากกรอบเพื่อวางกล่องข้อความ"}[kind]
        self.status(f"โหมดคอมเมนต์: {how}")

    def add_page_numbers_ui(self):
        if not self.pdf.is_open():
            return self.need_file()
        from PyQt6.QtWidgets import QInputDialog
        styles = ["หน้า {n}", "{n}", "{n}/{total}", "หน้า {n} จาก {total}", "- {n} -"]
        fmt, ok = QInputDialog.getItem(
            self, "ใส่เลขหน้า", "รูปแบบเลขหน้า:", styles, 0, False)
        if not ok:
            return
        positions = {"ล่างกลาง": "bottom-center", "ล่างขวา": "bottom-right",
                     "ล่างซ้าย": "bottom-left", "บนกลาง": "top-center",
                     "บนขวา": "top-right"}
        pos_label, ok = QInputDialog.getItem(
            self, "ใส่เลขหน้า", "ตำแหน่ง:", list(positions), 0, False)
        if not ok:
            return
        try:
            self.pdf.add_page_numbers(self.current_font_path, positions[pos_label], fmt)
            self.render_page()
            self.status(f"ใส่เลขหน้าแล้ว ✓ ({self.pdf.page_count} หน้า, Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ใส่เลขหน้าไม่สำเร็จ:\n{e}")

    def tool_link_on_text(self):
        """Link-on-text mode: click a word/line and the link covers that text."""
        if not self.pdf.is_open():
            return self.need_file()
        self.change_mode(MODE_LINK)
        self.status("🔗 คลิกข้อความเพื่อใส่ลิงก์ / คลิกลิงก์เดิมเพื่อแก้หรือเอาออก "
                    "(หรือลากคลุมพื้นที่เองก็ได้)")

    def add_link_ui(self, rect):
        """Handle a click/drag in link mode. If it lands on an EXISTING link,
        offer to edit or remove it. Otherwise create a new link; a plain click
        snaps to the text span under it, a drag uses the dragged rectangle."""
        rect = fitz.Rect(rect).normalize()
        click = rect.width < 6 and rect.height < 6

        # clicking an existing link -> manage it (edit URL / remove)
        if click:
            existing = self.pdf.link_at(self.page_index, rect.tl)
            if existing:
                return self._manage_link(existing)

        if click:
            span = self.pdf.span_at(self.page_index, rect.tl)
            if span:
                rect = fitz.Rect(span["bbox"])
            else:
                self.status("คลิกไม่โดนข้อความ — ลากคลุมพื้นที่ที่จะใส่ลิงก์แทน")
                return
        url, ok = QInputDialog.getText(self, "เพิ่มลิงก์",
                                       "ใส่ลิงก์ (URL) เช่น https://example.com :")
        if not ok or not url.strip():
            return
        url = self._norm_url(url)
        try:
            self.pdf.add_link(self.page_index, rect, url)
            self.render_page()
            self.status(f"เพิ่มลิงก์ไปยัง {url} แล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"เพิ่มลิงก์ไม่สำเร็จ:\n{e}")

    @staticmethod
    def _norm_url(url):
        url = url.strip()
        if url and not url.startswith(("http://", "https://", "mailto:")):
            url = "https://" + url
        return url

    def _manage_link(self, link):
        """Dialog for an existing link: edit the URL or remove the link."""
        box = QMessageBox(self)
        box.setWindowTitle(self.T("จัดการลิงก์"))
        box.setText(f"ลิงก์นี้ชี้ไปที่:\n{link['uri']}\n\nต้องการทำอะไร?")
        edit_btn = box.addButton(self.T("แก้ไขลิงก์"), QMessageBox.ButtonRole.AcceptRole)
        del_btn = box.addButton(self.T("เอาลิงก์ออก"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.T("ยกเลิก"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == del_btn:
            self.pdf.delete_link(self.page_index, link["rect"])
            self.render_page()
            self.status("เอาลิงก์ออกแล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        elif clicked == edit_btn:
            url, ok = QInputDialog.getText(self, "แก้ไขลิงก์",
                                           "ใส่ลิงก์ใหม่:", text=link["uri"])
            if ok and url.strip():
                self.pdf.update_link(self.page_index, link["rect"],
                                     self._norm_url(url))
                self.render_page()
                self.status("แก้ไขลิงก์แล้ว ✓ (Ctrl+Z ย้อนกลับได้)")

    def place_comment_drag(self, p1, p2):
        """Place an arrow or text-box comment from a drag (p1..p2, PDF coords)."""
        kind = self.comment_kind
        dlg = CommentDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.text()
        try:
            self.pdf.add_comment(self.page_index, p1, text, kind=kind, end=p2)
            self.render_page()
            self.status("วางคอมเมนต์แล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"เพิ่มคอมเมนต์ไม่สำเร็จ:\n{e}")

    def _make_highlight_menu(self):
        from PyQt6.QtGui import QAction, QPixmap, QIcon
        m = QMenu(self)
        for label, hexc in self.HL_COLORS:
            pm = QPixmap(18, 18); pm.fill(QColor(hexc))
            act = QAction(QIcon(pm), self.T(label), self)
            act.triggered.connect(lambda _=False, h=hexc: self._set_highlight_color(QColor(h)))
            m.addAction(act)
        m.addSeparator()
        more = QAction(self.T("🎨 เลือกสีอื่น..."), self)
        more.triggered.connect(self.pick_highlight_color)
        m.addAction(more)
        return m

    def _set_highlight_color(self, qc):
        self.highlight_color = qc
        self._refresh_hl_swatch()
        self.change_mode(MODE_HIGHLIGHT)
        self.status(f"ตั้งสีไฮไลท์แล้ว — ลากคลุมข้อความได้เลย")

    def _refresh_hl_swatch(self):
        """Tint the highlight button so the current colour is visible."""
        btn = self.mode_buttons.get(MODE_HIGHLIGHT)
        if btn:
            c = self.highlight_color
            btn.setStyleSheet(
                "QToolButton { border-bottom: 3px solid %s; }" % c.name())

    def pick_highlight_color(self):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self.highlight_color, self, "เลือกสีไฮไลท์")
        if c.isValid():
            self._set_highlight_color(c)

    def _act(self, parent, text, slot, shortcut=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        parent.addAction(a)
        return a

    def status(self, msg):
        self.statusBar().showMessage(msg)

    def _update_undo_buttons(self):
        self.btn_undo.setEnabled(self.pdf.can_undo())
        self.btn_redo.setEnabled(self.pdf.can_redo())
        self.act_undo.setEnabled(self.pdf.can_undo())
        self.act_redo.setEnabled(self.pdf.can_redo())

    # ======================================================
    #  font
    # ======================================================
    @property
    def current_font_path(self):
        return self.fm.path(self.current_font)


    def _recent_list(self):
        return self.settings.value("recent", [], type=list)

    def _push_recent(self, path):
        lst = [p for p in self._recent_list() if p != path]
        lst.insert(0, path)
        self.settings.setValue("recent", lst[:MAX_RECENT])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.menu_recent.clear()
        lst = [p for p in self._recent_list() if os.path.exists(p)]
        if not lst:
            a = QAction("(ยังไม่มี)", self)
            a.setEnabled(False)
            self.menu_recent.addAction(a)
            return
        for p in lst:
            self._act(self.menu_recent, os.path.basename(p),
                      lambda _=False, pp=p: self._open_path(pp))

    def open_pdf(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "เปิดไฟล์ PDF", "", "PDF Files (*.pdf)")
        if path:
            self._open_path(path)

    def _open_path(self, path):
        err = self.pdf.open(path)
        if err == "password":
            pw, ok = QInputDialog.getText(self, "ไฟล์มีรหัสผ่าน", "กรอกรหัสผ่าน:",
                                          QLineEdit.EchoMode.Password)
            if not ok:
                return
            err = self.pdf.open(path, pw)
            if err:
                QMessageBox.warning(self, APP_NAME, "รหัสผ่านไม่ถูกต้อง")
                return
        elif err:
            QMessageBox.critical(self, APP_NAME, f"เปิดไฟล์ไม่สำเร็จ:\n{err}")
            return
        self.page_index = 0
        self._push_recent(path)
        self.refresh_all()
        if self.pdf.has_form():
            self.status(f"เปิดแล้ว: {os.path.basename(path)} "
                        f"({self.pdf.page_count} หน้า) — 📋 ไฟล์นี้เป็นแบบฟอร์ม "
                        f"คลิกช่องในโหมดแก้ข้อความเพื่อกรอก หรือใช้เมนู เครื่องมือ")
        else:
            self.status(f"เปิดแล้ว: {os.path.basename(path)}  ({self.pdf.page_count} หน้า)")

    def save_pdf(self):
        if not self.pdf.is_open():
            return
        if not self.pdf.path:
            return self.save_as_pdf()
        # about to overwrite the original -> warn and offer safer options
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.T("บันทึกทับไฟล์ต้นฉบับ?"))
        box.setText(self.T(
            "กำลังจะบันทึกทับไฟล์ต้นฉบับ\nข้อมูลเดิมจะถูกแทนที่"))
        box.setInformativeText(self.T(
            "แนะนำให้บันทึกเป็นไฟล์ใหม่ เพื่อเก็บต้นฉบับไว้"))
        newbtn = box.addButton(self.T("บันทึกเป็นไฟล์ใหม่ (แนะนำ)"),
                               QMessageBox.ButtonRole.AcceptRole)
        overbtn = box.addButton(self.T("บันทึกทับ (สำรองอัตโนมัติ)"),
                                QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.T("ยกเลิก"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(newbtn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == newbtn:
            return self.save_as_pdf()
        if clicked != overbtn:
            return
        try:
            backup = self.pdf.backup_version()      # keep a restorable copy first
            self.pdf.save()
            self.refresh_all()
            if backup:
                self.status("บันทึกทับแล้ว ✓ (สำรองเวอร์ชันเดิมไว้ให้ — "
                            "ดูได้ที่ ไฟล์ → ประวัติเวอร์ชัน)")
            else:
                self.status("บันทึกเรียบร้อย ✓")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"บันทึกไม่สำเร็จ:\n{e}")

    def show_version_history(self):
        """List automatic backups of the current file and let the user open one
        (opened as a separate copy - it never overwrites the current file)."""
        if not self.pdf.is_open() or not self.pdf.path:
            return self.need_file()
        versions = self.pdf.list_versions()
        if not versions:
            QMessageBox.information(
                self, self.T("ประวัติเวอร์ชัน"),
                self.T("ยังไม่มีเวอร์ชันสำรองของไฟล์นี้\n"
                       "(ระบบจะสำรองให้อัตโนมัติเมื่อคุณบันทึกทับไฟล์เดิม)"))
            return
        labels = [f"{v['label']}" for v in versions]
        choice, ok = QInputDialog.getItem(
            self, self.T("ประวัติเวอร์ชัน"),
            self.T("เลือกเวอร์ชันที่ต้องการเปิดดู/กู้คืน:"),
            labels, 0, False)
        if not ok:
            return
        picked = versions[labels.index(choice)]
        # confirm discarding current unsaved work before switching
        if self.pdf.modified and not self.confirm_discard():
            return
        try:
            original_path = self.pdf.path       # remember the real file
            err = self.pdf.open(picked["file"])
            if err:
                raise RuntimeError(err)
            # Keep pointing at the ORIGINAL file (not the backup copy) so a
            # normal Save writes the restored version back where the user
            # expects. This is safe because the save flow already (a) asks
            # overwrite-vs-new-file and (b) backs up the current on-disk
            # state into version history before overwriting - so nothing is
            # ever lost, and the user no longer gets forced into "Save As"
            # after restoring a version.
            self.pdf.path = original_path
            self.pdf.modified = True
            self.page_index = 0
            self.refresh_all()
            self.status(self.T(
                "เปิดเวอร์ชันเก่าแล้ว — กดบันทึก (Ctrl+S) เพื่อใช้เวอร์ชันนี้ "
                "(ระบบจะสำรองสถานะปัจจุบันให้ก่อนทับเสมอ)"))
        except Exception as e:
            QMessageBox.critical(self, APP_NAME,
                                 f"เปิดเวอร์ชันเก่าไม่สำเร็จ:\n{e}")

    def save_as_pdf(self):
        if not self.pdf.is_open():
            return
        path, sel = QFileDialog.getSaveFileName(
            self, "บันทึกเป็น", "",
            "PDF (*.pdf);;รูปภาพ PNG (*.png);;รูปภาพ JPG (*.jpg);;ข้อความ (*.txt)")
        if not path:
            return
        low = path.lower()
        try:
            # --- save as image ---
            if "png" in sel.lower() or "jpg" in sel.lower() or \
               low.endswith((".png", ".jpg", ".jpeg")):
                is_jpg = "jpg" in sel.lower() or low.endswith((".jpg", ".jpeg"))
                ext = ".jpg" if is_jpg else ".png"
                if not low.endswith((".png", ".jpg", ".jpeg")):
                    path += ext
                if self.pdf.page_count > 1:
                    ans = QMessageBox.question(
                        self, APP_NAME,
                        f"ไฟล์มี {self.pdf.page_count} หน้า\n"
                        "Yes = ส่งออกทุกหน้าเป็นไฟล์ ZIP เดียว (รูปครบทุกหน้าในนั้น)\n"
                        "No = เฉพาะหน้าปัจจุบันเป็นรูปเดียว")
                    if ans == QMessageBox.StandardButton.Yes:
                        # one tidy archive instead of dozens of loose images -
                        # easier to send to someone and nothing gets lost
                        zip_path = os.path.splitext(path)[0] + ".zip"
                        n = self.pdf.export_images_zip(
                            zip_path, fmt="jpg" if is_jpg else "png")
                        self.status(f"ส่งออก {n} หน้าเป็น ZIP: "
                                    f"{os.path.basename(zip_path)} ✓")
                        return
                self.pdf.export_image(self.page_index, path)
                self.status(f"บันทึกหน้า {self.page_index+1} เป็นรูปแล้ว ✓")
                return
            # --- save as text ---
            if "txt" in sel.lower() or low.endswith(".txt"):
                if not low.endswith(".txt"):
                    path += ".txt"
                self.pdf.export_all_text(path)
                self.status("ดึงข้อความทั้งไฟล์แล้ว ✓")
                return
            # --- save as PDF ---
            if not low.endswith(".pdf"):
                path += ".pdf"
            pages = self._ask_page_subset()
            if pages == "cancel":
                return
            if pages is not None:
                # exporting a subset: write a NEW file and keep working on the
                # original (self.pdf.path untouched), so the user doesn't
                # silently end up editing a one-page file afterwards
                n = self.pdf.save_pages(pages, path)
                self._push_recent(path)
                self.status(f"บันทึก {n} หน้า เป็น {os.path.basename(path)} แล้ว ✓ "
                            f"(ยังแก้ไขไฟล์เดิมอยู่)")
                return
            self.pdf.save(path)
            self._push_recent(path)
            self.render_page()
            self.status(f"บันทึกเป็น {os.path.basename(path)} แล้ว ✓")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"บันทึกไม่สำเร็จ:\n{e}")

    def _ask_page_subset(self):
        """Ask which pages a Save-As should contain.

        Returns None for "the whole document" (the plain save path), a list of
        0-based page indices for a subset, or the string "cancel". Skipped
        entirely for single-page files, where the question has one answer."""
        n = self.pdf.page_count
        if n <= 1:
            return None
        whole = self.T(f"ทั้งไฟล์ ({n} หน้า)")
        cur = self.T(f"เฉพาะหน้าปัจจุบัน (หน้า {self.page_index + 1})")
        custom = self.T("ระบุช่วงหน้าเอง เช่น 1-3,5,8-")
        choice, ok = QInputDialog.getItem(
            self, APP_NAME, self.T("บันทึกหน้าไหนลงไฟล์ใหม่?"),
            [whole, cur, custom], 0, False)
        if not ok:
            return "cancel"
        if choice == whole:
            return None
        if choice == cur:
            return [self.page_index]
        spec, ok = QInputDialog.getText(
            self, APP_NAME,
            self.T(f"ระบุหน้า (1-{n}) เช่น 1-3,5,8-\n"
                   f"เรียงลำดับได้ด้วย เช่น 3,1,2"),
            text=f"{self.page_index + 1}")
        if not ok:
            return "cancel"
        try:
            return self.pdf.parse_page_spec(spec, n)
        except ValueError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return "cancel"

    def save_encrypted(self):
        if not self.pdf.is_open():
            return self.need_file()
        pw, ok = QInputDialog.getText(self, "ตั้งรหัสผ่าน",
                                      "รหัสผ่านสำหรับเปิดไฟล์:", QLineEdit.EchoMode.Password)
        if not ok or not pw:
            return
        path, _ = QFileDialog.getSaveFileName(self, "บันทึกไฟล์ที่ล็อกรหัส", "",
                                              "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.pdf.save_encrypted(path, pw)
            self.status(f"บันทึกไฟล์พร้อมรหัสผ่านแล้ว: {os.path.basename(path)} ✓")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"บันทึกไม่สำเร็จ:\n{e}")

    @staticmethod
    def _parse_pages(text, maxpage):
        """Parse a page-range string like '1-3, 5, 8-10' into a list of page numbers
        (order and duplicates preserved)."""
        out = []
        for part in text.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                a, _, b = part.partition("-")
                if a.isdigit() and b.isdigit():
                    lo, hi = int(a), int(b)
                    rng = range(lo, hi + 1) if lo <= hi else range(lo, hi - 1, -1)
                    out += [n for n in rng if 1 <= n <= maxpage]
            elif part.isdigit():
                n = int(part)
                if 1 <= n <= maxpage:
                    out.append(n)
        return out

    def merge_pdf(self):
        if not self.pdf.is_open():
            return self.need_file()
        path, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์ PDF ที่จะนำมารวม", "",
                                              "PDF Files (*.pdf)")
        if not path:
            return
        # peek at the page count (supports password-protected files)
        n, need_pw = self.pdf.peek_page_count(path)
        pw = None
        if need_pw:
            pw, ok = QInputDialog.getText(self, "ไฟล์มีรหัสผ่าน",
                                          "กรอกรหัสผ่านของไฟล์ที่จะรวม:",
                                          QLineEdit.EchoMode.Password)
            if not ok:
                return
            n, _ = self.pdf.peek_page_count(path, pw)
            if n == 0:
                QMessageBox.warning(self, APP_NAME, "รหัสผ่านไม่ถูกต้อง")
                return

        # pick pages
        spec, ok = QInputDialog.getText(
            self, "เลือกหน้าที่จะรวม",
            f"ไฟล์นี้มี {n} หน้า — พิมพ์หน้าที่ต้องการ (เช่น 1-3, 5, 8)\n"
            f"เว้นว่าง = เอาทั้งหมด:")
        if not ok:
            return
        spec = spec.strip()
        pages = self._parse_pages(spec, n) if spec else None
        if spec and not pages:
            QMessageBox.warning(self, APP_NAME, "รูปแบบหน้าไม่ถูกต้องหรืออยู่นอกช่วง")
            return

        # pick insert position (1-based, no confusing "0")
        cur = self.pdf.page_count
        pos, ok = QInputDialog.getInt(
            self, "แทรกไว้ตำแหน่งใด",
            f"เอกสารมี {cur} หน้า — จะแทรกไว้ก่อนหน้าเลขใด?\n"
            f"(1 = ไว้หน้าแรกสุด, {cur + 1} = ต่อท้ายสุด)",
            cur + 1, 1, cur + 1)
        if not ok:
            return
        at = pos - 1        # merge_pages uses 0-based "insert after page `at`"
        try:
            added = self.pdf.merge_pages(path, pages, at=at, password=pw)
            self.page_index = at            # jump to the first inserted page
            self.refresh_all()
            what = f"{added} หน้า" + (f" (หน้า {spec})" if spec else " (ทั้งไฟล์)")
            self.status(f"รวม {what} แล้ว — ตอนนี้ทั้งหมด {self.pdf.page_count} หน้า ✓")
        except ValueError as e:
            msg = "ไม่มีหน้าที่เลือก" if str(e) != "password" else "รหัสผ่านไม่ถูกต้อง"
            QMessageBox.warning(self, APP_NAME, msg)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"รวมไฟล์ไม่สำเร็จ:\n{e}")

    def export_png(self):
        if not self.pdf.is_open():
            return self.need_file()
        path, _ = QFileDialog.getSaveFileName(
            self, "ส่งออกหน้าเป็นรูป", f"page_{self.page_index+1}.png",
            "PNG (*.png);;JPG (*.jpg)")
        if not path:
            return
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            path += ".png"
        self.pdf.export_image(self.page_index, path)
        self.status(f"ส่งออกหน้า {self.page_index+1} เป็นรูปแล้ว ✓")

    def export_text(self):
        if not self.pdf.is_open():
            return self.need_file()
        path, _ = QFileDialog.getSaveFileName(self, "บันทึกข้อความ", "extracted.txt",
                                              "Text (*.txt)")
        if not path:
            return
        self.pdf.export_all_text(path)
        self.status("ดึงข้อความทั้งไฟล์เรียบร้อย")

    def compress_pdfs(self):
        """Shrink PDFs - the open one and/or any others - in one batch run.

        The originals are never written over: every result is a new
        *_compressed.pdf, so a squeeze that came out too soft costs the user
        nothing but a delete. Whatever file is open is put in the list to save
        the usual trip through the file dialog.
        """
        import tempfile
        files, names, tmp = [], {}, None
        if self.pdf.is_open() and self.pdf.path:
            if self.pdf.modified:
                # Unsaved edits: compress exactly what is on screen. The old
                # flow asked "save first?" and then dropped the user into the
                # overwrite dialog - easy to end up compressing the stale
                # on-disk copy without noticing. A temp snapshot avoids both;
                # the result is still named <file>_compressed.pdf next to
                # the original and the original stays untouched.
                try:
                    fd, tmp = tempfile.mkstemp(prefix="wny_compress_",
                                               suffix=".pdf")
                    os.close(fd)
                    self.pdf.doc.save(tmp, garbage=1)
                    files.append(tmp)
                    names[tmp] = self.pdf.path
                except Exception:
                    tmp = None
                    files.append(self.pdf.path)
            else:
                files.append(self.pdf.path)

        dlg = CompressDialog(self, self.T, files, names)
        try:
            dlg.exec()
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if dlg.results:
            before = sum(r["before"] for r in dlg.results)
            after = sum(r["after"] for r in dlg.results)
            pct = (before - after) * 100.0 / before if before else 0
            self.status(self.T("บีบอัดแล้ว %d ไฟล์ — เล็กลง %.0f%% ✓")
                        % (len(dlg.results), pct))

    def export_word(self):
        """Convert the document to a .docx the user can open in Word."""
        if not self.pdf.is_open():
            return self.need_file()
        dlg = WordExportDialog(self, self.T, self.pdf.page_count,
                               self.page_index + 1)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        layout, spec, tables = dlg.values()

        pages = None
        if spec:
            nums = self._parse_pages(spec, self.pdf.page_count)
            if not nums:
                QMessageBox.warning(self, APP_NAME,
                                    self.T("รูปแบบหน้าไม่ถูกต้องหรืออยู่นอกช่วง"))
                return
            pages = [n - 1 for n in nums]

        stem = os.path.splitext(os.path.basename(self.pdf.path or "document"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, self.T("บันทึกเป็นไฟล์ Word"), stem + ".docx",
            "Word (*.docx)")
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"

        n_total = len(pages) if pages else self.pdf.page_count
        bar = QProgressDialog(self.T("กำลังแปลงเป็น Word..."), self.T("ยกเลิก"),
                              0, n_total, self)
        bar.setWindowTitle(APP_NAME)
        bar.setWindowModality(Qt.WindowModality.WindowModal)
        bar.setMinimumDuration(400)

        def tick(done, total):
            bar.setValue(done)
            QApplication.processEvents()
            return not bar.wasCanceled()

        try:
            stats = self.pdf.export_docx(path, layout=layout, pages=pages,
                                         tables=tables, progress=tick)
        except ExportCancelled:
            bar.close()
            try:
                os.remove(path)          # a half-written docx would not open
            except OSError:
                pass
            self.status(self.T("ยกเลิกการแปลงแล้ว"))
            return
        except Exception as e:
            bar.close()
            QMessageBox.critical(self, APP_NAME,
                                 self.T("แปลงเป็น Word ไม่สำเร็จ:\n%s") % e)
            return
        bar.setValue(n_total)
        bar.close()

        msg = self.T("แปลงเป็น Word แล้ว %d หน้า: %s ✓") % (
            stats["pages"], os.path.basename(path))
        self.status(msg)
        # Pages whose text could not be decoded went in as pictures. Say so now
        # rather than let the user find unselectable text later and assume the
        # converter mangled it.
        if stats["picture_pages"]:
            nums = ", ".join(str(p) for p in stats["picture_pages"][:12])
            more = "..." if len(stats["picture_pages"]) > 12 else ""
            QMessageBox.information(
                self, APP_NAME,
                self.T("แปลงเสร็จแล้ว แต่หน้า %s%s อ่านตัวอักษรจากไฟล์ PDF "
                       "ไม่ได้ (ไฟล์ต้นฉบับไม่ได้ฝังตารางรหัสตัวอักษรมา)\n\n"
                       "จึงใส่เป็นรูปภาพให้แทน เพื่อไม่ให้ได้ข้อความที่เพี้ยน")
                % (nums, more))

    # ======================================================
    #  Undo / Redo
    # ======================================================
    def _drop_stale_selection(self):
        """Undo/redo reloads the document: a selected span/image still holds
        its OLD bbox, so the next arrow-key nudge would erase the wrong area
        and rewrite the text somewhere else. Forget it instead."""
        self.selection = None
        self.page_view.sel_span = self.page_view.sel_img = None
        self.page_view.hover_span = self.page_view.hover_img = None

    def undo(self):
        if self.pdf.is_open() and self.pdf.undo():
            self._drop_stale_selection()
            self.refresh_all()
            self.status("เลิกทำแล้ว ↶")

    def redo(self):
        if self.pdf.is_open() and self.pdf.redo():
            self._drop_stale_selection()
            self.refresh_all()
            self.status("ทำซ้ำแล้ว ↷")

    # ======================================================
    #  rendering
    # ======================================================
    def refresh_all(self, keep_selection=False):
        if not keep_selection and self.multi_sel:
            self.multi_sel = []
        self.render_page()
        self.build_thumbnails()

    def render_page(self):
        if not self.pdf.is_open() or self.pdf.page_count == 0:
            self.page_view.clear()
            self.page_view.setText(
                self.T("เปิดไฟล์ PDF เพื่อเริ่มใช้งาน\n\n"
                       "📂 กด Ctrl+O  หรือ  ลากไฟล์ PDF มาวางที่นี่"))
            self._update_undo_buttons()
            return
        self.page_index = max(0, min(self.page_index, self.pdf.page_count - 1))
        # when the page actually changes, clear per-page overlays (selection
        # outline, drag box, comment drag) so a frame from page 1 never lingers
        # on top of page 2
        if getattr(self, "_rendered_page", -1) != self.page_index:
            self.selection = None
            self.page_view.sel_span = None
            self.page_view.sel_img = None
            self.page_view.drag_rect = None
            self.page_view.drag_start = None
            self.page_view.comment_drag = None
            self.page_view.pen_points = None
        self._rendered_page = self.page_index
        pix = self.pdf.render(self.page_index, self.zoom)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888)
        self.page_view.setPixmap(QPixmap.fromImage(img))

        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(self.pdf.page_count)
        self.page_spin.setValue(self.page_index + 1)
        self.page_spin.blockSignals(False)
        self.page_total.setText(f" / {self.pdf.page_count}  ")
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(f"{int(round(self.zoom * 100))}%")
        self.zoom_combo.blockSignals(False)

        if 0 <= self.page_index < self.thumbs.count():
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(self.page_index)
            self.thumbs.blockSignals(False)

        mod = "  ●" if self.pdf.modified else ""
        name = os.path.basename(self.pdf.path) if self.pdf.path else "ไม่มีชื่อ"
        self.setWindowTitle(f"{APP_NAME} — {name}{mod}")
        self._update_undo_buttons()

    def build_thumbnails(self):
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        if self.pdf.is_open():
            for i in range(self.pdf.page_count):
                pix = self.pdf.render(i, 0.17)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888)
                item = QListWidgetItem(QIcon(QPixmap.fromImage(img)), f"{i+1}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.thumbs.addItem(item)
            self.thumbs.setCurrentRow(self.page_index)
        self.thumbs.blockSignals(False)

    def _thumb_clicked(self, row):
        if row >= 0 and self.pdf.is_open():
            self.page_index = row
            self.render_page()

    def reorder_pages(self, src, dst):
        """Reorder pages by dragging thumbnails (called from ThumbnailList)."""
        if not self.pdf.is_open():
            return
        try:
            new_pos = self.pdf.reorder_page(src, dst)
            self.page_index = new_pos
            self.refresh_all()
            self.status(f"ย้ายหน้า {src + 1} ไปเป็นหน้า {new_pos + 1} แล้ว ✓ "
                        "(Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ย้ายหน้าไม่สำเร็จ:\n{e}")
            self.build_thumbnails()   # rebuild thumbnails to match the real state

    def set_zoom(self, z):
        self.zoom = max(0.25, min(z, 6.0))
        self.render_page()

    def fit_page(self):
        if not self.pdf.is_open():
            return
        rect = self.pdf.page_rect(self.page_index)
        avail_h = self.scroll.viewport().height() - 24
        avail_w = self.scroll.viewport().width() - 24
        self.set_zoom(min(avail_h / rect.height, avail_w / rect.width))

    def prev_page(self):
        if self.pdf.is_open() and self.page_index > 0:
            self.page_index -= 1
            self.render_page()

    def next_page(self):
        if self.pdf.is_open() and self.page_index < self.pdf.page_count - 1:
            self.page_index += 1
            self.render_page()

    def jump_page(self, val):
        if self.pdf.is_open():
            self.page_index = val - 1
            self.selection = None
            if hasattr(self, "page_view"):
                self.page_view.sel_span = self.page_view.sel_img = None
            self.render_page()

    # ======================================================
    #  text
    # ======================================================
    def _check_font_for(self, text):
        """Warn if the text contains Thai but no Thai font file is available."""
        if any("\u0e00" <= ch <= "\u0e7f" for ch in text) and not self.current_font_path:
            QMessageBox.warning(self, APP_NAME,
                                "ข้อความมีภาษาไทย แต่ไม่พบไฟล์ฟอนต์ไทย\n"
                                "กรุณาเลือกฟอนต์จากช่อง 'ฟอนต์' บนแถบเครื่องมือก่อน")
            return False
        return True

    def _use_font(self, name):
        """Remember the last font chosen in the text box as next time's default."""
        if name in self.fm:
            self.current_font = name
        return self.fm.path(name)

    def _use_font_styled(self, name, bold, italic):
        """Resolve (font path, faux_bold, faux_italic). Prefer a REAL bold/italic
        font file of the same family so the weight is detectable later (B button
        state) and re-bolding won't stack strokes; fall back to synthesised style
        only when the family has no such file."""
        if name in self.fm:
            self.current_font = name
        path = self.fm.variant_path(name, bold=bold, italic=italic)
        base = os.path.basename(path or "").lower()
        real_bold = any(w in base for w in ("bold", "black", "heavy"))
        real_ital = ("italic" in base) or ("oblique" in base)
        faux_bold = bold and not real_bold
        faux_ital = italic and not real_ital
        return path, faux_bold, faux_ital

    def _span_display_font(self, span):
        """Map a span's embedded font name to a bundled display name so the edit
        dialog shows the text's real family (falls back to the toolbar font)."""
        raw = (span.get("font") or "").split("+")[-1].lower()
        for w in ("bold", "italic", "oblique", "black", "heavy", "regular",
                  "-", "_", " "):
            raw = raw.replace(w, "")
        if raw:
            for name in self.fm.names():
                n = name.lower()
                for w in ("bold", "italic", "oblique", "black", "heavy",
                          "regular", "-", "_", " ", "✍", "(", ")"):
                    n = n.replace(w, "")
                if n and (n == raw or n.startswith(raw) or raw.startswith(n)):
                    return name
        return self.current_font

    def edit_text_at(self, point):
        # a fillable form box under the click wins over the printed label
        # behind it - clicking a form obviously means "fill it in"
        if self.fill_form_at(point):
            return
        span = self.pdf.span_at(self.page_index, point)
        if not span:
            self.status("ไม่พบข้อความตรงจุดที่คลิก — คลิกให้ตรงกรอบเส้นประ")
            return
        c = span.get("color", 0)
        span_color = QColor(c >> 16 & 255, c >> 8 & 255, c & 255)
        dlg = TextEditDialog(self, self.fm, "แก้ไขข้อความ",
                             "ข้อความเดิมจะถูกแทนที่ด้วยข้อความ/ฟอนต์/สีที่เลือก:",
                             span["text"], span["size"],
                             self._span_display_font(span),
                             color=span_color,
                             bold=self.pdf._span_is_bold(span),
                             italic=self.pdf._span_is_italic(span))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_text, size, fontname, qc, bold, italic = dlg.values()
        if not self._check_font_for(new_text):
            return
        # if the user kept the original font name, prefer the file's own embedded
        # font so the look is preserved even when that font isn't installed here
        keep_font = (fontname == self._span_display_font(span))
        try:
            fpath, faux_b, faux_i = self._use_font_styled(fontname, bold, italic)
            self.pdf.edit_span(self.page_index, span, new_text, size, fpath,
                               color=(qc.redF(), qc.greenF(), qc.blueF()),
                               bold=faux_b, italic=faux_i,
                               prefer_embedded=keep_font)
            self.render_page()
            self.status("แก้ไขข้อความแล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"แก้ไขไม่สำเร็จ:\n{e}")

    def move_text(self, span, dx, dy):
        try:
            # document prefers the embedded original font -> font won't change on its own
            self.pdf.move_span(self.page_index, span, dx, dy, self.current_font_path)
            self._clear_selection_overlay()
            self.render_page()
            self.status("ขยับข้อความแล้ว ✓ (คงฟอนต์เดิม / Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ขยับไม่สำเร็จ:\n{e}")

    def move_image_ui(self, info, dx, dy):
        """Move a placed image/signature."""
        try:
            self.pdf.move_image(self.page_index, info, dx, dy)
            self._clear_selection_overlay()
            self.render_page()
            self.status("ขยับรูป/ลายเซ็นแล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ขยับรูปไม่สำเร็จ:\n{e}")

    def _clear_selection_overlay(self):
        """Drop the selection/hover frames so no outline is left behind at the
        old position after a move, resize, edit or delete."""
        self.selection = None
        self.page_view.sel_span = None
        self.page_view.sel_img = None
        self.page_view.hover_span = None
        self.page_view.hover_img = None

    def delete_at(self, point):
        """Delete mode: click text or an image/signature to remove it."""
        span = self.pdf.span_at(self.page_index, point)
        if span:
            preview = span["text"][:40] + ("…" if len(span["text"]) > 40 else "")
            ans = QMessageBox.question(self, APP_NAME, f"ลบข้อความนี้?\n\n“{preview}”")
            if ans != QMessageBox.StandardButton.Yes:
                return
            try:
                self.pdf.delete_span(self.page_index, span)
                self.render_page()
                self.status("ลบข้อความแล้ว ✓")
            except Exception as e:
                QMessageBox.critical(self, APP_NAME, f"ลบไม่สำเร็จ:\n{e}")
            return
        info = self.pdf.image_at(self.page_index, point)
        if info:
            ans = QMessageBox.question(self, APP_NAME, "ลบรูปภาพ/ลายเซ็นนี้?")
            if ans != QMessageBox.StandardButton.Yes:
                return
            try:
                self.pdf.delete_image(self.page_index, info)
                self.render_page()
                self.status("ลบรูป/ลายเซ็นแล้ว ✓")
            except Exception as e:
                QMessageBox.critical(self, APP_NAME, f"ลบรูปไม่สำเร็จ:\n{e}")
            return
        com = self.pdf.comment_at(self.page_index, point)
        if com:
            ans = QMessageBox.question(self, APP_NAME, "ลบคอมเมนต์นี้?")
            if ans == QMessageBox.StandardButton.Yes:
                self.pdf.delete_comment(self.page_index, com["xref"])
                self.render_page()
                self.status("ลบคอมเมนต์แล้ว ✓")
            return
        ink = self.pdf.ink_at(self.page_index, point)
        if ink:
            ans = QMessageBox.question(self, APP_NAME, "ลบเส้นปากกานี้?")
            if ans == QMessageBox.StandardButton.Yes:
                self.pdf.delete_ink(self.page_index, ink)
                self.render_page()
                self.status("ลบเส้นปากกาแล้ว ✓")
            return
        self.status("ไม่พบข้อความ รูป คอมเมนต์ หรือเส้นปากกาตรงจุดที่คลิก")

    def add_text_at(self, point):
        dlg = TextEditDialog(self, self.fm, "เพิ่มข้อความใหม่",
                             "พิมพ์ข้อความ เลือกฟอนต์ ขนาด และสีได้ในกล่องนี้:",
                             "", self.font_size, self.current_font,
                             color=self.text_color)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text, size, fontname, qc, bold, italic = dlg.values()
        if not text.strip() or not self._check_font_for(text):
            return
        self.font_size = size
        self.text_color = qc
        color = (qc.redF(), qc.greenF(), qc.blueF())
        try:
            fpath, faux_b, faux_i = self._use_font_styled(fontname, bold, italic)
            self.pdf.add_text(self.page_index, point, text, size, color,
                              fpath, bold=faux_b, italic=faux_i)
            self.render_page()
            self.status("เพิ่มข้อความแล้ว ✓")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"เพิ่มข้อความไม่สำเร็จ:\n{e}")

    def add_highlight(self, rect):
        try:
            c = self.highlight_color
            self.pdf.highlight(self.page_index, rect,
                               color=(c.redF(), c.greenF(), c.blueF()))
            self.render_page()
            self.status("ไฮไลท์แล้ว ✓")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ไฮไลท์ไม่สำเร็จ:\n{e}")

    def apply_whiteout(self, rect):
        try:
            self.pdf.whiteout(self.page_index, rect)
            self.render_page()
            self.status("ปิดทับพื้นที่แล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ปิดทับไม่สำเร็จ:\n{e}")

    # ======================================================
    #  signature / image
    # ======================================================
    def _load_signatures(self):
        """Load the signature gallery from disk (persists across sessions)."""
        try:
            data = self.settings.value("signatures", [])
            out = []
            for b64 in (data or []):
                import base64
                out.append(base64.b64decode(b64))
            return out
        except Exception:
            return []

    def _save_signatures(self):
        try:
            import base64
            self.settings.setValue(
                "signatures",
                [base64.b64encode(p).decode("ascii") for p in self.saved_signatures])
        except Exception:
            pass

    def tool_signature(self):
        """Open the signature dialog - a gallery of saved signatures to reuse."""
        dlg = SignatureDialog(self, self.fm, last_png=self.signature_png,
                              saved=self.saved_signatures)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.signature_png = dlg.result_png
            self.signature_width = dlg.result_width
            # remove gallery items the user deleted (back to front to keep indices valid)
            for idx in sorted(set(dlg.deleted_saved), reverse=True):
                if 0 <= idx < len(self.saved_signatures):
                    self.saved_signatures.pop(idx)
            # save the new signature to the gallery (if ticked and not a duplicate)
            if dlg.result_save and dlg.result_png and \
                    dlg.result_png not in self.saved_signatures:
                self.saved_signatures.append(dlg.result_png)
                if len(self.saved_signatures) > 30:      # cap the size
                    self.saved_signatures.pop(0)
            self._save_signatures()
            self._ghost_cache.clear()
            self.change_mode(MODE_SIGNATURE)
        elif self.signature_png:
            self.change_mode(MODE_SIGNATURE)   # cancelled but a previous one exists -> keep using it
        else:
            self.change_mode(MODE_VIEW)

    def tool_image(self):
        """Pick a fresh image every time the image button is pressed."""
        path, _ = QFileDialog.getOpenFileName(self, "เลือกรูปภาพ", "",
                                              "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            with open(path, "rb") as f:
                self.image_png = f.read()
            w, ok = QInputDialog.getInt(self, "ขนาดรูป",
                                        "ความกว้างเมื่อวางลงหน้า (pt):",
                                        self.image_width, 20, 800)
            if ok:
                self.image_width = w
            self._ghost_cache.clear()
            self.change_mode(MODE_IMAGE)
        elif self.image_png:
            self.change_mode(MODE_IMAGE)       # cancelled but a previous image exists -> keep using it
        else:
            self.change_mode(MODE_VIEW)

    def adjust_stamp_width(self, delta):
        """Adjust the signature/image size before placing (mouse wheel)."""
        if self.mode == MODE_SIGNATURE:
            self.signature_width = max(20, min(800, self.signature_width + delta))
            self.status(f"ขนาดลายเซ็น: {self.signature_width} pt (หมุนลูกกลิ้งเพื่อปรับ)")
        elif self.mode == MODE_IMAGE:
            self.image_width = max(20, min(800, self.image_width + delta))
            self.status(f"ขนาดรูป: {self.image_width} pt (หมุนลูกกลิ้งเพื่อปรับ)")

    def resize_image_ui(self, info, new_rect):
        """Resize an image/signature by dragging a corner."""
        try:
            self.pdf.resize_image(self.page_index, info, new_rect)
            self._clear_selection_overlay()
            self.render_page()
            self.status("ปรับขนาดแล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ปรับขนาดไม่สำเร็จ:\n{e}")

    def resize_text_ui(self, span, scale):
        """Resize text by dragging a corner (font/colour kept)."""
        try:
            new_size = round(span["size"] * scale, 1)
            self.pdf.resize_span(self.page_index, span, new_size,
                                 self.current_font_path)
            self._clear_selection_overlay()
            self.render_page()
            self.status(f"ปรับขนาดข้อความเป็น {new_size:g} pt ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ปรับขนาดข้อความไม่สำเร็จ:\n{e}")

    def tool_symbol(self, kind):
        """Pick a symbol (check/cross/dot/circle/dash) and click to stamp it."""
        if not self.pdf.is_open():
            return self.need_file()
        self.image_png = symbol_image(kind)
        self.image_width = {"dot": 8, "check": 14, "cross": 12,
                            "circle": 22, "dash": 18}.get(kind, 14)
        self._ghost_cache.clear()
        self.change_mode(MODE_IMAGE)
        self.status("🔖 คลิกวางสัญลักษณ์ / หมุนลูกกลิ้งปรับขนาด / วางซ้ำได้หลายจุด")

    def tool_stamp(self):
        """Make an official-style text stamp, then click on the page to place it."""
        if not self.pdf.is_open():
            return self.need_file()
        presets = ["สำเนาถูกต้อง", "ต้นฉบับ", "ด่วนที่สุด", "ด่วนมาก", "ลับ",
                   f"ได้รับเอกสารเมื่อ\n{self._today_th()}",
                   "ผ่านการตรวจสอบแล้ว", "ยกเลิก", "พิมพ์ข้อความเอง..."]
        choice, ok = QInputDialog.getItem(self, "ตราประทับ",
                                          "เลือกข้อความตราประทับ:", presets, 0, False)
        if not ok:
            return
        if choice == "พิมพ์ข้อความเอง...":
            txt, ok = QInputDialog.getText(self, "ตราประทับ",
                                           "พิมพ์ข้อความ (ขึ้นบรรทัดใหม่ได้ด้วย \\n):")
            if not ok or not txt.strip():
                return
            choice = txt.replace("\\n", "\n")
        elif choice.startswith("ได้รับเอกสารเมื่อ"):
            # let the user confirm or change the date on a received-stamp
            date_str, ok = QInputDialog.getText(
                self, "ตราประทับ", "วันที่ (แก้ได้):", text=self._today_th())
            if not ok:
                return
            choice = f"ได้รับเอกสารเมื่อ\n{date_str.strip() or self._today_th()}"
        colors = {"แดง": (0.80, 0.13, 0.13), "น้ำเงิน": (0.10, 0.30, 0.75),
                  "เขียว": (0.13, 0.55, 0.25)}
        cname, ok = QInputDialog.getItem(self, "ตราประทับ", "สี:",
                                         list(colors), 0, False)
        if not ok:
            return
        self.image_png = stamp_text_image(choice, self.current_font_path,
                                          color=colors[cname])
        self.image_width = 90
        self._ghost_cache.clear()
        self.change_mode(MODE_IMAGE)
        self.status("📋 คลิกบนหน้าเพื่อวางตราประทับ / หมุนลูกกลิ้งปรับขนาด")

    def tool_enhance_scan(self):
        """Brighten / sharpen / straighten a scanned page."""
        if not self.pdf.is_open():
            return self.need_file()
        # this step turns the page into pixels, so warn if it holds real text
        if not self.pdf.is_scanned_page(self.page_index):
            ok = QMessageBox.question(
                self, self.T("ปรับแต่งรูปสแกน"),
                self.T("หน้านี้ไม่ใช่หน้าสแกน (มีข้อความจริงอยู่)\n\n"
                       "ถ้าปรับแต่ง ข้อความจะกลายเป็นรูปภาพ แก้ไขข้อความไม่ได้อีก\n"
                       "ต้องการทำต่อหรือไม่?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                return
        dlg = ScanEnhanceDialog(self, tr=self.T)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        brightness, contrast, angle = dlg.values()
        if not (brightness or contrast or angle):
            return
        try:
            self.pdf.enhance_scan(self.page_index, brightness, contrast, angle)
            self.refresh_all()
            self.status(self.T("ปรับแต่งรูปสแกนแล้ว ✓ (Ctrl+Z ย้อนกลับได้)"))
        except Exception as e:
            QMessageBox.critical(self, APP_NAME,
                                 f"{self.T('ปรับแต่งไม่สำเร็จ')}:\n{e}")

    def tool_qr(self):
        """Generate a QR code from text/URL, then click on the page to place it."""
        if not self.pdf.is_open():
            return self.need_file()
        data, ok = QInputDialog.getText(
            self, "สร้าง QR Code",
            "ใส่ลิงก์หรือข้อความที่จะเข้ารหัสใน QR:\n"
            "(เช่น https://... หรือเลขที่หนังสือ)")
        if not ok or not data.strip():
            return
        png = qr_png_bytes(data.strip())
        if not png:
            QMessageBox.warning(self, APP_NAME,
                                "สร้าง QR ไม่ได้ — ไม่พบไลบรารี qrcode\n"
                                "ติดตั้งด้วย: pip install qrcode")
            return
        self.image_png = png
        self.image_width = 70
        self._ghost_cache.clear()
        self.change_mode(MODE_IMAGE)
        self.status("🔳 คลิกบนหน้าเพื่อวาง QR Code / หมุนลูกกลิ้งปรับขนาด")

    @staticmethod
    def _today_th():
        """Today's date as a Thai-Buddhist-year string (d/m/พ.ศ.)."""
        from datetime import date
        d = date.today()
        return f"{d.day}/{d.month}/{d.year + 543}"

    def comment_click(self, point, existing=None):
        """Click in comment mode: on an existing icon = read/edit/delete, on empty = new."""
        if existing is None:
            existing = self.pdf.comment_at(self.page_index, point)
        if existing:
            dlg = CommentDialog(self, existing["text"], existing["author"],
                                allow_delete=True)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                if dlg.action == "delete":
                    self.pdf.delete_comment(self.page_index, existing["xref"])
                    self.status("ลบคอมเมนต์แล้ว ✓")
                elif dlg.text():
                    self.pdf.set_comment(self.page_index, existing["xref"], dlg.text())
                    self.status("แก้ไขคอมเมนต์แล้ว ✓")
                self.render_page()
            except Exception as e:
                QMessageBox.critical(self, APP_NAME, f"จัดการคอมเมนต์ไม่สำเร็จ:\n{e}")
            return
        if self.mode != MODE_COMMENT:
            return                      # view mode: read-only
        dlg = CommentDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.text():
            try:
                self.pdf.add_comment(self.page_index, point, dlg.text())
                self.render_page()
                self.status("วางคอมเมนต์แล้ว ✓ (ลากไอคอนเพื่อย้าย / คลิกเพื่ออ่าน-แก้-ลบ)")
            except Exception as e:
                QMessageBox.critical(self, APP_NAME, f"เพิ่มคอมเมนต์ไม่สำเร็จ:\n{e}")

    def move_comment_ui(self, comment, dx, dy):
        """Move a comment icon (called from dragging in PageView)."""
        try:
            self.pdf.move_comment(self.page_index, comment["xref"], dx, dy)
            self.render_page()
            self.status("ย้ายคอมเมนต์แล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ย้ายคอมเมนต์ไม่สำเร็จ:\n{e}")

    PEN_COLORS = [("น้ำเงิน", "#141e73"), ("ดำ", "#111116"),
                  ("แดง", "#c81e1e"), ("เขียว", "#1a7a3a")]

    def _make_pen_menu(self):
        from PyQt6.QtGui import QAction, QPixmap, QIcon
        m = QMenu(self)
        for label, hexc in self.PEN_COLORS:
            pm = QPixmap(18, 18); pm.fill(QColor(hexc))
            act = QAction(QIcon(pm), self.T(label), self)
            act.triggered.connect(lambda _=False, h=hexc: self._set_pen_color(QColor(h)))
            m.addAction(act)
        m.addSeparator()
        more = QAction(self.T("🎨 เลือกสีอื่น..."), self)
        more.triggered.connect(self._pick_pen_color)
        m.addAction(more)
        return m

    def _set_pen_color(self, qc):
        self.pen_color = qc
        self._refresh_pen_swatch()
        self.change_mode(MODE_PEN)
        self.status("ตั้งสีปากกาแล้ว — กดค้างแล้วลากวาดได้เลย")

    def _pick_pen_color(self):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self.pen_color, self, "เลือกสีปากกา")
        if c.isValid():
            self._set_pen_color(c)

    def _refresh_pen_swatch(self):
        btn = self.mode_buttons.get(MODE_PEN)
        if btn:
            btn.setStyleSheet(
                "QToolButton { border-bottom: 3px solid %s; }" % self.pen_color.name())

    def add_ink_ui(self, points):
        """Add the drawn pen stroke in the chosen colour."""
        try:
            c = self.pen_color
            self.pdf.add_ink(self.page_index, points,
                             color=(c.redF(), c.greenF(), c.blueF()))
            self.render_page()
            self.status("🖊 วาดแล้ว ✓ (ลบได้ในโหมดลบ / Ctrl+Z ย้อนกลับ)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"วาดไม่สำเร็จ:\n{e}")

    def stamp_preview(self):
        """QImage of the signature/image for the cursor preview."""
        data = self.signature_png if self.mode == MODE_SIGNATURE else self.image_png
        if not data:
            return None
        if data not in self._ghost_cache:
            img = QImage.fromData(data)
            self._ghost_cache.clear()
            self._ghost_cache[data] = img
        return self._ghost_cache[data]

    def stamp_width(self):
        return self.signature_width if self.mode == MODE_SIGNATURE else self.image_width

    def place_stamp(self, point, signature=True):
        if not self.pdf.is_open():
            return self.need_file()
        data = self.signature_png if signature else self.image_png
        if not data:
            self.tool_signature() if signature else self.tool_image()
            return
        try:
            self.pdf.insert_image(self.page_index, point, self.stamp_width(), data)
            self.render_page()
            what = "ลายเซ็น" if signature else "รูปภาพ"
            self.status(f"วาง{what}แล้ว ✓ (คลิกวางเพิ่มได้ / Ctrl+Z ย้อนกลับ)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"วางไม่สำเร็จ:\n{e}")

    # ======================================================
    #  other tools
    # ======================================================
    def add_watermark(self):
        if not self.pdf.is_open():
            return self.need_file()
        text, ok = QInputDialog.getText(self, "ใส่ลายน้ำ",
                                        "ข้อความลายน้ำ (จะแสดงเฉียงกลางหน้าทุกหน้า):")
        if not ok or not text.strip():
            return
        try:
            self.pdf.watermark(text.strip(), self.current_font_path)
            self.refresh_all()
            self.status("ใส่ลายน้ำทุกหน้าแล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ใส่ลายน้ำไม่สำเร็จ:\n{e}")

    def extract_pages(self):
        if not self.pdf.is_open():
            return self.need_file()
        n = self.pdf.page_count
        start, ok = QInputDialog.getInt(self, "แยกหน้า", "ตั้งแต่หน้า:",
                                        self.page_index + 1, 1, n)
        if not ok:
            return
        end, ok = QInputDialog.getInt(self, "แยกหน้า", "ถึงหน้า:", start, start, n)
        if not ok:
            return
        path, _ = QFileDialog.getSaveFileName(self, "บันทึกไฟล์ใหม่",
                                              f"pages_{start}-{end}.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.pdf.extract_pages(start, end, path)
            self.status(f"แยกหน้า {start}-{end} เป็นไฟล์ใหม่แล้ว ✓")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"แยกหน้าไม่สำเร็จ:\n{e}")

    # ======================================================
    #  page management
    # ======================================================
    def rotate_page(self, deg):
        if not self.pdf.is_open():
            return self.need_file()
        self.pdf.rotate_page(self.page_index, deg)
        self.refresh_all()

    def move_page(self, delta):
        if not self.pdf.is_open():
            return self.need_file()
        new_pos = self.pdf.move_page(self.page_index, delta)
        if new_pos != self.page_index:
            self.page_index = new_pos
            self.refresh_all()
            self.status(f"ย้ายหน้าไปตำแหน่งที่ {new_pos + 1} แล้ว ✓")

    def delete_page(self):
        if not self.pdf.is_open():
            return self.need_file()
        if self.pdf.page_count == 1:
            QMessageBox.warning(self, APP_NAME, "ลบไม่ได้ ไฟล์ต้องมีอย่างน้อย 1 หน้า")
            return
        ans = QMessageBox.question(self, APP_NAME, f"ยืนยันลบหน้า {self.page_index+1} ?")
        if ans == QMessageBox.StandardButton.Yes:
            self.pdf.delete_page(self.page_index)
            self.refresh_all()

    def insert_blank_page(self):
        if not self.pdf.is_open():
            return self.need_file()
        self.pdf.insert_blank(self.page_index)
        self.page_index += 1
        self.refresh_all()

    def search_text(self):
        """Open the floating search bar (stays open until ✕ or Esc)."""
        if not self.pdf.is_open():
            return self.need_file()
        self._position_search_bar()
        self.search_bar.show()
        self.search_bar.raise_()
        self.search_bar.focus_find(self._last_find)
        if self.search_bar.find():
            self.search_update()

    def _position_search_bar(self):
        """Place the search bar at the top-right of the document area."""
        self.search_bar.adjustSize()
        w = self.search_bar.width()
        vp = self.scroll.width()
        self.search_bar.move(max(8, vp - w - 24), 12)

    def search_update(self):
        """Collect every match in the file, highlight them, and jump to the first."""
        term = self.search_bar.find()
        self._last_find = term
        self.page_view.search_term = term
        self._search_hits = []
        if term:
            for pno in range(self.pdf.page_count):
                for r in self.pdf.find_on_page(pno, term):
                    self._search_hits.append((pno, r))
        if self._search_hits:
            # start at the first match on the current page or later
            self._search_idx = 0
            for i, (pno, _) in enumerate(self._search_hits):
                if pno >= self.page_index:
                    self._search_idx = i
                    break
            self._goto_hit()
        else:
            self._search_idx = -1
            self.search_bar.set_count(0, 0)
            self.render_page()

    def _goto_hit(self):
        """Jump to the match _search_idx points at and scroll it into view."""
        if not self._search_hits:
            return
        pno, rect = self._search_hits[self._search_idx]
        if pno != self.page_index:
            self.page_index = pno
        self.page_view.search_term = self.search_bar.find()
        self.render_page()
        self.search_bar.set_count(self._search_idx + 1, len(self._search_hits))
        # scroll the match into view
        try:
            sr = self.page_view.pdf_rect_to_screen(rect)
            self.scroll.ensureVisible(sr.center().x(), sr.center().y(), 80, 120)
        except Exception:
            pass
        self._position_search_bar()
        self.search_bar.raise_()

    def search_goto(self, direction):
        """Go to the next (+1) or previous (-1) match, wrapping around."""
        if not self.search_bar.isVisible():
            return
        # if the term changed but wasn't searched yet, search first
        if self.search_bar.find() != self.page_view.search_term:
            self.search_update()
            return
        if not self._search_hits:
            self.search_update()
            return
        n = len(self._search_hits)
        self._search_idx = (self._search_idx + direction) % n
        self._goto_hit()

    def search_replace_all(self):
        find = self.search_bar.find()
        repl = self.search_bar.repl()
        if not find:
            return
        n = self.pdf.count_matches(find)
        if n == 0:
            QMessageBox.information(self, APP_NAME, f"ไม่พบ “{find}” ในเอกสาร")
            return
        verb = "ลบ" if not repl else "แทนที่"
        ans = QMessageBox.question(
            self, APP_NAME,
            f"พบ “{find}” ทั้งหมด {n} จุด\n"
            f"ต้องการ{verb}เป็น “{repl or '(ว่าง)'}” ทั้งไฟล์หรือไม่?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            done = self.pdf.replace_text(find, repl, self.current_font_path)
            self.page_view.search_term = ""
            self._search_hits = []
            self._search_idx = -1
            self.search_bar.set_count(0, 0)
            self.render_page()
            self.status(f"{verb} “{find}” เป็น “{repl or '(ว่าง)'}” "
                        f"จำนวน {done} จุดแล้ว ✓ (Ctrl+Z ย้อนกลับได้)")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"แทนที่ไม่สำเร็จ:\n{e}")

    def search_close(self):
        """Close the search bar and clear all highlights."""
        self.search_bar.hide()
        self.page_view.search_term = ""
        self._search_hits = []
        self._search_idx = -1
        self.render_page()

    # ======================================================
    #  modes / misc
    # ======================================================
    def change_mode(self, mode):
        self.mode = mode
        if self.multi_sel:
            self.multi_sel = []
            self.page_view.update()
        for md, btn in self.mode_buttons.items():
            btn.setChecked(md == mode)
        cursors = {
            MODE_VIEW: Qt.CursorShape.ArrowCursor,
            MODE_EDIT_TEXT: Qt.CursorShape.PointingHandCursor,
            MODE_MOVE_TEXT: Qt.CursorShape.OpenHandCursor,
            MODE_DELETE_TEXT: Qt.CursorShape.PointingHandCursor,
            MODE_ADD_TEXT: Qt.CursorShape.IBeamCursor,
            MODE_HIGHLIGHT: Qt.CursorShape.CrossCursor,
            MODE_SIGNATURE: Qt.CursorShape.CrossCursor,
            MODE_IMAGE: Qt.CursorShape.CrossCursor,
            MODE_WHITEOUT: Qt.CursorShape.CrossCursor,
            MODE_LINK: Qt.CursorShape.CrossCursor,
            MODE_PEN: Qt.CursorShape.CrossCursor,
            MODE_COMMENT: Qt.CursorShape.PointingHandCursor,
        }
        self.page_view.setCursor(cursors[mode])
        self.page_view.hover_span = None
        self.page_view.hover_img = None
        # clear any selection outline so it never lingers after switching tools
        self.selection = None
        self.page_view.sel_span = None
        self.page_view.sel_img = None
        self.page_view.cursor_pos = None
        self.page_view.update()
        tips = {
            MODE_VIEW: "โหมดดู",
            MODE_EDIT_TEXT: "✏️ คลิกที่กรอบข้อความ (เส้นประ) เพื่อแก้ไข",
            MODE_MOVE_TEXT: "✥ ลากกลาง = ขยับ / ลากมุมส้มของรูป = ย่อ-ขยาย (คงสัดส่วน)",
            MODE_DELETE_TEXT: "🗑 คลิกข้อความหรือรูป/ลายเซ็นเพื่อลบออกจากไฟล์",
            MODE_ADD_TEXT: "＋ คลิกตำแหน่งที่ต้องการวางข้อความใหม่",
            MODE_HIGHLIGHT: "🖍 ลากเมาส์คลุมข้อความเพื่อไฮไลท์",
            MODE_SIGNATURE: "✍️ เลื่อนเมาส์ดูตัวอย่าง คลิกวาง / หมุนลูกกลิ้งปรับขนาด",
            MODE_IMAGE: "🖼 เลื่อนเมาส์ดูตัวอย่าง คลิกวาง / หมุนลูกกลิ้งปรับขนาด",
            MODE_WHITEOUT: "⬜ ลากคลุมพื้นที่ที่ต้องการลบ/ปิดทับ",
            MODE_LINK: "🔗 คลิกที่ข้อความ หรือลากคลุมพื้นที่ เพื่อใส่ลิงก์",
            MODE_PEN: "🖊 กดค้างแล้วลากเพื่อวาด — กด Shift ค้างเพื่อลากเส้นตรงยาวๆ (ลบได้ในโหมดลบ)",
            MODE_COMMENT: "💬 คลิกตำแหน่งที่ต้องการวางโน้ต / คลิกไอคอนเดิมเพื่ออ่าน-แก้-ลบ",
        }
        self.status(tips.get(mode, ""))

    def _apply_zoom_text(self, text):
        """Read a % from the zoom box (typed or picked from the list)."""
        try:
            v = int("".join(ch for ch in text if ch.isdigit()))
            if v > 0:
                self.set_zoom(v / 100.0)
                return
        except ValueError:
            pass
        self.zoom_combo.setCurrentText(f"{int(round(self.zoom * 100))}%")

    def zoom_step(self, direction):
        self.set_zoom(self.zoom * (1.2 if direction > 0 else 1 / 1.2))

    def keyPressEvent(self, ev):
        k = ev.key()
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if k == Qt.Key.Key_Escape:
            if self.search_bar.isVisible():
                self.search_close()
                return
            self.selection = None
            self.page_view.sel_span = None
            self.page_view.sel_img = None
            self.page_view.search_term = ""       # clear the search highlight
            self.page_view.update()
            self.change_mode(MODE_VIEW)
        elif k in arrows and self.selection is not None:
            # arrow keys nudge the selection (Shift = 5x, normally 1 pt)
            step = 5.0 if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
            ux, uy = arrows[k]
            self.nudge_selection(ux * step, uy * step)
        elif k == Qt.Key.Key_Delete and self.selection is not None:
            kind, item = self.selection
            try:
                if kind == "span":
                    self.pdf.delete_span(self.page_index, item)
                else:
                    self.pdf.delete_image(self.page_index, item)
                self.selection = None
                self.page_view.sel_span = self.page_view.sel_img = None
                self.render_page()
                self.status("ลบแล้ว ✓")
            except Exception as e:
                QMessageBox.critical(self, APP_NAME, f"ลบไม่สำเร็จ:\n{e}")
        elif k == Qt.Key.Key_PageDown:
            self.next_page()
        elif k == Qt.Key.Key_PageUp:
            self.prev_page()
        else:
            super().keyPressEvent(ev)

    # ---------- multi-selection (Ctrl+click) ----------
    def toggle_multi_select(self, span):
        """Add the span to the group selection, or remove it if already there."""
        key = (span["text"], tuple(round(v, 1) for v in span["bbox"]))
        for i, s in enumerate(self.multi_sel):
            if (s["text"], tuple(round(v, 1) for v in s["bbox"])) == key:
                self.multi_sel.pop(i)
                break
        else:
            self.multi_sel.append(span)
        # group selection replaces the single selection to avoid ambiguity
        # about what an arrow key should move
        self.selection = None
        self.page_view.sel_span = self.page_view.sel_img = None
        n = len(self.multi_sel)
        if n:
            self.status(self.T(f"เลือกไว้ {n} ข้อความ — ลากอันใดอันหนึ่ง หรือกดลูกศร "
                               f"เพื่อขยับทั้งกลุ่ม (Ctrl+คลิก เพิ่ม/เอาออก, คลิกเปล่า = ยกเลิก)"))
        else:
            self.status(self.T("ยกเลิกการเลือกกลุ่มแล้ว"))
        self.page_view.setFocus()
        self.page_view.update()

    def move_multi(self, dx, dy):
        """Move every span in the multi-selection by the same offset.

        Each span is re-found after its move (same text, nearest expected
        spot) so the selection survives the round-trip and the user can keep
        nudging. Sorted right-to-left / bottom-to-top before moving so a span
        never gets moved onto a group member that hasn't moved yet (which
        would drag it into the collateral-rewrite path unnecessarily)."""
        if not self.multi_sel:
            return
        order = sorted(self.multi_sel,
                       key=lambda s: (s["bbox"][0] * (1 if dx <= 0 else -1),
                                      s["bbox"][1] * (1 if dy <= 0 else -1)))
        new_sel = []
        for span in order:
            bb = fitz.Rect(span["bbox"])
            text = span["text"]
            try:
                self.pdf.move_span(self.page_index, span, dx, dy,
                                   self.current_font_path)
            except Exception:
                continue
            cx, cy = (bb.x0 + bb.x1) / 2 + dx, (bb.y0 + bb.y1) / 2 + dy
            cand = [s for s in self.pdf.spans(self.page_index)
                    if s["text"] == text]
            if cand:
                best = min(cand, key=lambda s: (
                    (fitz.Rect(s["bbox"]).x0 + fitz.Rect(s["bbox"]).x1) / 2 - cx) ** 2
                    + ((fitz.Rect(s["bbox"]).y0 + fitz.Rect(s["bbox"]).y1) / 2 - cy) ** 2)
                new_sel.append(best)
        self.multi_sel = new_sel
        self.refresh_all(keep_selection=True)
        self.status(self.T(f"ขยับ {len(new_sel)} ข้อความพร้อมกันแล้ว"))

    # ---------- form filling (AcroForm) ----------
    def fill_form_at(self, point):
        """If a fillable form field sits under `point`, open the right editor
        for its type and write the value back. Returns True when handled."""
        f = self.pdf.form_field_at(self.page_index, point)
        if not f:
            return False
        if f["type"] == "checkbox":
            self.pdf.set_form_field(self.page_index, f, not f["value"])
            self.refresh_all()
            self.status(self.T(f"สลับช่อง ☑ '{f['name']}' แล้ว"))
            return True
        cur = "" if f["value"] is None else str(f["value"])
        text, ok = QInputDialog.getMultiLineText(
            self, APP_NAME,
            self.T(f"กรอกช่อง: {f['name'] or '(ไม่มีชื่อ)'}"), cur)
        if ok:
            self.pdf.set_form_field(self.page_index, f, text)
            self.refresh_all()
            self.status(self.T("บันทึกค่าในฟอร์มแล้ว ✓"))
        return True

    def fill_form_dialog(self):
        """List every field in the document and let the user pick one to fill -
        for forms whose boxes are hard to hit by clicking."""
        if not self.need_file():
            return
        rows = []
        for pno in range(self.pdf.page_count):
            for f in self.pdf.form_fields(pno):
                rows.append((pno, f))
        if not rows:
            QMessageBox.information(self, APP_NAME,
                                    self.T("ไฟล์นี้ไม่มีช่องฟอร์มให้กรอก"))
            return
        labels = [f"หน้า {p+1}: {f['name'] or '(ไม่มีชื่อ)'} [{f['type']}] = "
                  f"{f['value'] if f['value'] not in (None, '') else '—'}"
                  for p, f in rows]
        choice, ok = QInputDialog.getItem(
            self, APP_NAME, self.T(f"ช่องฟอร์มทั้งหมด ({len(rows)}):"),
            labels, 0, False)
        if not ok:
            return
        pno, f = rows[labels.index(choice)]
        self.page_index = pno
        if f["type"] == "checkbox":
            self.pdf.set_form_field(pno, f, not f["value"])
        else:
            cur = "" if f["value"] is None else str(f["value"])
            text, ok = QInputDialog.getMultiLineText(
                self, APP_NAME, self.T(f"กรอกช่อง: {f['name']}"), cur)
            if not ok:
                return
            self.pdf.set_form_field(pno, f, text)
        self.refresh_all()
        self.status(self.T("บันทึกค่าในฟอร์มแล้ว ✓"))

    def select_item(self, point):
        """Select the clicked text/image (in move mode) for arrow-key nudging."""
        # a plain click always dissolves the Ctrl+click multi-selection -
        # matching how selection works everywhere else (file managers, Office)
        if self.multi_sel:
            self.multi_sel = []
            self.page_view.update()
        img = self.pdf.image_at(self.page_index, point)
        span = self.pdf.span_at(self.page_index, point)
        if img and span:
            span = None
        if span:
            self.selection = ("span", span)
            self.page_view.sel_span = span
            self.page_view.sel_img = None
            self.status("เลือกข้อความแล้ว — กดลูกศร ←↑↓→ ขยับทีละนิด "
                        "(Shift = เร็วขึ้น, Delete = ลบ)")
        elif img:
            self.selection = ("image", img)
            self.page_view.sel_img = img
            self.page_view.sel_span = None
            self.status("เลือกรูป/ลายเซ็นแล้ว — กดลูกศร ←↑↓→ ขยับทีละนิด "
                        "(Shift = เร็วขึ้น, Delete = ลบ)")
        else:
            self.selection = None
            self.page_view.sel_span = self.page_view.sel_img = None
        self.page_view.setFocus()      # so arrow keys go to nudging, not scrolling
        self.page_view.update()

    def nudge_selection(self, dx, dy):
        """Move the selection by (dx,dy) then re-find it to keep it selected."""
        if self.multi_sel:
            self.move_multi(dx, dy)
            return
        if self.selection is None:
            return
        kind, item = self.selection
        try:
            if kind == "span":
                bb = fitz.Rect(item["bbox"])
                text = item["text"]
                imgs_before = len(self.pdf.images(self.page_index))
                self.pdf.move_span(self.page_index, item, dx, dy,
                                   self.current_font_path)
                # re-find the same span (same text, nearest the new spot) to keep it selected
                cx, cy = (bb.x0 + bb.x1) / 2 + dx, (bb.y0 + bb.y1) / 2 + dy
                cand = [s for s in self.pdf.spans(self.page_index)
                        if s["text"] == text]
                if cand:
                    best = min(cand, key=lambda s: (
                        (fitz.Rect(s["bbox"]).x0 + fitz.Rect(s["bbox"]).x1) / 2 - cx) ** 2
                        + ((fitz.Rect(s["bbox"]).y0 + fitz.Rect(s["bbox"]).y1) / 2 - cy) ** 2)
                    self.selection = ("span", best)
                    self.page_view.sel_span = best
                elif len(self.pdf.images(self.page_index)) > imgs_before:
                    # the span was converted to an image (font couldn't be
                    # reproduced) -> select that image so further nudges work
                    imgs = self.pdf.images(self.page_index)
                    best = min(imgs, key=lambda i: (
                        (i["bbox"].x0 + i["bbox"].x1) / 2 - cx) ** 2
                        + ((i["bbox"].y0 + i["bbox"].y1) / 2 - cy) ** 2)
                    self.selection = ("image", best)
                    self.page_view.sel_span = None
                    self.page_view.sel_img = best
            else:
                bb = item["bbox"]
                self.pdf.move_image(self.page_index, item, dx, dy)
                cx, cy = bb.x0 + dx, bb.y0 + dy
                imgs = self.pdf.images(self.page_index)
                if imgs:
                    best = min(imgs, key=lambda i: (i["bbox"].x0 - cx) ** 2
                               + (i["bbox"].y0 - cy) ** 2)
                    self.selection = ("image", best)
                    self.page_view.sel_img = best
            self.render_page()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"ขยับไม่สำเร็จ:\n{e}")

    def need_file(self):
        QMessageBox.information(self, APP_NAME, "กรุณาเปิดไฟล์ PDF ก่อน")

    def confirm_discard(self):
        """Ask before losing unsaved changes. Returns True if it is OK to proceed
        (close/open another file), False to stay. Offers Save / Don't Save / Cancel
        so 'Don't Save' really does close the program."""
        if not (self.pdf.is_open() and self.pdf.modified):
            return True
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("มีการแก้ไขที่ยังไม่ได้บันทึก")
        box.setInformativeText("ต้องการบันทึกก่อนหรือไม่?")
        btn_save = box.addButton("💾 บันทึก", QMessageBox.ButtonRole.AcceptRole)
        btn_discard = box.addButton("ไม่บันทึก", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton("ยกเลิก", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_cancel:
            return False                 # stay
        if clicked is btn_discard:
            return True                  # close without saving
        # Save chosen -> try to save; only proceed if it actually succeeded
        try:
            if self.pdf.path:
                self.pdf.save()
            else:
                self.save_as_pdf()
                if self.pdf.modified:    # user cancelled the Save-As dialog
                    return False
            return True
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"บันทึกไม่สำเร็จ:\n{e}")
            return False

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "search_bar", None) and self.search_bar.isVisible():
            self._position_search_bar()

    def closeEvent(self, ev):
        if self.confirm_discard():
            # release the document and delete every temp font file this
            # session extracted, so the OS temp dir doesn't accumulate them
            try:
                self.pdf.close()
            except Exception:
                pass
            ev.accept()
        else:
            ev.ignore()

    def about(self):
        if self.lang == "en":
            QMessageBox.about(self, f"About {APP_NAME}",
                              f"<h3>{APP_NAME} v{VERSION}</h3>"
                              "<p>A PDF reader &amp; editor.</p>"
                              "<p>Edit/move/delete/add text • Highlight • Signatures<br>"
                              "Insert images • White-out • Watermark • Password • Undo/Redo<br>"
                              "Page management • Merge/Split • Find/Replace</p>"
                              f"<p><b>Fonts:</b> {len(self.fm)} bundled "
                              "(incl. the full TH Sarabun family)</p>"
                              "<p>Built with Python + PyQt6 + PyMuPDF</p>")
        else:
            QMessageBox.about(self, f"เกี่ยวกับ {APP_NAME}",
                              f"<h3>{APP_NAME} v{VERSION}</h3>"
                              "<p>โปรแกรมอ่านและแก้ไขไฟล์ PDF</p>"
                              "<p>แก้ไข/ขยับ/ลบ/เพิ่มข้อความ • ไฮไลท์ • ลายเซ็น 3 แบบ<br>"
                              "แทรกรูปภาพ • ปิดทับ • ลายน้ำ • รหัสผ่าน • Undo/Redo<br>"
                              "จัดการหน้า • รวม/แยกไฟล์ • ค้นหา/แทนที่</p>"
                              f"<p><b>ฟอนต์:</b> {len(self.fm)} แบบ (รวม TH Sarabun ทุกตระกูล)</p>"
                              "<p>พัฒนาด้วย Python + PyQt6 + PyMuPDF</p>")


def run():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    QLocale.setDefault(_ARABIC_LOCALE)   # Arabic digits app-wide
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":     # in case this file is run directly
    run()
