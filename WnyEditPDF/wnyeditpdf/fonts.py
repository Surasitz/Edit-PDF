# -*- coding: utf-8 -*-
"""FontManager - collects and manages fonts used to write into PDFs."""

import os
import platform

from .config import resource_path

# fonts bundled with the app (display name -> file in the fonts/ folder)
BUNDLED = [
    ("TH Sarabun New",              "THSarabunNew.ttf"),
    ("TH Sarabun New Bold",         "THSarabunNew-Bold.ttf"),
    ("TH SarabunPSK",               "THSarabunPSK.ttf"),
    ("TH SarabunPSK Bold",          "THSarabunPSK-Bold.ttf"),
    ("TH SarabunPSK Italic",        "THSarabunPSK-Italic.ttf"),
    ("TH SarabunPSK BoldItalic",    "THSarabunPSK-BoldItalic.ttf"),
    ("TH Sarabun IT๙ (เลขไทย)",      "THSarabunIT9.ttf"),
    ("TH Sarabun IT๙ Bold",         "THSarabunIT9-Bold.ttf"),
    ("TH Sarabun IT๙ Italic",       "THSarabunIT9-Italic.ttf"),
    ("TH Sarabun IT๙ BoldItalic",   "THSarabunIT9-BoldItalic.ttf"),
    ("Sarabun (Google)",            "Sarabun-Regular.ttf"),
    ("Sarabun (Google) Bold",       "Sarabun-Bold.ttf"),
    ("Sarabun (Google) Italic",     "Sarabun-Italic.ttf"),
    ("Sarabun (Google) BoldItalic", "Sarabun-BoldItalic.ttf"),
    ("Sarabun (Google) Light",      "Sarabun-Light.ttf"),
    ("Sarabun (Google) Medium",     "Sarabun-Medium.ttf"),
    ("Sarabun (Google) SemiBold",   "Sarabun-SemiBold.ttf"),
    ("✍ ลายเซ็น Pachautid N",        "B2_SIGN_Pachautid_N.ttf"),
    ("✍ ลายเซ็น Pachautid S",        "B2_SIGN_Pachautid_S.ttf"),
    ("✍ ลายมือ SOV JD RungReung",    "SOV_JD_RungReung.ttf"),
    ("✍ ลายมือ SOV Rataphan 2498",   "SOV_rataphan2498.ttf"),
    ("KJR Aksornsart (Demo)",       "KJR_AKSORNSART_DEMO.ttf"),
]

# OS Thai fonts (fallback)
SYSTEM_FONTS = {
    "Windows": [
        ("Leelawadee UI", "LeelawUI.ttf"), ("Tahoma", "tahoma.ttf"),
        ("Angsana New", "angsa.ttf"), ("Cordia New", "cordia.ttc"),
        ("Arial", "arial.ttf"),
    ],
    "Darwin": [
        ("Thonburi", "/System/Library/Fonts/Supplemental/Thonburi.ttc"),
        ("Arial Unicode", "/Library/Fonts/Arial Unicode.ttf"),
    ],
    "Linux": [
        ("Loma", "/usr/share/fonts/opentype/tlwg/Loma.otf"),
        ("Garuda", "/usr/share/fonts/opentype/tlwg/Garuda.otf"),
        ("Noto Sans Thai", "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"),
        ("DejaVu Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ],
}


class FontManager:
    """Collect every font: bundled + system + user-added."""

    def __init__(self):
        self._fonts = {}   # display name -> file path
        self._collect()

    def _collect(self):
        for name, fname in BUNDLED:
            p = resource_path(os.path.join("fonts", fname))
            if os.path.exists(p):
                self._fonts[name] = p

        # auto-scan the fonts/ folder so any .ttf/.otf/.ttc dropped in there shows
        # up in the picker without editing this file. The BUNDLED list above only
        # sets nicer display names; everything else is named from its file.
        self._scan_folder(resource_path("fonts"))

        system = platform.system()
        entries = SYSTEM_FONTS.get(system, SYSTEM_FONTS["Linux"])
        for name, f in entries:
            if system == "Windows":
                f = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", f)
            if os.path.exists(f):
                self._fonts.setdefault(name, f)

    def _scan_folder(self, folder):
        """Add every font file in `folder` that isn't already registered, using a
        readable display name derived from the file name."""
        if not folder or not os.path.isdir(folder):
            return
        known = {os.path.abspath(p) for p in self._fonts.values()}
        for fname in sorted(os.listdir(folder)):
            if not fname.lower().endswith((".ttf", ".otf", ".ttc")):
                continue
            full = os.path.abspath(os.path.join(folder, fname))
            if full in known:
                continue
            display = self._display_name(fname)
            # avoid clobbering a nicer BUNDLED name for the same display text
            if display in self._fonts:
                continue
            self._fonts[display] = full

    @staticmethod
    def _display_name(fname):
        """Turn a font file name into a friendly picker label."""
        stem = os.path.splitext(fname)[0]
        nice = {"tahoma": "Tahoma", "tahomabd": "Tahoma Bold",
                "arial": "Arial", "arialbd": "Arial Bold"}
        if stem.lower() in nice:
            return nice[stem.lower()]
        # normalise separators to spaces, keep Thai 'TH ' family names readable
        stem = stem.replace("_", " ").replace("-", " ")
        stem = " ".join(stem.split())               # collapse repeated spaces
        return stem

    # ---------- queries ----------
    def names(self):
        return list(self._fonts.keys())

    def path(self, name):
        return self._fonts.get(name)

    def variant_path(self, name, bold=False, italic=False):
        """Return the real font file for the bold/italic variant of `name`
        when the family has one bundled (e.g. TH Sarabun New -> its Bold file);
        otherwise return the plain path so the caller can fall back to faux style.

        Using a real bold file (instead of synthesised faux-bold) means the
        weight is detectable afterwards, so the B button reflects the true state
        and pressing it again won't stack extra strokes."""
        base = self.path(name)
        if not (bold or italic):
            return base
        if not base:
            return base

        def norm(fp):
            n = os.path.basename(fp).lower()
            for ch in " -_.":
                n = n.replace(ch, "")
            return n.replace("regular", "").replace("ttf", "").replace("otf", "")

        want = norm(base)
        best = None   # (score, path); higher score = better match
        for fp in self._fonts.values():
            n = norm(fp)
            # must share the family stem (strip style words for the comparison)
            stem = n
            for w in ("bold", "italic", "oblique", "black", "heavy"):
                stem = stem.replace(w, "")
            base_stem = want
            for w in ("bold", "italic", "oblique", "black", "heavy"):
                base_stem = base_stem.replace(w, "")
            if stem != base_stem:
                continue
            has_bold = any(w in n for w in ("bold", "black", "heavy"))
            has_ital = ("italic" in n) or ("oblique" in n)
            if has_bold == bool(bold) and has_ital == bool(italic):
                return fp        # exact style match
            # partial credit (e.g. want bold+italic but only bold exists)
            score = (has_bold == bool(bold)) + (has_ital == bool(italic))
            if best is None or score > best[0]:
                best = (score, fp)
        # only use a partial match if it actually adds the requested weight/slant
        if best and norm(best[1]) != want:
            return best[1]
        return base

    def default_name(self):
        """Default font (first Sarabun found)."""
        return next(iter(self._fonts), None)

    def signature_default(self):
        """Default signature font."""
        for n in self._fonts:
            if n.startswith("✍"):
                return n
        return self.default_name()

    # ---------- user-added fonts ----------
    def add(self, path):
        """Add a font from a .ttf/.otf file; return its display name."""
        disp = os.path.splitext(os.path.basename(path))[0]
        self._fonts[disp] = path
        return disp

    def __contains__(self, name):
        return name in self._fonts

    def __len__(self):
        return len(self._fonts)
