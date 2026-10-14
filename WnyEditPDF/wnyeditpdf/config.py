# -*- coding: utf-8 -*-
"""Constants, colour theme and tool modes for WnyEditPDF."""

import os
import sys

APP_NAME = "WnyEditPDF"
VERSION = "6.0.0"
ORG_NAME = "WnyEdit"

# ---------- tool modes ----------
MODE_VIEW = 0        # select / view
MODE_EDIT_TEXT = 1   # click existing text to edit
MODE_MOVE_TEXT = 2   # drag existing text to a new spot
MODE_DELETE_TEXT = 3 # click existing text to delete
MODE_ADD_TEXT = 4    # click empty space to add text
MODE_HIGHLIGHT = 5   # drag to highlight
MODE_SIGNATURE = 6   # click to place a signature
MODE_IMAGE = 7       # click to place an image
MODE_WHITEOUT = 8    # drag an area to white it out (removes everything inside)
MODE_PEN = 9         # pen: drag to draw freehand
MODE_COMMENT = 10    # comment: click to drop a sticky note
MODE_LINK = 11       # link: drag a box then enter a URL
MODE_FORM = 12       # form field: drag a box to add a fillable field

ADOBE_BLUE = "#1473e6"   # Acrobat-style blue
CANVAS_GRAY = "#e4e7eb"  # canvas background around the page (light, the page casts a soft shadow)


def resource_path(rel):
    """Resolve a resource path for both normal runs and PyInstaller bundles."""
    base = getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


STYLE = f"""
* {{ font-family: 'Segoe UI', 'Tahoma', 'Noto Sans Thai', sans-serif; font-size: 13px; }}
QMainWindow {{ background: #ffffff; }}
QDialog, QMessageBox, QTabWidget, QWidget#tabPage {{ background: #ffffff; color: #2c2c2c; }}

QMenuBar {{ background: #ffffff; color: #2c2c2c; border-bottom: 1px solid #e1e3e6; padding: 1px; }}
QMenuBar::item {{ padding: 6px 12px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: #e8f1fd; color: {ADOBE_BLUE}; }}
QMenu {{ background: #ffffff; color: #2c2c2c; border: 1px solid #d5d7db; border-radius: 6px; padding: 5px; }}
QMenu::item {{ padding: 7px 28px 7px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: #e8f1fd; color: {ADOBE_BLUE}; }}
QMenu::separator {{ height: 1px; background: #e1e3e6; margin: 5px 8px; }}

QToolBar {{ background: #f6f7f9; border: none; border-bottom: 1px solid #d5d7db;
            padding: 4px 6px; spacing: 2px; }}
QToolBar::separator {{ background: #d5d7db; width: 1px; margin: 5px 7px; }}
QToolButton {{ background: transparent; color: #3b3b3b; border: none;
               border-radius: 5px; padding: 6px 10px; }}
QToolButton:hover {{ background: #e4e6ea; color: #1a1a1a; }}
QToolButton:pressed {{ background: #d8dadf; }}
QToolButton:checked {{ background: {ADOBE_BLUE}; color: #ffffff; }}
QToolButton:disabled {{ color: #b6b9be; }}

QPushButton {{ background: {ADOBE_BLUE}; color: #ffffff; border: none;
               border-radius: 5px; padding: 8px 20px; font-weight: 600; }}
QPushButton:hover {{ background: #2b82ea; }}
QPushButton:pressed {{ background: #0d66d0; }}
QPushButton[flat="true"] {{ background: transparent; color: {ADOBE_BLUE}; }}

QLabel {{ color: #3b3b3b; }}
QStatusBar {{ background: #f6f7f9; color: #6b6f76; border-top: 1px solid #d5d7db; }}

QScrollArea {{ background: {CANVAS_GRAY}; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {CANVAS_GRAY}; }}
QScrollBar:vertical {{ background: transparent; width: 13px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #9a9da3; border-radius: 5px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: #7e8187; }}
QScrollBar:horizontal {{ background: transparent; height: 13px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #9a9da3; border-radius: 5px; min-width: 40px; }}
QScrollBar::handle:horizontal:hover {{ background: #7e8187; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListWidget {{ background: #fafbfc; border: none; border-right: 1px solid #e1e3e6;
               padding: 6px; outline: none; }}
QListWidget::item {{ background: transparent; border: 2px solid transparent;
                     border-radius: 6px; margin: 4px 2px; padding: 5px; color: #55585e; }}
QListWidget::item:hover {{ background: #eef0f3; }}
QListWidget::item:selected {{ background: #e8f1fd; border: 2px solid {ADOBE_BLUE};
                              color: {ADOBE_BLUE}; }}

QSpinBox, QLineEdit, QPlainTextEdit, QComboBox {{
    background: #ffffff; color: #2c2c2c; border: 1px solid #c9ccd1;
    border-radius: 5px; padding: 5px 8px; selection-background-color: {ADOBE_BLUE}; }}
QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 1px solid {ADOBE_BLUE}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: #ffffff; color: #2c2c2c;
    border: 1px solid #c9ccd1; selection-background-color: #e8f1fd;
    selection-color: {ADOBE_BLUE}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}

QTabWidget::pane {{ border: 1px solid #d5d7db; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: #f0f1f4; color: #55585e; padding: 8px 18px;
                border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: #ffffff; color: {ADOBE_BLUE}; font-weight: 600;
                         border: 1px solid #d5d7db; border-bottom: none; }}

QSplitter::handle {{ background: #e1e3e6; width: 1px; }}

QDoubleSpinBox {{ background: #ffffff; color: #2c2c2c; border: 1px solid #c9ccd1;
    border-radius: 5px; padding: 5px 8px; }}
QDoubleSpinBox:focus {{ border: 1px solid {ADOBE_BLUE}; }}
QTreeWidget, QTextBrowser {{ background: #ffffff; color: #2c2c2c; border: 1px solid #d5d7db;
    border-radius: 6px; padding: 4px; }}
QTreeWidget::item {{ padding: 4px 2px; }}
QTreeWidget::item:selected {{ background: #e8f1fd; color: {ADOBE_BLUE}; }}
QHeaderView::section {{ background: #f6f7f9; color: #55585e; border: none;
    border-bottom: 1px solid #e1e3e6; padding: 6px 8px; font-weight: 600; }}
QCheckBox, QRadioButton {{ color: #2c2c2c; spacing: 7px; padding: 2px 0; }}
QProgressDialog {{ background: #ffffff; }}

/* ---------- welcome screen ---------- */
QWidget#welcome {{ background: {CANVAS_GRAY}; }}
QFrame#welcomeCard {{ background: #ffffff; border-radius: 14px; }}
QLabel#welcomeTitle {{ color: {ADOBE_BLUE}; font-size: 30px; font-weight: 700; }}
QLabel#welcomeSub {{ color: #6b6f76; font-size: 14px; }}
QLabel#welcomeHead {{ color: #2c2c2c; font-size: 15px; font-weight: 700; padding-top: 10px; }}
QPushButton#welcomeOpen {{ font-size: 15px; padding: 12px 28px; border-radius: 8px; }}
QPushButton#welcomeRecent {{ background: transparent; color: #2c2c2c; font-weight: 400;
    text-align: left; padding: 7px 10px; border-radius: 6px; }}
QPushButton#welcomeRecent:hover {{ background: #e8f1fd; color: {ADOBE_BLUE}; }}
QPushButton#welcomeTool {{ background: #f6f7f9; color: #2c2c2c; font-weight: 600;
    text-align: left; padding: 10px 14px; border: 1px solid #e1e3e6; border-radius: 10px; }}
QPushButton#welcomeTool:hover {{ background: #e8f1fd; border: 1px solid {ADOBE_BLUE};
    color: {ADOBE_BLUE}; }}
QLabel#toolName {{ color: #1f2937; font-size: 14px; font-weight: 700; background: transparent; }}
QLabel#toolDesc {{ color: #6b6f76; font-size: 12px; background: transparent; }}

/* ---------- top bar: menu, mode tabs, tool search ---------- */
QToolBar#topBar {{ background: #ffffff; border: none; border-bottom: 1px solid #e5e7eb;
    padding: 2px 10px; spacing: 4px; }}
QToolButton#menuBtn {{ color: #1f2937; font-weight: 600; padding: 7px 12px; }}
QToolButton#menuBtn::menu-indicator {{ image: none; }}
QToolButton#modeTab {{ color: #4b5563; font-size: 14px; padding: 12px 12px 10px 12px;
    border-radius: 0; border-bottom: 2px solid transparent; background: transparent; }}
QToolButton#modeTab:hover {{ color: #111827; background: transparent; }}
QToolButton#modeTab:checked {{ color: #111827; font-weight: 700; background: transparent;
    border-bottom: 2px solid #111827; }}
QPushButton#searchBox {{ background: #f3f4f6; color: #6b7280; border: 1px solid #e5e7eb;
    border-radius: 17px; padding: 7px 16px; font-weight: 400; text-align: left; min-width: 280px; }}
QPushButton#searchBox:hover {{ border: 1px solid {ADOBE_BLUE}; background: #ffffff; }}
QToolButton#topIcon {{ padding: 7px; border-radius: 7px; }}
QToolButton#langBtn {{ background: #eef4fe; color: {ADOBE_BLUE}; font-weight: 700;
    padding: 6px 12px; border-radius: 14px; margin-left: 4px; }}
QToolButton#langBtn:hover {{ background: #dbe8fd; }}

/* ---------- left tool panel ---------- */
QFrame#toolPanel {{ background: #ffffff; border: none; border-right: 1px solid #e5e7eb; }}
QLabel#panelTitle {{ color: #111827; font-size: 16px; font-weight: 700; }}
QLabel#panelSection {{ color: #6b7280; font-size: 12px; font-weight: 600; padding: 12px 8px 3px 8px; }}
QLabel#panelGroup {{ color: #111827; font-size: 14px; font-weight: 700; padding: 14px 8px 0 8px; }}
QPushButton#toolRow, QPushButton#groupRow {{ background: transparent; color: #1f2937;
    font-weight: 400; text-align: left; padding: 8px 10px; border-radius: 7px; }}
QPushButton#groupRow {{ font-size: 14px; padding: 9px 10px; }}
QPushButton#toolRow:hover, QPushButton#groupRow:hover {{ background: #f1f5fd; color: {ADOBE_BLUE}; }}
QToolButton#panelBtn {{ padding: 4px; border-radius: 6px; }}
QScrollArea#panelScroll, QScrollArea#panelScroll > QWidget > QWidget {{ background: #ffffff; border: none; }}

/* ---------- floating tool rail beside the page ---------- */
QWidget#canvas {{ background: {CANVAS_GRAY}; }}
QFrame#rail {{ background: #ffffff; border: 1px solid #dfe3e8; border-radius: 12px; }}
QToolButton#railBtn {{ padding: 7px; border-radius: 8px; margin: 1px 0; }}
QToolButton#railBtn:hover {{ background: #f1f3f6; }}
QToolButton#railBtn:checked {{ background: #e3edfd; }}
QToolButton#railBtn[popupMode="1"] {{ padding-right: 14px; }}
QFrame#railSep {{ background: #e5e7eb; max-height: 1px; min-height: 1px; margin: 4px 6px; }}

/* ---------- page thumbnails (right) and status-bar controls ---------- */
QListWidget#thumbs {{ border-right: none; border-left: 1px solid #e5e7eb; background: #fafbfc; }}
QToolButton#navBtn {{ padding: 3px 5px; border-radius: 5px; }}
QStatusBar QSpinBox, QStatusBar QComboBox {{ padding: 2px 6px; }}

/* ---------- Ctrl+K command search ---------- */
QDialog#palette {{ background: #ffffff; border: 1px solid #c9ccd1; border-radius: 10px; }}
QLineEdit#paletteEdit {{ font-size: 16px; padding: 10px 12px; border-radius: 8px; }}
QListWidget#paletteList {{ background: #ffffff; border: none; padding: 2px; }}
QListWidget#paletteList::item {{ border: none; border-radius: 6px; margin: 1px 0;
    padding: 8px 10px; color: #2c2c2c; }}
QListWidget#paletteList::item:selected {{ background: #e8f1fd; color: {ADOBE_BLUE}; border: none; }}
"""
