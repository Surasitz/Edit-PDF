# -*- coding: utf-8 -*-
"""Line icons for the toolbar and tool panel.

The SVGs in assets/icons are Lucide icons (ISC licence, see
assets/icons/LICENSE-lucide.txt). They are drawn with ``stroke="currentColor"``,
so one file serves every tint: the colour is substituted before rendering, the
way the tool families are colour-coded in the tool panel.
"""

import os

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from .config import resource_path

ICON_DIR = os.path.join("wnyeditpdf", "assets", "icons")
DEFAULT = "#3b3f46"

_svg_cache = {}
_icon_cache = {}


def _svg(name):
    if name not in _svg_cache:
        try:
            with open(resource_path(os.path.join(ICON_DIR, name + ".svg")), encoding="utf-8") as f:
                _svg_cache[name] = f.read()
        except OSError:
            _svg_cache[name] = None
    return _svg_cache[name]


def pixmap(name, color=DEFAULT, size=20, stroke=None, ratio=2.0):
    """The icon drawn at ``size`` logical pixels (rendered at ``ratio`` for
    sharp edges on high-DPI screens). A missing icon gives an empty pixmap."""
    px = int(size * ratio)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    svg = _svg(name)
    if svg:
        svg = svg.replace("currentColor", color)
        if stroke:
            svg = svg.replace('stroke-width="2"', 'stroke-width="%s"' % stroke)
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        p = QPainter(pm)
        r.render(p, QRectF(0, 0, px, px))
        p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name, color=DEFAULT, size=20, active=None):
    """A QIcon; ``active`` is the colour used while the button is checked."""
    key = (name, color, size, active)
    if key not in _icon_cache:
        ic = QIcon(pixmap(name, color, size))
        if active:
            ic.addPixmap(pixmap(name, active, size), QIcon.Mode.Normal, QIcon.State.On)
        _icon_cache[key] = ic
    return _icon_cache[key]
