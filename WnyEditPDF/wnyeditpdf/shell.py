# -*- coding: utf-8 -*-
"""The left tool panel, laid out like the new Acrobat / PdfCraft window:
"All tools" lists every tool family in its colour; a family - or a mode tab
such as Edit, Convert or E-Sign - opens its tools as one-click rows. Built
from catalog.GROUPS, so a new tool only needs a catalogue entry."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea,
                             QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import catalog
from .icons import icon


class ToolPanel(QFrame):
    WIDTH = 268

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("toolPanel")
        self.setFixedWidth(self.WIDTH)
        self.view = ("home", None, None)          # what rebuild() redraws

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 6, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(2)
        self.back = QToolButton()
        self.back.setObjectName("panelBtn")
        self.back.setIcon(icon("chevron-left", size=18))
        self.back.clicked.connect(lambda: self.win.set_tab("all"))
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("panelBtn")
        self.close_btn.setIcon(icon("x", size=18))
        self.close_btn.clicked.connect(win.hide_tool_panel)
        head.addWidget(self.back)
        head.addWidget(self.title, 1)
        head.addWidget(self.close_btn)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("panelScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)
        self.show_home()

    def _fresh(self):
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 2, 4, 6)
        v.setSpacing(1)
        # the body keeps the height its rows need, so a long list scrolls
        # instead of being squeezed until the rows overlap
        v.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll.setWidget(body)                # the previous body is deleted
        return v

    @staticmethod
    def _fit(widget, height):
        """A fixed row height, any width: a long label may clip at the right
        edge (its tooltip has the full text) but never widens the panel."""
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        widget.setFixedHeight(height)

    def _row(self, layout, text, icon_name, hue, slot, obj="toolRow", tip=""):
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setIcon(icon(icon_name, hue, 20))
        b.setIconSize(QSize(20, 20))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fit(b, 38 if obj == "groupRow" else 34)
        b.setToolTip(tip or text)
        b.clicked.connect(slot)
        layout.addWidget(b)
        return b

    def show_home(self):
        T = self.win.T
        self.view = ("home", None, None)
        self.title.setText(T("เครื่องมือทั้งหมด"))
        self.back.hide()
        v = self._fresh()
        for g in catalog.GROUPS:
            self._row(v, T(g.label), g.icon, g.hue,
                      lambda _=False, gid=g.id: self.show_groups([gid]), "groupRow", T(g.desc))
        v.addStretch(1)

    def show_groups(self, ids, title=None):
        T = self.win.T
        self.view = ("groups", list(ids), title)
        groups = [catalog.BY_ID[i] for i in ids]
        self.title.setText(T(title or groups[0].label))
        self.back.show()
        v = self._fresh()
        for g in groups:
            if len(groups) > 1:
                lab = QLabel(T(g.label))
                lab.setObjectName("panelGroup")
                self._fit(lab, 36)
                v.addWidget(lab)
            for sec_title, items in g.sections:
                lab = QLabel(T(sec_title))
                lab.setObjectName("panelSection")
                self._fit(lab, 30)
                v.addWidget(lab)
                for it in items:
                    self._row(v, T(it.label), it.icon, g.hue,
                              lambda _=False, item=it: self.win.run_tool(item))
        v.addStretch(1)

    def rebuild(self):
        """Redraw the current view (after the language changes)."""
        kind, ids, title = self.view
        if kind == "home":
            self.show_home()
        else:
            self.show_groups(ids, title)
