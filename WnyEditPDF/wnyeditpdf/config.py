# -*- coding: utf-8 -*-
"""Constants, colour theme and tool modes for WnyEditPDF."""

import os
import sys

APP_NAME = "WnyEditPDF"
VERSION = "5.8.1"
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

ADOBE_BLUE = "#1473e6"   # Acrobat-style blue
CANVAS_GRAY = "#4b4d52"  # canvas background around the page


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
"""
