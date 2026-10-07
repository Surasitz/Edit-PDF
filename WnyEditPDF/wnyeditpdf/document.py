# -*- coding: utf-8 -*-
"""PdfDocument - a PyMuPDF wrapper: read / edit / save with Undo/Redo."""

import math
import os
import random
import re
import tempfile
import fitz  # PyMuPDF

MAX_UNDO = 25


def _unique_png(data):
    """Give an image a unique 'pixel fingerprint' by nudging 4 random pixels by 1.
    PyMuPDF identifies images by pixel digest, so identical images collapse to
    one xref; this keeps signatures placed in several spots individually editable.
    Colour is only stored for opaque pixels (transparent ones are dropped into
    the smask), so we poke a colour channel of opaque pixels plus the alpha."""
    try:
        pix = fitz.Pixmap(data)
        if pix.alpha:
            done = 0
            for _ in range(4000):          # find 4 pixels opaque enough
                if done >= 4:
                    break
                x = random.randrange(pix.width)
                y = random.randrange(pix.height)
                px = list(pix.pixel(x, y))
                if px[-1] > 8:             # opaque enough that colour is kept in base
                    px[random.randrange(len(px) - 1)] ^= 1   # colour channel -> base
                    px[-1] ^= 1                              # alpha channel -> smask
                    pix.set_pixel(x, y, tuple(px))
                    done += 1
            if done == 0:                  # fully transparent image (almost never happens)
                for _ in range(4):
                    x = random.randrange(pix.width)
                    y = random.randrange(pix.height)
                    px = list(pix.pixel(x, y))
                    px[-1] ^= 1
                    pix.set_pixel(x, y, tuple(px))
        else:
            for _ in range(4):
                x = random.randrange(pix.width)
                y = random.randrange(pix.height)
                px = list(pix.pixel(x, y))
                px[random.randrange(len(px))] ^= 1
                pix.set_pixel(x, y, tuple(px))
        return pix.tobytes("png")
    except Exception:
        return data


# clockwise display rotation -> the same turn expressed as a content-stream
# `cm` in PDF user space (y axis pointing UP)
_ROT_CM = {90: (0, -1, 1, 0), 180: (-1, 0, 0, -1), 270: (0, 1, -1, 0)}


def _pdf_box(doc, page, key):
    """A page box (/MediaBox, /CropBox ...) in raw PDF coordinates, or None."""
    try:
        t, v = doc.xref_get_key(page.xref, key)
        if t == "array":
            return fitz.Rect([float(x) for x in v.strip("[]").split()]).normalize()
    except Exception:
        pass
    return None


_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)")


def _turn_annot_geometry(doc, xref, m):
    """Apply matrix `m` (PDF coords) to an annotation's /Rect and point lists."""
    def turn_points(s):
        nums = [float(x) for x in _NUM.findall(s)]
        out = []
        for i in range(0, len(nums) - 1, 2):
            p = fitz.Point(nums[i], nums[i + 1]) * m
            out += [p.x, p.y]
        return " ".join("%g" % v for v in out)

    try:
        t, v = doc.xref_get_key(xref, "Rect")
        if t == "array":
            r = fitz.Rect([float(x) for x in _NUM.findall(v)][:4]).normalize()
            doc.xref_set_key(xref, "Rect", "[%g %g %g %g]" % tuple((r * m).normalize()))
        for key in ("QuadPoints", "L", "Vertices", "CL"):
            t, v = doc.xref_get_key(xref, key)
            if t == "array":
                doc.xref_set_key(xref, key, "[" + turn_points(v) + "]")
        t, v = doc.xref_get_key(xref, "InkList")
        if t == "array":
            strokes = re.findall(r"\[([^\[\]]*)\]", v)
            doc.xref_set_key(xref, "InkList", "[" + " ".join(
                "[" + turn_points(s) + "]" for s in strokes) + "]")
    except Exception:
        pass


def bake_page_rotation(page):
    """Turn a /Rotate page into an upright (Rotate 0) page that LOOKS identical.

    Why: scanners and phone apps (typical for ID-card scans) save a sideways
    image and set /Rotate 90 instead of rotating the pixels. On such a page
    the viewer coordinates (what the user clicks) are rotated against the
    PDF coordinates that insert_text / annotations / get_text use, so every
    new text came out sideways (vertical) in the wrong spot, highlights and
    comments landed elsewhere, and clicking existing text missed. Baking the
    turn into the content stream makes both coordinate systems the same.

    PyMuPDF's own Page.remove_rotation() loses or shifts a /CropBox that
    differs from the /MediaBox, so this does the maths in raw PDF space.
    Returns the page (reloaded) - the old page object must not be reused."""
    rot = page.rotation
    if rot not in _ROT_CM:
        return page
    doc = page.parent
    # new fitz coords == old viewer coords, so links and form fields (which
    # live in fitz coordinates) move by rotation_matrix. Read them BEFORE the
    # boxes change.
    to_view = fitz.Matrix(page.rotation_matrix)
    annots = [a.xref for a in page.annots() or []]
    # fixed-size icons (sticky notes) get re-anchored by MuPDF on reload;
    # remember where they must end up
    icons = {a.xref: a.rect * to_view for a in page.annots() or []
             if a.type[0] == fitz.PDF_ANNOT_TEXT}
    links = []
    for lk in page.get_links():
        lk = dict(lk)
        lk["from"] = fitz.Rect(lk["from"]) * to_view
        links.append(lk)
    widgets = []
    for w in page.widgets() or []:
        widgets.append((w.xref, w.rect * to_view))

    mb = _pdf_box(doc, page, "MediaBox") or fitz.Rect(page.mediabox)
    a, b, c, d = _ROT_CM[rot]
    t = fitz.Matrix(a, b, c, d, 0, 0)
    nm = (mb * t).normalize()
    t = t * fitz.Matrix(1, 0, 0, 1, -nm.x0, -nm.y0)     # keep the origin at 0,0

    fmt = "[%g %g %g %g]"
    # annotations: turn their geometry (raw PDF coords) with the same matrix.
    # set_rect() is not enough - highlights / ink / lines are defined by
    # point lists, and some types refuse set_rect() altogether.
    for xref in annots:
        _turn_annot_geometry(doc, xref, t)
    doc.xref_set_key(page.xref, "MediaBox", fmt % tuple((mb * t).normalize()))
    for key in ("CropBox", "TrimBox", "BleedBox", "ArtBox"):
        box = _pdf_box(doc, page, key)
        if box is not None:
            doc.xref_set_key(page.xref, key, fmt % tuple((box * t).normalize()))
    doc.xref_set_key(page.xref, "Rotate", "0")
    # wrap the old content in q <turn> cm ... Q so later additions are upright
    cm = ("q %g %g %g %g %g %g cm\n" % tuple(t)).encode()
    fitz.TOOLS._insert_contents(page, cm, False)
    fitz.TOOLS._insert_contents(page, b"\nQ\n", True)

    page = doc.reload_page(page)
    redraw = (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE,
              fitz.PDF_ANNOT_STRIKE_OUT, fitz.PDF_ANNOT_SQUIGGLY,
              fitz.PDF_ANNOT_INK, fitz.PDF_ANNOT_LINE, fitz.PDF_ANNOT_POLYGON,
              fitz.PDF_ANNOT_POLY_LINE, fitz.PDF_ANNOT_SQUARE,
              fitz.PDF_ANNOT_CIRCLE)
    for xref in annots:
        try:                       # redraw the appearance from the new geometry
            annot = page.load_annot(xref)
            if annot.type[0] in redraw:
                annot.update()
            elif xref in icons:
                annot.set_rect(icons[xref])
        except Exception:
            pass
    for lk in links:
        try:
            page.delete_link(lk)
            page.insert_link(lk)
        except Exception:
            pass
    if widgets:
        want = dict(widgets)
        for w in page.widgets() or []:
            if w.xref in want:
                try:
                    w.rect = want[w.xref]
                    w.update()
                except Exception:
                    pass
    return page


def _qimage_to_png(img):
    """Encode a QImage as PNG bytes."""
    from PyQt6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _rotated_png(data, deg):
    """Rotate the image pixels by the given angle (for non-90-degree placements)."""
    if abs(deg) < 0.5:
        return data
    try:
        from PyQt6.QtGui import QImage, QTransform
        from PyQt6.QtCore import QBuffer, QIODevice, Qt
        img = QImage.fromData(data)
        img = img.transformed(QTransform().rotate(deg),
                              Qt.TransformationMode.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data())
    except Exception:
        return data


def _placement_rotation(m):
    """Read the rotation angle from an image-placement matrix.
    Returns (rotate_param, bake_deg): if it snaps to 90 use insert_image's
    rotate=, otherwise bake the rotation into the pixels (bake_deg)."""
    ang = math.degrees(math.atan2(m.b, m.a))
    snap = round(ang / 90.0) * 90
    if abs(ang - snap) <= 1.5:
        return int(-snap) % 360, 0.0
    return 0, ang


def int_to_rgb(c):
    """Convert a PyMuPDF colour int to a 0-1 tuple."""
    return ((c >> 16 & 255) / 255.0, (c >> 8 & 255) / 255.0, (c & 255) / 255.0)


class PdfDocument:
    def __init__(self):
        self.doc = None
        self.path = None
        self.modified = False
        self._undo = []
        self._redo = []
        self._span_cache = {}     # page number -> list of spans
        self._fontfile_cache = {} # font xref -> extracted font file path
        self._font_obj_cache = {} # font path -> fitz.Font (for glyph checks)
        self._temp_fonts = []     # temp font files we created (cleaned on close)
        self.default_thai_font = None  # full Thai font (safety net), set by window
        self.bundled_fonts = {}   # normalised name -> bundled full font path (set by window)

    def _cached_font(self, fontpath):
        """A fitz.Font for `fontpath`, cached. Font files are immutable once
        written (repairs create NEW files with a _fixed suffix), so caching by
        path is safe and saves re-parsing the same 100-200KB file on every
        glyph check / width measurement - which happens several times per move."""
        f = self._font_obj_cache.get(fontpath)
        if f is None:
            f = fitz.Font(fontfile=fontpath)
            self._font_obj_cache[fontpath] = f
        return f

    def _register_temp(self, path):
        """Track a temp font file for deletion when the document is closed or a
        new one is opened. Without this every open session leaks the extracted
        subsets and their repaired copies into the OS temp dir (a busy editing
        session creates dozens at ~100-200KB each)."""
        if path:
            self._temp_fonts.append(path)
        return path

    def _cleanup_temp_fonts(self):
        for p in self._temp_fonts:
            try:
                os.remove(p)
            except Exception:
                pass
        self._temp_fonts.clear()
        self._font_obj_cache.clear()
        self._fontfile_cache.clear()

    def close(self):
        """Release the document and every temp file it produced."""
        try:
            if self.doc:
                self.doc.close()
        except Exception:
            pass
        self.doc = None
        self._cleanup_temp_fonts()

    def __del__(self):
        try:
            self._cleanup_temp_fonts()
        except Exception:
            pass

    def _match_bundled(self, span_font_name):
        """Map a span's font name to a bundled full font of the SAME family+weight.
        Used as a fallback when the embedded (subset) font cannot be re-written, so
        the weight is preserved instead of dropping to the toolbar font. Bold/italic
        aware so bold does not silently become regular.

        Matching is done against each bundled font's FILE name (e.g.
        'Sarabun-Bold.ttf'), not its friendly display name (e.g.
        'Sarabun (Google) Bold') - the file name is the reliable, punctuation-free
        form that lines up with how PDFs name their fonts."""
        if not span_font_name or not self.bundled_fonts:
            return None

        def norm(s):
            s = s.split("+")[-1].lower()
            # drop everything that isn't a letter or digit (spaces, hyphens,
            # parentheses, the word 'google', etc.)
            import re
            s = re.sub(r"\(.*?\)", "", s)            # remove (google) and similar
            s = re.sub(r"[^a-z0-9]", "", s)
            return s.replace("regular", "")

        def style(s):
            s = s.lower()
            return ("bold" in s or "black" in s or "heavy" in s or "semibold" in s,
                    "italic" in s or "oblique" in s)

        def weight_class(s):
            """Coarse weight bucket so a Regular request does not silently accept
            a Medium file. Both Sarabun-Medium and Sarabun-Light used to score
            mismatch=0 against 'Sarabun' because they were neither bold nor
            italic - and the loop then picked whichever came first, thickening
            or thinning the moved text."""
            s = s.lower()
            if "thin" in s or "hairline" in s:
                return 100
            if "extralight" in s or "ultralight" in s:
                return 200
            if "light" in s:
                return 300
            if "medium" in s:
                return 500
            if "semibold" in s or "demibold" in s:
                return 600
            if "bold" in s or "heavy" in s or "black" in s:
                return 700
            return 400   # regular / book / normal

        def family(s):                               # strip style words to compare
            for w in ("bold", "italic", "oblique", "black", "heavy",
                      "semibold", "demibold", "extralight", "ultralight",
                      "medium", "light", "thin", "hairline"):
                s = s.replace(w, "")
            return s

        target = norm(span_font_name)
        target_fam = family(target)
        want_bold, want_ital = style(span_font_name)
        want_weight = weight_class(span_font_name)
        best = None   # (style_mismatch, weight_diff, family_diff, path)
        for name, path in self.bundled_fonts.items():
            fn = norm(os.path.basename(path))        # match on the FILE name
            if not fn:
                continue
            fam = family(fn)
            # families must line up (one is a prefix of the other)
            if not (fam == target_fam or fam.startswith(target_fam)
                    or target_fam.startswith(fam)):
                continue
            b, it = style(os.path.basename(path))
            mismatch = (b != want_bold) + (it != want_ital)
            # weight difference dominates family_diff so a wrong-weight but
            # exact-family match no longer wins over a right-weight one
            wdiff = abs(weight_class(os.path.basename(path)) - want_weight)
            diff = abs(len(fam) - len(target_fam))
            key = (mismatch, wdiff, diff)
            if best is None or key < best[:3]:
                best = (mismatch, wdiff, diff, path)
        return best[3] if best else None

    # ================= open / close =================
    def is_open(self):
        return self.doc is not None

    @property
    def page_count(self):
        return self.doc.page_count if self.doc else 0

    def open(self, path, password=None):
        """Open a file. Returns None on success, 'password' if a password is needed,
        or an error message string."""
        try:
            doc = fitz.open(path)
        except Exception as e:
            return str(e)
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                doc.close()
                return "password"
        # switching documents: drop everything belonging to the previous one,
        # including its extracted temp fonts (otherwise they pile up in the OS
        # temp dir for the whole app lifetime)
        try:
            if self.doc:
                self.doc.close()
        except Exception:
            pass
        self._cleanup_temp_fonts()
        self.doc = doc
        self.path = path
        self._bake_rotations()
        self.modified = False
        self._undo.clear()
        self._redo.clear()
        self._span_cache.clear()
        return None

    def _bake_rotations(self):
        """Make every /Rotate page upright in content (see bake_page_rotation)
        so viewer clicks, inserted text and extracted spans share one
        coordinate system. A no-op for pages that are not rotated."""
        if not self.doc or not self.doc.is_pdf:
            return
        for pno in range(self.doc.page_count):
            try:
                if self.doc[pno].rotation:
                    bake_page_rotation(self.doc[pno])
            except Exception:
                pass                 # never block opening a file over this
        self._span_cache.clear()

    # ================= Undo / Redo =================
    def _snapshot(self):
        if not self.doc:
            return
        self._undo.append(self.doc.tobytes())
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()

    def _load_bytes(self, data):
        self.doc = fitz.open("pdf", data)
        self.modified = True
        self._span_cache.clear()
        # The reloaded document renumbers font xrefs, so cached extractions
        # keyed by xref could point at the WRONG font (per-subset glyph ids).
        # Temp files themselves stay on disk until close() - other cached
        # paths may still reference them.
        self._fontfile_cache.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self.doc.tobytes())
        self._load_bytes(self._undo.pop())
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self.doc.tobytes())
        self._load_bytes(self._redo.pop())
        return True

    def _touch(self, pno=None):
        self.modified = True
        if getattr(self, "_find_cache", None):
            self._find_cache.clear()
        if pno is None:
            self._span_cache.clear()
        else:
            self._span_cache.pop(pno, None)

    # ================= save =================
    def save(self, path=None):
        path = path or self.path
        if not path:
            raise ValueError("ไม่มีพาธไฟล์")
        if os.path.abspath(path) == os.path.abspath(self.path or ""):
            # Keep the document recoverable: if anything past close() fails
            # (disk full during replace, file locked by a viewer, ...), the
            # user's in-memory work must not be lost. Snapshot to bytes first
            # so we can reopen from memory in the error path.
            backup = self.doc.tobytes()
            tmp = path + ".wny_tmp"
            try:
                self.doc.save(tmp, garbage=3, deflate=True)
                self.doc.close()
                os.replace(tmp, path)
                self.doc = fitz.open(path)
            except Exception:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
                self.doc = fitz.open("pdf", backup)
                raise
            finally:
                self._span_cache.clear()
                # garbage=3 renumbers xrefs; extraction cache keyed by xref
                # must not survive the save
                self._fontfile_cache.clear()
        else:
            self.doc.save(path, garbage=3, deflate=True)
            self.path = path
        self.modified = False

    # ================= version history =================
    @staticmethod
    def _version_dir():
        """Folder where automatic version backups are kept (survives app close)."""
        d = os.path.join(os.path.expanduser("~"), ".wnyeditpdf", "versions")
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def _version_key(path):
        """A stable id for an original file: its name + a short hash of the path,
        so two different files with the same name don't share a history."""
        import hashlib
        h = hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest()[:8]
        stem = os.path.splitext(os.path.basename(path))[0]
        return f"{stem}__{h}"

    def backup_version(self, path=None, keep=15):
        """Copy the current on-disk file into the version folder with a timestamp,
        BEFORE it gets overwritten. Keeps the newest `keep` versions per file.
        Returns the backup path, or None if there was nothing to back up yet."""
        import shutil
        from datetime import datetime
        src = path or self.path
        if not src or not os.path.exists(src):
            return None
        key = self._version_key(src)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(self._version_dir(), f"{key}__{stamp}.pdf")
        try:
            shutil.copy2(src, dest)
        except Exception:
            return None
        # prune old versions of this file
        mine = sorted(
            (f for f in os.listdir(self._version_dir())
             if f.startswith(key + "__")),
            reverse=True)
        for old in mine[keep:]:
            try:
                os.remove(os.path.join(self._version_dir(), old))
            except Exception:
                pass
        return dest

    def list_versions(self, path=None):
        """Return saved versions for `path`, newest first:
        [{'file', 'when'(datetime), 'label'(str)}]."""
        from datetime import datetime
        src = path or self.path
        if not src:
            return []
        key = self._version_key(src)
        out = []
        vdir = self._version_dir()
        for f in os.listdir(vdir):
            if f.startswith(key + "__") and f.endswith(".pdf"):
                stamp = f[len(key) + 2:-4]
                try:
                    when = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
                except ValueError:
                    continue
                out.append({"file": os.path.join(vdir, f), "when": when,
                            "label": when.strftime("%d/%m/%Y %H:%M:%S")})
        out.sort(key=lambda v: v["when"], reverse=True)
        return out

    def save_encrypted(self, path, user_pw, owner_pw=None):
        """Save with a password (AES-256)."""
        self.doc.save(path, garbage=3, deflate=True,
                      encryption=fitz.PDF_ENCRYPT_AES_256,
                      user_pw=user_pw, owner_pw=owner_pw or user_pw)

    # ================= rendering / coordinates =================
    def render(self, pno, zoom):
        return self.doc[pno].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)

    def page_rect(self, pno):
        """The page rectangle as seen on screen (page rotation applied)."""
        return self.doc[pno].rect

    @staticmethod
    def _to_unrot_rect(page, rect):
        """Convert a rect from viewer coords to unrotated coords (images / drawing)."""
        return (fitz.Rect(rect) * page.derotation_matrix).normalize()

    @staticmethod
    def _to_view_rect(page, rect):
        """Convert a rect from unrotated coords to viewer coords."""
        return (fitz.Rect(rect) * page.rotation_matrix).normalize()

    # ================= existing text (span) =================
    def spans(self, pno):
        if pno in self._span_cache:
            return self._span_cache[pno]
        out = []
        d = self.doc[pno].get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    if sp.get("text", "").strip():
                        out.append(sp)
        self._span_cache[pno] = out
        return out

    def span_at(self, pno, point, slack=2.5):
        """Find the span at the clicked point. When several overlap, pick the SMALLEST
        one (so clicking text laid over a row of dots hits the text, not the dots)."""
        if point is None:
            return None
        best = None
        best_area = None
        for sp in self.spans(pno):
            r = fitz.Rect(sp["bbox"])
            r.x0 -= slack; r.y0 -= slack; r.x1 += slack; r.y1 += slack
            if r.contains(point):
                area = r.get_area()
                if best is None or area < best_area:
                    best, best_area = sp, area
        return best

    # ================= placed images / signatures =================
    def images(self, pno):
        """Images on the page (viewer coords) with each placement's rotation info.
        Skips full-page background scans and 1x1 ghost images left by deletes."""
        page = self.doc[pno]
        out = []
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            return out
        parea = page.rect.get_area() or 1
        for info in infos:
            urect = fitz.Rect(info["bbox"])          # unrotated coords
            if urect.is_empty or not info.get("xref"):
                continue
            if info.get("width", 99) <= 2 and info.get("height", 99) <= 2:
                continue                             # ghost image from delete_image
            vrect = self._to_view_rect(page, urect)  # viewer coords
            if vrect.get_area() > parea * 0.85:      # full-page scanned image
                continue
            try:
                m = fitz.Matrix(info["transform"])
                rot, bake = _placement_rotation(m)
            except Exception:
                rot, bake = 0, 0.0
            out.append({"bbox": vrect, "urect": urect, "xref": info["xref"],
                        "rot": rot, "bake": bake})
        return out

    def image_at(self, pno, point):
        if point is None:
            return None
        for info in reversed(self.images(pno)):   # topmost (placed last) first
            if info["bbox"].contains(point):
                return info
        return None

    @staticmethod
    def _same_rect(a, b, tol=1.0):
        return (abs(a.x0 - b.x0) < tol and abs(a.y0 - b.y0) < tol and
                abs(a.x1 - b.x1) < tol and abs(a.y1 - b.y1) < tol)

    def _extract_image_bytes(self, xref):
        """Extract an image from the file WITH transparency. PDF stores alpha as a
        separate smask; pulling only the base would turn a signature's transparent
        background black."""
        ex = self.doc.extract_image(xref)
        data = ex["image"]
        smask = ex.get("smask")
        if smask:
            try:
                base = fitz.Pixmap(data)
                if base.alpha:
                    base = fitz.Pixmap(base, 0)   # drop existing alpha before merging with mask
                mask = fitz.Pixmap(self.doc.extract_image(smask)["image"])
                data = fitz.Pixmap(base, mask).tobytes("png")
            except Exception:
                pass
        return data

    def _replace_placements(self, pno, info, new_view_rect):
        """Remove only the clicked placement (an image reused in several spots shares
        one xref in PyMuPDF), then put the other placements back with their
        original rotation. new_view_rect = new viewer-coord position (move/resize)
        or None (delete)."""
        page = self.doc[pno]
        xref = info["xref"]
        target = info["urect"]
        data = self._extract_image_bytes(xref)
        placements = []
        for r, m in page.get_image_rects(xref, transform=True):
            rot, bake = _placement_rotation(m)
            placements.append((fitz.Rect(r), rot, bake))
        page.delete_image(xref)          # delete every placement of this xref (leaves a 1x1 ghost)
        for r, rot, bake in placements:  # put the other placements back unchanged
            if self._same_rect(r, target):
                continue
            d = _rotated_png(data, bake) if bake else data
            page.insert_image(r, stream=_unique_png(d), rotate=rot,
                              keep_proportion=False)
        if new_view_rect is not None:
            urect = self._to_unrot_rect(page, new_view_rect)
            d = _rotated_png(data, info.get("bake", 0.0)) if info.get("bake") else data
            page.insert_image(urect, stream=_unique_png(d),
                              rotate=info.get("rot", 0), keep_proportion=False)

    def move_image(self, pno, info, dx, dy):
        """Move an image/signature (dx,dy in viewer coords); size and rotation unchanged."""
        self._snapshot()
        page = self.doc[pno]
        r = info["bbox"]                 # viewer coords
        w, h = r.width, r.height
        nx0 = max(0.0, min(r.x0 + dx, page.rect.width - w))
        ny0 = max(0.0, min(r.y0 + dy, page.rect.height - h))
        self._replace_placements(pno, info,
                                 fitz.Rect(nx0, ny0, nx0 + w, ny0 + h))
        self._touch(pno)

    def resize_image(self, pno, info, new_view_rect):
        """Resize an image/signature to a new rect (viewer coords)."""
        self._snapshot()
        r = fitz.Rect(new_view_rect) & self.doc[pno].rect
        if r.width < 8 or r.height < 8:
            r = info["bbox"]              # too small, don't shrink
        self._replace_placements(pno, info, r)
        self._touch(pno)

    def delete_image(self, pno, info):
        self._snapshot()
        self._replace_placements(pno, info, None)
        self._touch(pno)

    # ================= embedded original font =================
    def _embedded_fontfile(self, pno, span):
        """Extract the span's ORIGINAL embedded font so moving text keeps its look.

        The match must be EXACT. A loose (prefix) match used to let a regular span
        called "THSarabunNew" pick up "THSarabunNew-Bold" that lived in the same
        file - the moved text then came out bold AND bigger, because it was drawn
        with a completely different face. If no exact match exists we return None
        and the caller falls back to a bundled font of the right weight."""
        name = span.get("font", "")
        if not name:
            return None

        def norm(s):
            # keep bold/italic markers - they are what distinguishes the faces
            s = s.split("+")[-1].lower()
            for junk in (" ", "-", "_", ",", "regular"):
                s = s.replace(junk, "")
            return s

        target = norm(name)
        path = None
        try:
            xref = None
            for f in self.doc[pno].get_fonts(full=True):
                if norm(f[3] or "") == target:          # exact match only
                    xref = f[0]
                    break
            if xref is None:
                return None
            # Cache by XREF, not by name: `norm` strips the subset prefix
            # (AAAAAA+), so in a merged document two DIFFERENT subsets of the
            # same family would collide under one name - and glyph ids are
            # per-subset, so reusing the wrong file maps characters to the
            # wrong glyphs. The xref uniquely identifies the font object.
            if xref in self._fontfile_cache:
                return self._fontfile_cache[xref]
            _, ext, _, buf = self.doc.extract_font(xref)
            if buf and ext in ("ttf", "otf", "ttc", "cff"):
                suffix = ".otf" if ext == "cff" else "." + ext
                fd = tempfile.NamedTemporaryFile(delete=False, suffix=suffix,
                                                 prefix="wnyfont_")
                fd.write(buf)
                fd.close()
                path = self._register_temp(fd.name)
                # Subsetted fonts (Word/Canva/Acrobat output) usually have
                # their cmap stripped, so the extracted file can't be addressed
                # by Unicode and would render tofu. Rebuild a Unicode->glyph
                # cmap from the page's own glyph trace so the ORIGINAL font can
                # be reused as real, editable text (this is what lets us keep
                # the file's font instead of converting the text to an image).
                repaired = self._repair_font_cmap(pno, path, name,
                                                  font_xref=xref)
                if repaired:
                    path = self._register_temp(repaired)
        except Exception:
            path = None
        if xref is not None:
            self._fontfile_cache[xref] = path
        return path

    def _read_tounicode(self, font_xref):
        """Read a PDF font's ToUnicode CMap and return {CID: unicode_codepoint}.

        For Identity-H fonts (the composite-font encoding Word / Google Docs use
        for Thai, CJK, Arabic, ...), CID equals glyph-id, so this dictionary is
        also {glyph_id: unicode}. That is exactly what a font's cmap needs but
        INVERTED, and it is the ONE place in the PDF that lists code points a
        subset actually stands for - including combining marks that never appear
        as standalone glyphs (Word merges them into composite glyphs via GSUB,
        so `page.get_texttrace()` never emits them and a trace-only repair leaves
        them missing).

        Returns {} on any parse failure - callers keep working with whatever else
        they have (trace + the file's own cmap). CMap format ref:
        Adobe Tech Note #5411 (bfchar / bfrange sections)."""
        try:
            key = self.doc.xref_get_key(font_xref, "ToUnicode")
        except Exception:
            return {}
        if not key or key[0] != "xref":
            return {}
        try:
            tu_xref = int(key[1].split()[0])
            raw = self.doc.xref_stream(tu_xref) or b""
        except Exception:
            return {}
        # CMaps are ASCII (hex-encoded); latin-1 decode is safe and lossless
        text = raw.decode("latin-1", errors="replace")

        import re
        result = {}

        # `N beginbfchar ... endbfchar`  each line: <src> <dst>
        for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
            for src_hex, dst_hex in re.findall(
                    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                try:
                    cid = int(src_hex, 16)
                    # dst may be multi-codepoint (ligature/decomposition) -
                    # keep the FIRST codepoint since that is the base glyph
                    # for our purposes (cmap is 1-to-1)
                    uni_first = int(dst_hex[:4], 16) if len(dst_hex) >= 4 \
                        else int(dst_hex, 16)
                    if 0 < uni_first < 0x110000:
                        result[cid] = uni_first
                except ValueError:
                    continue

        # `N beginbfrange ... endbfrange`  two forms per line:
        #   <start> <end> <first_dst>            -> consecutive
        #   <start> <end> [<dst1> <dst2> ...]    -> explicit per-CID
        for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
            # form 2 (array) first - it would otherwise partially match form 1
            for src_hex, end_hex, arr in re.findall(
                    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]",
                    block, re.S):
                try:
                    start = int(src_hex, 16)
                    end = int(end_hex, 16)
                except ValueError:
                    continue
                dsts = re.findall(r"<([0-9A-Fa-f]+)>", arr)
                for i, ds in enumerate(dsts):
                    if start + i > end:
                        break
                    try:
                        u = int(ds[:4], 16) if len(ds) >= 4 else int(ds, 16)
                        if 0 < u < 0x110000:
                            result[start + i] = u
                    except ValueError:
                        continue
            # form 1 (consecutive)
            for src_hex, end_hex, dst_hex in re.findall(
                    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
                    block):
                try:
                    start = int(src_hex, 16)
                    end = int(end_hex, 16)
                    base = int(dst_hex[:4], 16) if len(dst_hex) >= 4 \
                        else int(dst_hex, 16)
                except ValueError:
                    continue
                for i in range(end - start + 1):
                    u = base + i
                    if 0 < u < 0x110000:
                        result.setdefault(start + i, u)
        return result

    def _read_actualtext(self, pno, font_resource_names=None):
        """Scan the page's content stream for /ActualText markers and return
        {CID: unicode_codepoint} pairs for each font used on that page.

        Why this matters: Word marks Thai combining marks (mai ek, thanthakhat,
        maitaikhu, ...) in the content stream like:

            /F5 20 Tf
            <00E5>Tj                                    (draws ฐ)
            /Span<</ActualText<FEFF0E4C>>> BDC
            <0164>Tj                                    (draws thanthakhat)
            EMC

        The BDC/EMC "marked content" wrapper says "the CID 0164 that follows
        actually stands for U+0E4C" - text extraction pulls the ActualText but
        the font's ToUnicode CMap points 0164 at a Private Use Area code
        point (U+F70E, an Adobe convention for a position-adjusted variant)
        instead of at the plain U+0E4C. Our earlier repair sources (font's own
        cmap, ToUnicode, glyph trace) therefore never mapped U+0E4C to any
        glyph even though the glyph is right there under a PUA name, and
        insert_text with the moved span rendered .notdef for every ต์ / ฐ์ /
        พ์ / ธ์ etc.

        By parsing the ActualText markers we recover the Word-intended
        Unicode -> CID mapping that the ToUnicode entry omitted. Combined with
        the other sources this lets embedded (Word's own subset) render every
        character the original file rendered - no font substitution, no size
        shrink, no image fallback.

        Returns {} on any parse error. When `font_resource_names` is given
        (dict {resource_name: pdf_font_name}), the return value is filtered
        to CIDs seen under a Tf operator whose resource matches. Callers pass
        the font name they care about and get pairs specific to that font."""
        result = {}
        try:
            page = self.doc[pno]
            contents = page.get_contents() or []
        except Exception:
            return {}
        import re
        # /F<num> <size> Tf   sets the current font resource key
        rx_tf = re.compile(rb"/([A-Za-z0-9_]+)\s+[-\d.]+\s+Tf")
        # <hex>Tj / <hex>TJ / [<hex><hex>...]TJ - the draws to attribute
        rx_show_hex = re.compile(rb"<([0-9A-Fa-f]+)>\s*T[jJ]")
        # /Span<</ActualText<FEFF...>>>BDC ... <hex>Tj ... EMC
        rx_actual = re.compile(
            rb"/Span\s*<<\s*/ActualText\s*<FEFF([0-9A-Fa-f]+)>\s*>>\s*BDC"
            rb"([^<]*<([0-9A-Fa-f]+)>\s*T[jJ])",
            re.S)

        for xref in contents:
            try:
                stream = self.doc.xref_stream(xref) or b""
            except Exception:
                continue
            # Precompute every Tf position once, then binary-search the nearest
            # one before each ActualText marker. The previous version rescanned
            # the stream from position 0 for every marker (O(n*m)) - harmless
            # on small files but noticeable on graphics-heavy pages with
            # hundreds of markers.
            tf_list = [(t.start(), t.group(1).decode("ascii", errors="ignore"))
                       for t in rx_tf.finditer(stream)]
            tf_positions = [t[0] for t in tf_list]
            import bisect

            for m in rx_actual.finditer(stream):
                actual_hex = m.group(1).decode("ascii", errors="ignore")
                cid_hex = m.group(3).decode("ascii", errors="ignore")
                if not actual_hex or not cid_hex:
                    continue
                try:
                    # ActualText is UTF-16BE; take the FIRST codepoint - for
                    # multi-codepoint sequences (rare here) the first is the
                    # base character we want mapped
                    uni = int(actual_hex[:4], 16)
                    cid = int(cid_hex[:4], 16)
                except ValueError:
                    continue
                if not (0 < uni < 0x110000):
                    continue

                # nearest Tf before this marker; if none, the font was
                # inherited from outside this stream and we can't attribute
                # the pair, so skip rather than mis-assign
                i = bisect.bisect_left(tf_positions, m.start()) - 1
                if i < 0:
                    continue
                res_name = tf_list[i][1]

                if font_resource_names is not None:
                    if res_name not in font_resource_names:
                        continue

                result.setdefault(res_name, {}).setdefault(cid, uni)
        return result

    def _font_resource_map(self, pno):
        """Build {resource_name -> font_xref} for `pno`.

        Content streams reference fonts by short resource names (`/F5`), which
        map to real font objects through the page's /Resources /Font dict. We
        need the reverse-ish view to know which resource key belongs to the
        font we are repairing so `_read_actualtext` can filter its CID pairs
        to just that font."""
        result = {}
        try:
            page = self.doc[pno]
            fonts = page.get_fonts(full=True)
        except Exception:
            return result
        # get_fonts(full=True) returns [xref, ext, type, basefont, refname, ...]
        for f in fonts:
            try:
                xref = f[0]
                refname = f[4] if len(f) > 4 else None
                if refname:
                    result[refname] = xref
            except Exception:
                continue
        return result

    def _repair_font_cmap(self, pno, fontpath, font_name=None, font_xref=None):
        """Merge into `fontpath`'s cmap every Unicode<->GID pair we can source
        for this font, and return the path to a patched copy. Returns None if
        the existing cmap already covers everything, or if the repair fails.

        Sources merged, in priority order (highest first):
          1. The file's existing cmap (Word puts ASCII there for text-search
             fallback - trustworthy for the code points it does list)
          2. The PDF's ToUnicode CMap for this font (has EVERY code point the
             font is actually used to display, including Thai/CJK combining
             marks that GSUB composed into a single glyph - which is why the
             trace on its own cannot see them)
          3. The page's glyph trace, filtered to spans of this font (backup
             for fonts without a ToUnicode CMap, e.g. some legacy PDFs)

        Why we don't skip when there is any existing cmap: Word/Google Docs
        subsets keep an ASCII-only cmap, so the naive "cmap present -> already
        fine" check would leave Thai unmapped and the moved text would fall
        back to a different font.

        `font_name` restricts the glyph trace to spans drawn with THIS font -
        glyph ids are per-font, so mixing another font's ids would map
        characters to the wrong glyphs.
        `font_xref` is the font's PDF xref number, used to read its ToUnicode
        CMap - the only source that includes composed combining marks."""
        try:
            from fontTools.ttLib import TTFont, newTable
            from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

            f = TTFont(fontpath)

            def norm(s):
                s = (s or "").split("+")[-1].lower()
                for junk in (" ", "-", "_", ",", "regular"):
                    s = s.replace(junk, "")
                return s

            want = norm(font_name) if font_name else None

            # collect Unicode -> glyph-id ONLY from spans using this same font
            uni2gid = {}
            for span in self.doc[pno].get_texttrace():
                if want and norm(span.get("font", "")) != want:
                    continue
                for c in span.get("chars", []):
                    ucs, gid = c[0], c[1]
                    if ucs and gid is not None:
                        uni2gid.setdefault(ucs, gid)

            # ToUnicode CMap: CID -> Unicode; Identity-H so CID == GID.
            # `setdefault` is the wrong direction here (we want Unicode -> GID);
            # invert with duplicate handling - the first CID that claims each
            # Unicode wins (which matches how a shaping engine would resolve it)
            if font_xref is not None:
                for cid, uni in self._read_tounicode(font_xref).items():
                    uni2gid.setdefault(uni, cid)

            # ActualText markers in the page's content stream: CID -> Unicode.
            # This catches Thai combining marks (◌่ ◌้ ◌๊ ◌๋ ◌์ ◌ั ◌ิ ◌ี ◌ื ◌ึ
            # ◌ุ ◌ู ◌็ ...) that Word writes as CIDs pointing at PUA glyphs -
            # ToUnicode maps those CIDs to U+F7xx placeholders instead of the
            # real Unicode, and the file's own cmap doesn't map U+0E4C etc.
            # at all. Without this the moved text renders .notdef wherever a
            # combining mark appears (ต์ / ฐ์ / พ์ / ธ์ / ประดิษฐ์).
            #
            # We look up the resource name (e.g. "F5") that identifies THIS
            # font in the content stream so we only merge CID pairs that were
            # drawn with THIS font - glyph ids are per-font.
            if font_xref is not None:
                try:
                    res_map = self._font_resource_map(pno)
                    my_res_names = [rn for rn, xr in res_map.items()
                                    if xr == font_xref]
                    if my_res_names:
                        at = self._read_actualtext(pno, set(my_res_names))
                        for res_name in my_res_names:
                            for cid, uni in at.get(res_name, {}).items():
                                uni2gid.setdefault(uni, cid)
                except Exception:
                    pass

            if not uni2gid:
                return None

            order = f.getGlyphOrder()

            def gname(g):
                return order[g] if 0 <= g < len(order) else ".notdef"

            # read the existing cmap once - Word puts ASCII here but usually
            # nothing else, so we keep what's there and add what's missing
            existing_map = {}
            if "cmap" in f:
                for st in f["cmap"].tables:
                    if st.format in (4, 6, 12, 13):
                        existing_map.update(getattr(st, "cmap", {}) or {})

            # new pairs, only for GIDs that exist in this file (a stale
            # ToUnicode/trace entry pointing past the subset's glyph count would
            # corrupt the cmap otherwise; those code points fall through to
            # the image path where they belong)
            new_map = {u: gname(g) for u, g in uni2gid.items()
                       if 0 <= g < len(order)}
            if not new_map:
                return None

            # if the existing cmap already covers everything we would add,
            # nothing to do - saves rewriting the font on every repeat call.
            # BUT: also repair when the existing cmap has ambiguous entries
            # (the same glyph reachable from more than one code point), because
            # PyMuPDF's ToUnicode generator picks arbitrarily during re-embed
            # and will silently swap "-" for U+00AD, non-breaking space for
            # regular space, etc. Canonicalising below removes the ambiguity.
            from collections import Counter
            gcount = Counter(existing_map.values())
            has_ambiguous = any(n > 1 for n in gcount.values())
            if not has_ambiguous and all(u in existing_map for u in new_map):
                return None

            merged = dict(existing_map)
            # existing entries win - the file's own cmap is ground truth for
            # anything it does map
            for u, n in new_map.items():
                merged.setdefault(u, n)

            # Canonicalize: keep at most ONE code point per glyph. Word ships
            # cmaps where the same glyph name (e.g. 'hyphen') is reached from
            # several code points (U+002D and U+00AD both aim at the hyphen
            # glyph). PyMuPDF re-embeds the font on insert_text and rebuilds a
            # ToUnicode CMap by inverting cmap; a many-to-one cmap forces it to
            # pick just one Unicode per glyph, and it picks the highest - so
            # every "-" in the original text comes back as U+00AD (soft hyphen)
            # after moving, breaking `str.contains`, search, copy, and every
            # tool downstream. Prefer whichever code point our sources say the
            # document ACTUALLY uses (via `uni2gid`) over the extra ones Word
            # baked in as fallbacks. When several such preferred code points
            # tie for the same glyph we pick the lowest - that gives basic
            # ASCII (U+002D) precedence over compat/format code points.
            preferred = set(uni2gid.keys())
            per_glyph = {}   # glyph_name -> chosen unicode
            for u, n in merged.items():
                cur = per_glyph.get(n)
                if cur is None:
                    per_glyph[n] = u
                    continue
                cur_pref = cur in preferred
                new_pref = u in preferred
                if new_pref and not cur_pref:
                    per_glyph[n] = u
                elif new_pref == cur_pref and u < cur:
                    per_glyph[n] = u
            merged = {u: n for n, u in per_glyph.items()}

            def make_sub(fmt, pid, eid):
                s = CmapSubtable.getSubtableClass(fmt)(fmt)
                s.platformID = pid
                s.platEncID = eid
                s.language = 0
                if fmt == 12:
                    s.reserved = 0
                    s.length = 0
                    s.nGroups = 0
                return s

            cmap = newTable("cmap")
            cmap.tableVersion = 0
            s4 = make_sub(4, 3, 1)
            s4.cmap = {u: n for u, n in merged.items() if u <= 0xFFFF}
            s12 = make_sub(12, 3, 10)
            s12.cmap = dict(merged)
            cmap.tables = [s4, s12]
            f["cmap"] = cmap

            out = fontpath.rsplit(".", 1)[0] + "_fixed.ttf"
            f.save(out)
            # verify the patch helps: probe a code point that was NOT in the
            # original cmap (so we know the repair added it), preferring a
            # Thai one because that is the whole point of the repair
            probe = next((u for u in new_map
                          if u not in existing_map and 0x0E00 <= u <= 0x0E7F), None)
            if probe is None:
                probe = next((u for u in new_map if u not in existing_map),
                             next(iter(new_map)))
            if fitz.Font(fontfile=out).has_glyph(probe):
                return out
        except Exception:
            return None
        return None

    # ---------- text-writing helper ----------
    def _metrics_close(self, embedded, match, text, threshold=0.10):
        """True when `match` has advance widths close enough to `embedded` that
        re-drawing the text with `match` will keep roughly the same width. False
        means the substitute font would stretch or compress the line badly.

        Not used by the default text-path decision anymore (we prefer editable
        text over exact appearance), but kept for callers that want to warn the
        user or trigger a UI hint when the substitution will visibly shift
        letter spacing."""
        if not embedded or not match:
            return False
        try:
            ef = self._cached_font(embedded)
            mf = self._cached_font(match)
            common = "".join(c for c in text
                             if not c.isspace()
                             and ef.has_glyph(ord(c))
                             and mf.has_glyph(ord(c)))
            if len(common) < 3:
                return False
            we = ef.text_length(common, fontsize=10.0)
            wm = mf.text_length(common, fontsize=10.0)
            if we < 0.1:
                return False
            return abs(wm - we) / we < threshold
        except Exception:
            return False

    def _text_font_ok(self, span, embedded, match):
        """Can we re-draw this span AS TEXT without changing its look?

        True when either the embedded font actually renders the text (its cmap
        is intact) OR a bundled font of the same family+weight exists. The
        earlier stricter check that also demanded matching metrics was rejected
        - it pushed too many spans into the image path and made text
        uneditable, which is worse than a visible font weight/spacing shift.
        `_fit_size` at the call site takes care of the overflow risk by
        shrinking to fit when the substitute font runs wider than the
        original."""
        text = span.get("text", "")
        if embedded and self._font_covers(embedded, text):
            return True
        if match:
            return True
        return False

    def _span_image(self, pno, span, zoom=6):
        """Render just this span's area to transparent PNG bytes, so text drawn in
        a font we cannot reproduce can be moved as a picture without any change to
        how it looks (this is the last-resort path, matching what editors do when
        a font is unavailable and cannot be re-encoded)."""
        bbox = fitz.Rect(span["bbox"])
        if bbox.is_empty or bbox.width < 1 or bbox.height < 1:
            return None, None
        pad = 1.0
        clip = fitz.Rect(bbox.x0 - pad, bbox.y0 - pad,
                         bbox.x1 + pad, bbox.y1 + pad)
        pix = self.doc[pno].get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                       clip=clip, alpha=False)
        try:
            import numpy as np
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n).copy()
            rgb = arr[:, :, :3]
            # near-white paper -> fully transparent; everything else opaque
            white = (rgb > 235).all(axis=2)
            alpha = np.where(white, 0, 255).astype(np.uint8)
            rgba = np.dstack([rgb, alpha])
            from PyQt6.QtGui import QImage
            h, w = rgba.shape[:2]
            img = QImage(np.ascontiguousarray(rgba).data, w, h, w * 4,
                         QImage.Format.Format_RGBA8888).copy()
            data = _qimage_to_png(img)
        except Exception:
            data = _unique_png(pix.tobytes("png"))
        return data, clip

    def _font_covers(self, fontpath, text):
        """Does this font file cover every (non-space) character?
        Guards against subset fonts missing glyphs -> boxes when re-written."""
        if not fontpath:
            return False
        try:
            f = self._cached_font(fontpath)
            for ch in text:
                if ch.isspace():
                    continue
                if f.has_glyph(ord(ch)) == 0:
                    return False
            return True
        except Exception:
            return False

    @staticmethod
    def _span_is_bold(span):
        """Is the span bold? Checks both the font name and the flags (bit 4 = 16)."""
        name = (span.get("font") or "").lower()
        if any(w in name for w in ("bold", "black", "heavy", "semibold")):
            return True
        return bool(span.get("flags", 0) & (1 << 4))

    @staticmethod
    def _span_is_italic(span):
        name = (span.get("font") or "").lower()
        if "italic" in name or "oblique" in name:
            return True
        return bool(span.get("flags", 0) & (1 << 1))

    def _path_is_bold(self, fontpath):
        """Is this font FILE itself bold?

        Reading the font's own flags (not its file name) matters because embedded
        fonts are extracted to temporary files like wnyfont_ab12.ttf - the name
        says nothing, and guessing 'not bold' there made us stack a faux-bold on
        top of an already-bold face ("double bold")."""
        if not fontpath:
            return False
        try:
            f = self._cached_font(fontpath)
            if getattr(f, "is_bold", 0):
                return True
        except Exception:
            pass
        name = os.path.basename(fontpath).lower()
        return "bold" in name or "-bd" in name

    def _path_is_italic(self, fontpath):
        """Is this font FILE itself italic (read from the font, then the name)?"""
        if not fontpath:
            return False
        try:
            f = self._cached_font(fontpath)
            if getattr(f, "is_italic", 0):
                return True
        except Exception:
            pass
        name = os.path.basename(fontpath).lower()
        return "italic" in name or "oblique" in name

    def _insert_text_chain(self, page, view_origin, text, size, color, fontpaths,
                           bold=False, italic=False, skip_faux_fonts=(),
                           max_width=None):
        """Write text at view_origin using the first font in the chain that works.
        (insert_text works in UNROTATED page coords and does not turn the text
        for /Rotate pages - which is why open() bakes rotation away first.)

        `max_width`: when given, and the chosen font would draw the text wider
        than this, condense HORIZONTALLY with a scale matrix instead of
        shrinking the font size. Rationale: a substitute font with wider
        advances (e.g. the Google-Fonts Sarabun vs Word's subset) would push
        the tail of a full-width line past the page edge; PyMuPDF's reader
        then drops the off-page characters on the next get_text() and the
        user "loses" text. Font-size shrinking fixes that but makes the line
        visibly smaller - users read Thai by x-height, so keeping glyph
        HEIGHT and squeezing only width is far less jarring, and the nominal
        font size stays what the user expects when they later edit the span.
        Condensation floor is 0.55: below that Thai glyphs deform badly, so
        we accept overflow beyond it rather than mash the letters.

        Priority order:
        1) fonts in the list that cover every glyph (closest to original look)
        2) bundled full Thai font as a safety net (if text has Thai)
        3) remaining fonts even if glyph coverage is incomplete
        4) standard helv (latin only — cannot render Thai)

        If `bold` is requested but the chosen font file is not itself bold,
        synthesize faux-bold by stroking the glyph outline (render_mode=2).
        `italic` is synthesized with a shear matrix."""
        origin = fitz.Point(view_origin)
        has_thai = any("\u0e00" <= ch <= "\u0e7f" for ch in text)
        cand = [p for p in dict.fromkeys(fontpaths) if p]

        ordered = [p for p in cand if self._font_covers(p, text)]   # (1) full glyphs
        if has_thai and self.default_thai_font and \
                self.default_thai_font not in ordered:              # (2) Thai net
            if self._font_covers(self.default_thai_font, text):
                ordered.append(self.default_thai_font)
        for p in cand:                                              # (3) the rest
            if p not in ordered:
                ordered.append(p)
        if not has_thai:
            ordered.append(None)                                    # (4) helv


        for fp in ordered:
            try:
                kw = dict(fontsize=size, color=color)
                # Faux styling (fake bold / fake italic) is applied ONLY when the
                # look is being rebuilt with a substitute font. When we write with
                # the span's own embedded font, its glyphs already carry their real
                # weight and slant - adding faux bold on top would thicken text that
                # was never bold, and moving it again would flip it back.
                reuse_original = fp in skip_faux_fonts

                # horizontal condensation: same font size, glyphs squeezed
                # side-to-side just enough to fit `max_width`
                sx = 1.0
                if max_width and fp:
                    try:
                        w = self._cached_font(fp).text_length(
                            text, fontsize=size)
                        if w > max_width * 1.02:
                            sx = max(0.55, max_width / w)
                    except Exception:
                        sx = 1.0

                shear = 0.25 if (italic and not reuse_original
                                 and not self._path_is_italic(fp)) else 0.0
                if sx != 1.0 or shear:
                    # one morph matrix carries both effects: X-scale for the
                    # condensation and the shear for faux italic
                    kw["morph"] = (origin,
                                   fitz.Matrix(sx, 0, shear, 1, 0, 0))
                if fp:
                    # Font name must be unique per file, otherwise PyMuPDF reuses
                    # the first font registered under that name (e.g. writing a
                    # regular span first then a bold one with the same name would
                    # yield the regular font and the bold would be lost).
                    tag = "WnyF" + str(abs(hash((fp, bold, italic))) % 100000)
                    kw.update(fontname=tag, fontfile=fp)
                # faux bold = stroke the glyph outline in a SINGLE insert_text
                # (render_mode=2), so the page keeps exactly one text span
                if bold and not reuse_original and not self._path_is_bold(fp):
                    kw.update(render_mode=2, fill=color,
                              border_width=max(0.03, size * 0.0025))
                rc = page.insert_text(origin, text, **kw)
                if rc >= 0:
                    return True
            except Exception:
                continue
        raise RuntimeError("No font could render this text "
                           "(pick a Thai font in the text box, then press Ctrl+Z).")

    @staticmethod
    def _clear_stale_redacts(page):
        """Drop any redaction annotations still pending in the original file first,
        otherwise our apply_redactions would also erase the text under them."""
        try:
            for a in list(page.annots(types=(fitz.PDF_ANNOT_REDACT,)) or []):
                page.delete_annot(a)
        except Exception:
            pass

    @staticmethod
    def _core(rect):
        """The 'real delete' box: shrink 18% vertically (text boxes reserve tall space
        for upper/lower vowels)."""
        r = fitz.Rect(rect)
        dy = r.height * 0.18
        dx = min(0.6, r.width * 0.1)
        rr = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 - dx, r.y1 - dy)
        return rr if not rr.is_empty else r

    @staticmethod
    def _risk(rect):
        """The 'at-risk' box of a span: wider than the delete box (shrink only 5%)
        because PDF deletion nibbles glyphs even when the box just grazes them."""
        r = fitz.Rect(rect)
        dy = r.height * 0.05
        rr = fitz.Rect(r.x0 + 0.3, r.y0 + dy, r.x1 - 0.3, r.y1 - dy)
        return rr if not rr.is_empty else r

    @staticmethod
    def _span_origin(span):
        """The true baseline point of a span (to rewrite it at exactly the same spot)."""
        o = span.get("origin")
        if o:
            return fitz.Point(o)
        r = fitz.Rect(span["bbox"])
        return fitz.Point(r.x0, r.y1 - span.get("size", 12) * 0.22)

    def _surgical_remove(self, pno, span, fallback_fontpath=None):
        """Surgically remove the target span. PDF deletion is area-based, so if the
        target was dragged over other text those words get nibbled too. Fix: find
        every span whose 'risk' box touches the group's delete box (chained), delete
        the whole group at once, then rewrite the non-target spans at their exact
        baseline with their original font/size/colour."""
        page = self.doc[pno]
        self._clear_stale_redacts(page)
        all_spans = self.spans(pno)

        members = [span]
        changed = True
        while changed:
            changed = False
            for sp in all_spans:
                if any(sp is mb for mb in members):
                    continue
                risk = self._risk(sp["bbox"])
                if any(risk.intersects(self._core(mb["bbox"])) for mb in members):
                    members.append(sp)
                    changed = True

        # capture collateral spans before deletion (extract font before redact)
        victims = []
        for sp in members:
            if sp is span:
                continue
            victims.append({"text": sp["text"], "size": sp["size"],
                            "color": int_to_rgb(sp.get("color", 0)),
                            "origin": self._span_origin(sp),
                            "width": fitz.Rect(sp["bbox"]).width,
                            "font": self._embedded_fontfile(pno, sp),
                            "match": self._match_bundled(sp.get("font", "")),
                            "bold": self._span_is_bold(sp),
                            "italic": self._span_is_italic(sp)})

        for sp in members:
            page.add_redact_annot(self._core(sp["bbox"]))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # rewrite the collateral spans at their original baseline.
        # ORDER MATTERS: the span's own EMBEDDED font must come before the
        # bundled match. An earlier version had these swapped, so every line a
        # dragged span touched was silently re-typeset in the substitute font -
        # for Word's Sarabun subset the Google-Fonts substitute runs ~50%
        # wider, so each collateral line stretched far past its old box and
        # piled onto its neighbours (visible as "everything turns to mush"
        # after moving text around a crowded page).
        # skip_faux_fonts: when the rewrite reuses the original embedded font,
        # its glyphs already carry the real weight/slant - stacking faux bold
        # on top would thicken the line every time it gets caught as
        # collateral damage of another move.
        # max_width: if the embedded font is unusable and we do land on the
        # substitute, condense horizontally to the span's original width so
        # the rewritten line cannot invade the rest of the layout.
        for v in victims:
            self._insert_text_chain(page, v["origin"], v["text"], v["size"],
                                    v["color"],
                                    [v["font"], v["match"], fallback_fontpath, None],
                                    bold=v["bold"], italic=v["italic"],
                                    skip_faux_fonts=(v["font"],) if v["font"] else (),
                                    max_width=v["width"])

    # ================= text editing =================
    def edit_span(self, pno, span, new_text, size, fontpath, color=None,
                  bold=None, italic=None, prefer_embedded=False):
        self._snapshot()
        page = self.doc[pno]
        rect = fitz.Rect(span["bbox"])
        if color is None:
            color = int_to_rgb(span.get("color", 0))
        embedded = self._embedded_fontfile(pno, span)
        match = self._match_bundled(span.get("font", ""))
        # keep the original weight/slant unless the user overrides it explicitly
        if bold is None:
            bold = self._span_is_bold(span)
        if italic is None:
            italic = self._span_is_italic(span)
        base = self._span_origin(span)
        self._surgical_remove(pno, span, fontpath)
        if new_text.strip():
            # when the user did NOT change the font, try the ORIGINAL embedded
            # font first so the edited text keeps the file's own look even if that
            # font is not installed on this machine.
            #
            # Embedded fonts in PDFs are usually SUBSETS: their glyph table only
            # holds the characters that already appear in the file, and their
            # Unicode cmap is often stripped so has_glyph() gives false negatives.
            # But if every character of the new text already appeared in the
            # original span, the subset is guaranteed to contain those glyphs, so
            # we can force the embedded font directly (bypassing the glyph check).
            if prefer_embedded:
                chain = [embedded, match, fontpath, None]
            else:
                chain = [fontpath, match, embedded, None]
            # reusing the original embedded font? then don't fake the styling
            skip = (embedded,) if (prefer_embedded and embedded) else ()
            self._insert_text_chain(page, fitz.Point(base.x, base.y),
                                    new_text, size, color, chain,
                                    bold=bold, italic=italic,
                                    skip_faux_fonts=skip)
        self._touch(pno)

    def _move_span_stream(self, pno, span, dx, dy):
        """Acrobat-style move: shift the span by editing the Tm (text matrix)
        operators in the page's content stream, WITHOUT deleting and
        re-typesetting the text.

        Why: the delete+rewrite path has to reproduce the text with a font it
        can address by Unicode - which drags in the whole subset/cmap-repair
        machinery and, for fonts we can't fully repair, font substitution.
        Editing Tm never touches the font, the CIDs, the ActualText wrappers,
        or the colour: the identical glyph run is simply drawn at a new
        position. Lossless for ANY font, however exotic or stripped.

        Approach: run a minimal interpreter over the content streams tracking
        the CTM (q / Q / cm) and locate every `a b c d e f Tm` inside BT..ET.
        Each Tm's device origin = (e,f) x CTM x page.transformation_matrix.
        Tm operators whose origin sits on this span's baseline inside its bbox
        belong to this span (one span can be split across several BT blocks);
        rewrite their e,f so the origin lands at old + (dx,dy).

        Returns True if at least one Tm was rewritten. The CALLER MUST VERIFY
        the result (compare the span table before/after) and fall back to the
        legacy path if anything else moved - that keeps this fast path safe on
        streams the mini-interpreter doesn't fully model (inherited graphics
        state, Td-positioned text, rotated pages, Form XObjects...)."""
        try:
            page = self.doc[pno]
            ptm = page.transformation_matrix
            origin = self._span_origin(span)
            bbox = fitz.Rect(span["bbox"])

            num_re = rb"[-+]?(?:\d+\.?\d*|\.\d+)"
            tok_re = re.compile(
                rb"(?P<num>" + num_re + rb")"
                rb"|(?P<op>\b(?:q|Q|cm|BT|ET|Tm)\b)")

            edits = []          # (xref, [(start, end, new_bytes), ...])
            for xref in (page.get_contents() or []):
                stream = self.doc.xref_stream(xref)
                if not stream:
                    continue
                ctm = fitz.Matrix(1, 0, 0, 1, 0, 0)
                stack = []
                nums = []       # (value, start, end) of recent numeric tokens
                in_text = False
                stream_edits = []
                for m in tok_re.finditer(stream):
                    if m.group("num") is not None:
                        try:
                            nums.append((float(m.group("num")),
                                         m.start(), m.end()))
                        except ValueError:
                            nums.clear()
                        if len(nums) > 6:
                            nums.pop(0)
                        continue
                    op = m.group("op")
                    if op == b"q":
                        stack.append(fitz.Matrix(ctm))
                    elif op == b"Q":
                        ctm = stack.pop() if stack else fitz.Matrix(1, 0, 0, 1, 0, 0)
                    elif op == b"cm" and len(nums) >= 6:
                        a, b, c, d, e, f = (n[0] for n in nums[-6:])
                        ctm = fitz.Matrix(a, b, c, d, e, f) * ctm
                    elif op == b"BT":
                        in_text = True
                    elif op == b"ET":
                        in_text = False
                    elif op == b"Tm" and in_text and len(nums) >= 6:
                        six = nums[-6:]
                        e_val, f_val = six[4][0], six[5][0]
                        # device origin of this text run, in viewer coords
                        dev = fitz.Point(e_val, f_val) * ctm * ptm
                        on_baseline = abs(dev.y - origin.y) <= 2.0
                        in_span_x = (bbox.x0 - 2.0) <= dev.x <= (bbox.x1 - 1.0)
                        if on_baseline and in_span_x:
                            target = fitz.Point(dev.x + dx, dev.y + dy)
                            # back through view->pdf, then pdf->text space
                            inv = ~(fitz.Matrix(ctm) * ptm)
                            new_ef = target * inv
                            start = six[4][1]
                            end = six[5][2]
                            new_bytes = (f"{new_ef.x:.4f} {new_ef.y:.4f}"
                                         .encode("ascii"))
                            stream_edits.append((start, end, new_bytes))
                    if op in (b"cm", b"Tm"):
                        nums.clear()
                if stream_edits:
                    edits.append((xref, stream_edits))

            if not edits:
                return False
            for xref, stream_edits in edits:
                stream = self.doc.xref_stream(xref)
                # apply back-to-front so earlier offsets stay valid
                for start, end, new_bytes in sorted(stream_edits, reverse=True):
                    stream = stream[:start] + new_bytes + stream[end:]
                self.doc.update_stream(xref, stream)
            return True
        except Exception:
            return False

    def _spans_fingerprint(self, pno):
        """(text, rounded-bbox) tuples for verifying a stream-level move
        touched only the intended span."""
        out = []
        for sp in self.spans(pno):
            b = sp["bbox"]
            out.append((sp["text"],
                        round(b[0], 1), round(b[1], 1),
                        round(b[2], 1), round(b[3], 1)))
        return out

    @staticmethod
    def _verify_stream_move(before, after, span, dx, dy, tol=1.5):
        """Did the stream edit move EXACTLY the intended span and nothing else?

        - same number of spans
        - the target's fingerprint is gone from its old place and a fingerprint
          with the same text exists displaced by ~(dx,dy)
        - every other fingerprint is unchanged
        A False here makes the caller roll the bytes back and use the legacy
        path, so being strict costs nothing but a retry."""
        if len(before) != len(after):
            return False
        tgt_text = span["text"]
        b = span["bbox"]
        tgt_fp = (tgt_text, round(b[0], 1), round(b[1], 1),
                  round(b[2], 1), round(b[3], 1))
        before_rest = list(before)
        try:
            before_rest.remove(tgt_fp)
        except ValueError:
            return False        # span table shifted under us - don't trust it
        moved_ok = False
        after_rest = []
        for fp in after:
            if (not moved_ok and fp[0] == tgt_text
                    and abs(fp[1] - (tgt_fp[1] + dx)) <= tol
                    and abs(fp[2] - (tgt_fp[2] + dy)) <= tol
                    and abs(fp[3] - (tgt_fp[3] + dx)) <= tol
                    and abs(fp[4] - (tgt_fp[4] + dy)) <= tol):
                moved_ok = True
                continue
            after_rest.append(fp)
        if not moved_ok:
            return False
        # everything else must be byte-identical (rounded to 0.1pt)
        return sorted(before_rest) == sorted(after_rest)

    def move_span(self, pno, span, dx, dy, fallback_fontpath):
        """Move text without changing how it looks.

        A move does not change the characters, so we simply re-draw the SAME text
        with the SAME font. The order tried is: the span's own embedded font (keeps
        the exact letterforms and weight, even for fonts not installed here) ->
        a bundled font of the same family+weight -> the toolbar font.

        Crucially we do NOT apply any faux bold/italic and do NOT try to guess or
        measure the weight. The chosen font already carries the correct weight in
        its glyphs, so re-drawing is a faithful copy. All the earlier weight
        'detection' is what made moved text randomly thicken or thin."""
        self._snapshot()
        page = self.doc[pno]

        # ---------- FAST PATH: Acrobat-style content-stream move ----------
        # Try shifting the Tm operators first. If it works, the glyph run is
        # untouched (font, CIDs, ActualText, colour all preserved bit-for-bit)
        # - the only change in the file is the position numbers. Verified
        # against the full span table; anything unexpected -> byte-exact
        # rollback and the legacy delete+rewrite path below takes over.
        before = self._spans_fingerprint(pno)
        backup = self.doc.tobytes()
        if self._move_span_stream(pno, span, dx, dy):
            self._span_cache.pop(pno, None)
            after = self._spans_fingerprint(pno)
            ok = self._verify_stream_move(before, after, span, dx, dy)
            if ok:
                self._touch(pno)
                return
            # rollback: reload from the byte snapshot taken above
            self.doc.close()
            self.doc = fitz.open("pdf", backup)
            self._span_cache.clear()
            self._fontfile_cache.clear()
            page = self.doc[pno]
        # ------------------------------------------------------------------

        fs = span["size"]
        color = int_to_rgb(span.get("color", 0))
        embedded = self._embedded_fontfile(pno, span)
        match = self._match_bundled(span.get("font", ""))
        base = self._span_origin(span)
        nx = max(0.0, min(base.x + dx, page.rect.width - 10))
        ny = max(fs * 0.5, min(base.y + dy, page.rect.height - 2))

        # If we cannot reproduce the look with any real font (embedded cmap is
        # stripped AND the family isn't bundled), move the ORIGINAL PIXELS as an
        # image instead of re-typing in a wrong font. This keeps the exact
        # appearance for any font the file uses - the same approach editors fall
        # back to when a font is unavailable.
        if not self._text_font_ok(span, embedded, match):
            data, clip = self._span_image(pno, span)
            if data:
                self._surgical_remove(pno, span, fallback_fontpath)
                new_rect = fitz.Rect(clip.x0 + dx, clip.y0 + dy,
                                     clip.x1 + dx, clip.y1 + dy)
                page.insert_image(new_rect, stream=data, keep_proportion=True)
                self._touch(pno)
                return

        # If the embedded subset can't render every glyph and we fall through
        # to a substitute font with wider advances, the line could spill past
        # the page edge and get cropped on read-back. Instead of shrinking the
        # font size (users complained the text visibly shrank), pass the span's
        # own width so `_insert_text_chain` condenses HORIZONTALLY: same font
        # size, same glyph height, letters squeezed just enough to fit. When
        # the embedded font covers everything (the normal case since the
        # ActualText-based cmap repair) width matches anyway and no morph is
        # applied at all.
        self._surgical_remove(pno, span, fallback_fontpath)
        self._insert_text_chain(page, fitz.Point(nx, ny),
                                span["text"], fs, color,
                                [embedded, match, fallback_fontpath, None],
                                bold=False, italic=False,
                                max_width=fitz.Rect(span["bbox"]).width)
        self._touch(pno)

    def resize_span(self, pno, span, new_size, fallback_fontpath):
        """Resize text (top-left fixed) without changing how it looks - same
        principle as move_span: redraw the same text in the same font, with no
        faux styling and no weight guessing."""
        new_size = max(4.0, min(200.0, float(new_size)))
        self._snapshot()
        page = self.doc[pno]
        rect = fitz.Rect(span["bbox"])
        old_size = span["size"] or 1.0
        color = int_to_rgb(span.get("color", 0))
        embedded = self._embedded_fontfile(pno, span)
        match = self._match_bundled(span.get("font", ""))
        base = self._span_origin(span)
        scale = new_size / old_size

        # font we can't reproduce -> scale the original pixels as an image
        if not self._text_font_ok(span, embedded, match):
            data, clip = self._span_image(pno, span)
            if data:
                self._surgical_remove(pno, span, fallback_fontpath)
                w, h = clip.width * scale, clip.height * scale
                new_rect = fitz.Rect(clip.x0, clip.y0, clip.x0 + w, clip.y0 + h)
                page.insert_image(new_rect, stream=data, keep_proportion=True)
                self._touch(pno)
                return

        new_baseline = rect.y0 + (base.y - rect.y0) * scale
        self._surgical_remove(pno, span, fallback_fontpath)
        self._insert_text_chain(page, fitz.Point(base.x, new_baseline),
                                span["text"], new_size, color,
                                [embedded, match, fallback_fontpath, None],
                                bold=False, italic=False,
                                max_width=rect.width * scale)
        self._touch(pno)

    def delete_span(self, pno, span):
        self._snapshot()
        self._surgical_remove(pno, span)
        self._touch(pno)

    def add_text(self, pno, point, text, size, color, fontpath,
                 bold=False, italic=False, max_width=None):
        """Add text at `point`. With `max_width` (or when the text contains
        newlines) the text flows as a PARAGRAPH: lines wrap at word boundaries
        instead of running off the right edge of the page - long notes no
        longer need the user to guess where to press Enter. Wrapping uses the
        actual font metrics so Thai text (no spaces between words) falls back
        to per-character wrapping, which is the standard behaviour for Thai
        line breaking without a dictionary."""
        self._snapshot()
        page = self.doc[pno]
        if (max_width and max_width > size) or "\n" in text:
            width = max_width or (page.rect.width - point.x - 18)
            width = max(size * 2, min(width, page.rect.width - point.x - 2))
            lines = self._wrap_text(text, size, fontpath, width)
            line_h = size * 1.35
            y = point.y
            for ln in lines:
                if ln:
                    self._insert_text_chain(page, fitz.Point(point.x, y),
                                            ln, size, color, [fontpath, None],
                                            bold=bold, italic=italic)
                y += line_h
                if y > page.rect.height - 2:
                    break
        else:
            self._insert_text_chain(page, fitz.Point(point.x, point.y),
                                    text, size, color, [fontpath, None],
                                    bold=bold, italic=italic)
        self._touch(pno)

    def _wrap_text(self, text, size, fontpath, width):
        """Greedy word-wrap using real font metrics. Splits on spaces when
        possible; a single 'word' wider than the box (typical for Thai, which
        has no inter-word spaces) is broken per character."""
        try:
            font = self._cached_font(fontpath) if fontpath else fitz.Font("helv")
        except Exception:
            font = fitz.Font("helv")

        def w(s):
            try:
                return font.text_length(s, fontsize=size)
            except Exception:
                return len(s) * size * 0.5

        out = []
        for para in text.split("\n"):
            if not para:
                out.append("")
                continue
            line = ""
            for word in para.split(" "):
                cand = (line + " " + word) if line else word
                if w(cand) <= width:
                    line = cand
                    continue
                if line:
                    out.append(line)
                    line = ""
                # word alone still too wide -> per-character break
                if w(word) > width:
                    chunk = ""
                    for ch in word:
                        if w(chunk + ch) > width and chunk:
                            out.append(chunk)
                            chunk = ch
                        else:
                            chunk += ch
                    line = chunk
                else:
                    line = word
            if line:
                out.append(line)
        return out

    # ---------- form fields (AcroForm) ----------
    def form_fields(self, pno):
        """List fillable form fields (AcroForm widgets) on the page.

        Government / hospital PDFs are often interactive forms; without this
        the fields were invisible to every tool in the app. Each entry:
        {name, type ('text'|'checkbox'|'radio'|'combobox'|'listbox'|...),
         value, rect (viewer coords), widget} - `widget` is the live PyMuPDF
        object used by set_form_field."""
        out = []
        try:
            page = self.doc[pno]
            for w in (page.widgets() or []):
                t = w.field_type_string.lower() if w.field_type_string else "?"
                out.append({"name": w.field_name or "",
                            "type": t,
                            "value": w.field_value,
                            "rect": fitz.Rect(w.rect),
                            "widget": w})
        except Exception:
            pass
        return out

    def form_field_at(self, pno, point):
        """The form field whose box contains `point`, or None."""
        for f in self.form_fields(pno):
            if f["rect"].contains(fitz.Point(point.x, point.y)):
                return f
        return None

    def set_form_field(self, pno, field, value):
        """Write `value` into a form field and refresh its appearance.

        Checkboxes take True/False; text fields take a string. The widget is
        re-fetched from a LIVE page reference here rather than reusing the
        object captured by form_fields(): PyMuPDF widgets are bound to the
        page proxy they were iterated from, and once that temporary page is
        garbage-collected the stored widget raises 'Annot is not bound to a
        page'. Matching by name+rect finds the same field again safely."""
        self._snapshot()
        page = self.doc[pno]          # keep alive for the whole update
        target = None
        for w in (page.widgets() or []):
            if ((w.field_name or "") == field["name"]
                    and fitz.Rect(w.rect).intersects(field["rect"])):
                target = w
                break
        if target is None:
            raise ValueError("ไม่พบช่องฟอร์มนี้แล้ว (ไฟล์อาจถูกแก้ไป)")
        if field["type"] == "checkbox":
            target.field_value = bool(value)
        else:
            target.field_value = "" if value is None else str(value)
        target.update()
        self._touch(pno)

    def has_form(self):
        """True if any page carries fillable fields (used to hint the user)."""
        try:
            for pno in range(self.page_count):
                if next(iter(self.doc[pno].widgets() or []), None) is not None:
                    return True
        except Exception:
            pass
        return False

    # ================= annotations / objects =================
    def highlight(self, pno, rect, color=(1, 0.92, 0.23)):
        """Highlight with a selectable colour (default yellow)."""
        self._snapshot()
        page = self.doc[pno]        # keep the page reference alive throughout
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=color)
        annot.update()
        self._touch(pno)

    # ---------- comments (sticky notes) ----------
    COMMENT_COLOR = (0.09, 0.45, 0.90)   # blue (replaces the old purple)

    # ---------- hyperlinks ----------
    def add_link(self, pno, rect, url):
        """Add a clickable web link over `rect` (viewer coords). The visual cue
        (light blue wash + underline) is drawn with ANNOTATIONS, not baked into
        the page, so delete_link() can remove the link and its decoration cleanly.
        The annotations are tagged in their title so we can find them again."""
        self._snapshot()
        page = self.doc[pno]
        r = fitz.Rect(rect)
        page.insert_link({"kind": fitz.LINK_URI, "from": r, "uri": url})
        blue = (0.05, 0.35, 0.85)
        tag = "wnylink"
        wash = page.add_rect_annot(r)
        wash.set_colors(stroke=blue, fill=(0.85, 0.92, 1.0))
        wash.set_opacity(0.32)
        wash.set_border(width=0)
        wash.set_info(title=tag, content=url)
        wash.update()
        y = r.y1 - 1
        line = page.add_line_annot(fitz.Point(r.x0, y), fitz.Point(r.x1, y))
        line.set_colors(stroke=blue)
        line.set_border(width=1.6)
        line.set_info(title=tag, content=url)
        line.update()
        self._touch(pno)

    def links(self, pno):
        """List web links on the page: [{'rect', 'uri'}]."""
        out = []
        for lk in self.doc[pno].get_links():
            if lk.get("kind") == fitz.LINK_URI and lk.get("uri"):
                out.append({"rect": fitz.Rect(lk["from"]), "uri": lk["uri"]})
        return out

    def link_at(self, pno, point):
        pt = fitz.Point(point)
        for lk in self.links(pno):
            if lk["rect"].contains(pt):
                return lk
        return None

    def delete_link(self, pno, rect):
        """Remove a link whose area matches `rect`, together with its decoration
        annotations (tagged 'wnylink') that overlap the same area."""
        self._snapshot()
        page = self.doc[pno]
        target = fitz.Rect(rect)
        for lk in page.get_links():
            if lk.get("kind") == fitz.LINK_URI and \
                    self._same_rect(fitz.Rect(lk["from"]), target):
                page.delete_link(lk)
        # remove the decoration annotations covering this link
        for a in list(page.annots() or []):
            try:
                if a.info.get("title") == "wnylink" and \
                        target.intersects(fitz.Rect(a.rect)):
                    page.delete_annot(a)
            except Exception:
                continue
        self._touch(pno)

    def update_link(self, pno, rect, new_url):
        """Change a link's URL (and its decoration's stored url) in place."""
        self._snapshot()
        page = self.doc[pno]
        target = fitz.Rect(rect)
        for lk in page.get_links():
            if lk.get("kind") == fitz.LINK_URI and \
                    self._same_rect(fitz.Rect(lk["from"]), target):
                lk["uri"] = new_url
                page.update_link(lk)
        for a in list(page.annots() or []):
            try:
                if a.info.get("title") == "wnylink" and \
                        target.intersects(fitz.Rect(a.rect)):
                    a.set_info(title="wnylink", content=new_url)
                    a.update()
            except Exception:
                continue
        self._touch(pno)

    def add_comment(self, pno, point, text, author="WnyEditPDF", kind="note",
                    end=None):
        """Add an annotation. kind:
        'note'   - sticky-note icon (a point)
        'arrow'  - a line with an arrow head from `point` to `end`
        'textbox'- a free-text box drawn in the rect (point .. end)
        end = second viewer-coord point/rect corner (for arrow/textbox)."""
        self._snapshot()
        page = self.doc[pno]
        if kind == "arrow" and end is not None:
            annot = page.add_line_annot(fitz.Point(point), fitz.Point(end))
            annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE,
                                fitz.PDF_ANNOT_LE_OPEN_ARROW)
            annot.set_colors(stroke=self.COMMENT_COLOR)
            annot.set_border(width=2.6)
            if text:
                annot.set_info(title=author, content=text)
        elif kind == "textbox" and end is not None:
            r = fitz.Rect(point, end).normalize()
            if r.width < 40:
                r.x1 = r.x0 + 160
            if r.height < 20:
                r.y1 = r.y0 + 48
            # embed a Thai-capable font so Thai text shows instead of boxes
            fontfile = self.default_thai_font
            kw = dict(fontsize=13, text_color=(0.1, 0.1, 0.1),
                      fill_color=(1.0, 0.99, 0.86))
            try:
                if fontfile:
                    annot = page.add_freetext_annot(
                        r, text or " ", font="wnybox", fontfile=fontfile, **kw)
                else:
                    annot = page.add_freetext_annot(r, text or " ", **kw)
            except TypeError:
                # older PyMuPDF without fontfile= support
                annot = page.add_freetext_annot(r, text or " ", **kw)
            # soft blue rounded-looking border
            try:
                annot.set_colors(stroke=(0.09, 0.45, 0.90),
                                 fill=(1.0, 0.99, 0.86))
                annot.set_border(width=1.2)
            except Exception:
                pass
            annot.set_info(title=author, content=text)
        else:                                   # sticky note
            annot = page.add_text_annot(fitz.Point(point), text, icon="Comment")
            annot.set_info(title=author, content=text)
            annot.set_colors(stroke=self.COMMENT_COLOR)
        annot.update()
        self._touch(pno)

    def _rebuild_line(self, page, annot, p1, p2):
        """PyMuPDF has no set_line(); to move/resize an arrow we read its style,
        delete it and recreate it between the new endpoints."""
        info = annot.info
        ec = annot.colors
        ends = annot.line_ends
        border = annot.border
        page.delete_annot(annot)
        b = page.add_line_annot(fitz.Point(p1), fitz.Point(p2))
        try:
            b.set_line_ends(ends[0] if ends else fitz.PDF_ANNOT_LE_NONE,
                            ends[1] if ends else fitz.PDF_ANNOT_LE_OPEN_ARROW)
        except Exception:
            b.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_OPEN_ARROW)
        b.set_colors(stroke=ec.get("stroke") or self.COMMENT_COLOR)
        b.set_border(width=(border or {}).get("width", 2.6) or 2.6)
        b.set_info(title=info.get("title", ""), content=info.get("content", ""))
        b.update()
        return b

    def move_comment(self, pno, xref, dx, dy):
        """Move a comment to a new spot (dx,dy in viewer coords). Works for all
        kinds: sticky notes and free-text use set_rect; line/arrow annots have no
        rect, so both endpoints are translated instead."""
        self._snapshot()
        page = self.doc[pno]
        a = self._annot_by_xref(page, xref)
        if a:
            if a.type[0] == fitz.PDF_ANNOT_LINE:
                v = a.vertices
                if v and len(v) >= 2:
                    self._rebuild_line(page, a,
                                       fitz.Point(v[0]) + (dx, dy),
                                       fitz.Point(v[-1]) + (dx, dy))
            else:
                r = fitz.Rect(a.rect)
                a.set_rect(r + (dx, dy, dx, dy))
                a.update()
        self._touch(pno)

    def resize_comment(self, pno, xref, new_rect):
        """Resize a comment to `new_rect` (viewer coords). Sticky notes keep their
        fixed icon size; free-text boxes resize; arrows stretch to the rect
        diagonal (start = top-left, end = bottom-right)."""
        self._snapshot()
        page = self.doc[pno]
        a = self._annot_by_xref(page, xref)
        if a:
            r = fitz.Rect(new_rect).normalize()
            if a.type[0] == fitz.PDF_ANNOT_LINE:
                self._rebuild_line(page, a,
                                   fitz.Point(r.x0, r.y0),
                                   fitz.Point(r.x1, r.y1))
            elif a.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
                if r.width >= 24 and r.height >= 16:
                    a.set_rect(r)
                    a.update()
            # sticky notes have a fixed icon size -> nothing to resize
        self._touch(pno)

    def comments(self, pno):
        """Comments on the page: [{'xref','rect','text','author','kind'}].
        kind: 'note' (sticky), 'arrow' (line), 'textbox' (free text)."""
        out = []
        kind_map = {fitz.PDF_ANNOT_TEXT: "note",
                    fitz.PDF_ANNOT_LINE: "arrow",
                    fitz.PDF_ANNOT_FREE_TEXT: "textbox"}
        try:
            for a in self.doc[pno].annots(types=tuple(kind_map)) or []:
                info = a.info
                out.append({"xref": a.xref, "rect": fitz.Rect(a.rect),
                            "text": info.get("content", ""),
                            "author": info.get("title", ""),
                            "kind": kind_map.get(a.type[0], "note")})
        except Exception:
            pass
        return out

    def comment_at(self, pno, point, slack=6):
        if point is None:
            return None
        for c in self.comments(pno):
            r = fitz.Rect(c["rect"])
            r.x0 -= slack; r.y0 -= slack; r.x1 += slack; r.y1 += slack
            if r.contains(point):
                return c
        return None

    @staticmethod
    def _annot_by_xref(page, xref):
        """Find an annot by xref. The caller must keep the page reference alive while
        using the annot (otherwise it detaches -> code=4)."""
        for a in page.annots() or []:
            if a.xref == xref:
                return a
        return None

    def set_comment(self, pno, xref, text):
        self._snapshot()
        page = self.doc[pno]
        a = self._annot_by_xref(page, xref)
        if a:
            a.set_info(content=text)
            a.update()
        self._touch(pno)

    def delete_comment(self, pno, xref):
        self._snapshot()
        page = self.doc[pno]
        a = self._annot_by_xref(page, xref)
        if a:
            page.delete_annot(a)
        self._touch(pno)

    # ---------- freehand pen ----------
    def add_ink(self, pno, points, color=(0.08, 0.12, 0.45), width=2.0):
        """Add a pen stroke (points = list of viewer-coord points)."""
        if len(points) < 2:
            return
        self._snapshot()
        page = self.doc[pno]
        annot = page.add_ink_annot([[(float(x), float(y)) for x, y in points]])
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
        annot.update()
        self._touch(pno)

    def ink_at(self, pno, point, slack=3):
        """Find the ink annotation at the clicked point (for deletion)."""
        if point is None:
            return None
        try:
            for a in self.doc[pno].annots(types=(fitz.PDF_ANNOT_INK,)) or []:
                r = fitz.Rect(a.rect)
                r.x0 -= slack; r.y0 -= slack; r.x1 += slack; r.y1 += slack
                if r.contains(point):
                    return a.xref
        except Exception:
            pass
        return None

    def delete_ink(self, pno, xref):
        self._snapshot()
        page = self.doc[pno]
        a = self._annot_by_xref(page, xref)
        if a:
            page.delete_annot(a)
        self._touch(pno)

    # ---------- insert image / white-out / watermark ----------
    def insert_image(self, pno, center, width_pt, data):
        """Place an image (PNG/JPG bytes) centred at `center` (viewer coords), width
        width_pt. The image stays upright as the user sees it even if the page is
        rotated."""
        self._snapshot()
        page = self.doc[pno]
        tmp = fitz.open(stream=data, filetype="image")
        pix_rect = tmp[0].rect
        ratio = pix_rect.height / pix_rect.width if pix_rect.width else 0.4
        tmp.close()
        w = width_pt
        h = w * ratio
        x0 = max(0, min(center.x - w / 2, page.rect.width - w))
        y0 = max(0, min(center.y - h / 2, page.rect.height - h))
        vrect = fitz.Rect(x0, y0, x0 + w, y0 + h)          # viewer coords
        urect = self._to_unrot_rect(page, vrect)
        page.insert_image(urect, stream=_unique_png(data),
                          rotate=page.rotation, keep_proportion=False)
        self._touch(pno)
        return vrect

    def whiteout(self, pno, rect):
        """White-out an area (rect in viewer coords)."""
        self._snapshot()
        page = self.doc[pno]
        self._clear_stale_redacts(page)
        page.add_redact_annot(rect, fill=(1, 1, 1))   # redact uses viewer coords
        page.apply_redactions()
        page.draw_rect(self._to_unrot_rect(page, rect),   # draw uses unrotated coords
                       color=None, fill=(1, 1, 1))
        self._touch(pno)

    def watermark(self, text, fontpath, fontsize=None, opacity=0.16, angle=45):
        """Add a big diagonal text watermark across the centre of every page.
        The font size auto-scales to the page width so it reads as a large stamp,
        and the text is centred both horizontally and vertically, rotated by
        `angle` degrees around the page centre."""
        self._snapshot()
        font = None
        if fontpath:
            try:
                font = fitz.Font(fontfile=fontpath)
            except Exception:
                font = None
        for page in self.doc:
            wrect = page.rect
            center = fitz.Point(wrect.width / 2, wrect.height / 2)
            # size the text to about 80% of the page width along the diagonal
            size = fontsize
            if size is None:
                if font:
                    tw = font.text_length(text, fontsize=100) or 100
                    size = max(28, min(160, (wrect.width * 0.82) / tw * 100))
                else:
                    size = max(28, wrect.width / max(len(text), 1) * 1.3)
            kw = dict(fontsize=size, color=(0.5, 0.5, 0.5),
                      fill_opacity=opacity,
                      morph=(center, fitz.Matrix(angle)))
            if fontpath:
                kw.update(fontname="WnyWm", fontfile=fontpath)
            # centre the text on the page: shift left by half the text width and
            # up by roughly half the cap height
            if font:
                half_w = font.text_length(text, fontsize=size) / 2
            else:
                half_w = size * len(text) * 0.25
            origin = fitz.Point(center.x - half_w, center.y + size * 0.35)
            rc = page.insert_text(origin, text, **kw)
            if rc < 0 and fontpath:
                kw.pop("fontname"); kw.pop("fontfile")
                page.insert_text(origin, text, **kw)
        self._touch()

    def add_page_numbers(self, fontpath, position="bottom-center",
                         fmt="{n}", start=1, fontsize=11):
        """Stamp a page number on every page. `fmt` may use {n} (page number)
        and {total} (page count), e.g. 'หน้า {n}/{total}'. `position` is one of
        bottom-center / bottom-right / bottom-left / top-center / top-right."""
        self._snapshot()
        total = self.page_count
        for i, page in enumerate(self.doc):
            n = start + i
            label = fmt.replace("{n}", str(n)).replace("{total}", str(total))
            wrect = page.rect
            margin = 28
            if position.startswith("top"):
                y = margin
            else:
                y = wrect.height - margin
            if position.endswith("left"):
                x, align = margin, fitz.TEXT_ALIGN_LEFT
            elif position.endswith("right"):
                x, align = wrect.width - margin, fitz.TEXT_ALIGN_RIGHT
            else:
                x, align = wrect.width / 2, fitz.TEXT_ALIGN_CENTER
            box = fitz.Rect(x - 120, y - fontsize, x + 120, y + fontsize + 4)
            kw = dict(fontsize=fontsize, color=(0.2, 0.2, 0.2), align=align)
            if fontpath:
                kw.update(fontname="WnyPnum", fontfile=fontpath)
            rc = page.insert_textbox(box, label, **kw)
            if rc < 0 and fontpath:
                kw.pop("fontname"); kw.pop("fontfile")
                page.insert_textbox(box, label, **kw)
        self._touch()

    # ================= page management =================
    def is_scanned_page(self, pno):
        """True when the page looks like a scan: it has (almost) no real text but
        does contain images. Used to warn before the enhance step rasterises."""
        page = self.doc[pno]
        text = page.get_text().strip()
        return len(text) < 20 and len(page.get_images()) > 0

    def enhance_scan(self, pno, brightness=0, contrast=0, angle=0.0, dpi=200):
        """Improve a scanned page: brightness/contrast and small deskew rotation.

        brightness: -100..100 (0 = unchanged)
        contrast:   -100..100 (0 = unchanged)
        angle:      degrees, positive = clockwise (use small values to straighten)

        The page is rendered, adjusted, and put back as a single image, so this is
        meant for SCANNED pages. On a text page it would turn the text into pixels,
        which is why the UI checks is_scanned_page() first."""
        from PyQt6.QtGui import QImage, QTransform, QColor, QPainter
        from PyQt6.QtCore import Qt
        self._snapshot()
        page = self.doc[pno]
        page_rect = fitz.Rect(page.rect)

        # 1) render the page at a good resolution
        zoom = max(1.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888).copy()

        # 2) brightness / contrast, applied per channel with a lookup table
        if brightness or contrast:
            b = max(-100, min(100, brightness)) * 255 / 100.0   # additive shift
            c = max(-100, min(100, contrast)) / 100.0
            factor = (1.0 + c) if c >= 0 else (1.0 + c * 0.9)   # contrast gain
            lut = []
            for v in range(256):
                nv = (v - 128) * factor + 128 + b               # contrast then brightness
                lut.append(max(0, min(255, int(round(nv)))))
            img = img.convertToFormat(QImage.Format.Format_RGB888)
            for y in range(img.height()):
                line = img.scanLine(y)
                line.setsize(img.bytesPerLine())
                buf = bytearray(line)
                for i in range(img.width() * 3):
                    buf[i] = lut[buf[i]]
                line[:len(buf)] = bytes(buf)

        # 3) deskew / rotate, filling the new corners with white (paper colour)
        if angle:
            rotated = img.transformed(QTransform().rotate(angle),
                                      Qt.TransformationMode.SmoothTransformation)
            canvas = QImage(rotated.size(), QImage.Format.Format_RGB888)
            canvas.fill(QColor("white"))
            p = QPainter(canvas)
            p.drawImage(0, 0, rotated)
            p.end()
            img = canvas

        # 4) put the result back as the whole page
        data = _qimage_to_png(img)
        page.clean_contents()
        for xref in [i[0] for i in page.get_images()]:
            try:
                page.delete_image(xref)
            except Exception:
                pass
        page.draw_rect(page_rect, color=None, fill=(1, 1, 1), overlay=False)
        page.insert_image(page_rect, stream=_unique_png(data),
                          keep_proportion=True, overlay=True)
        self._touch(pno)

    def rotate_page(self, pno, deg):
        self._snapshot()
        page = self.doc[pno]
        page.set_rotation((page.rotation + deg) % 360)
        bake_page_rotation(page)
        self._touch()

    def delete_page(self, pno):
        self._snapshot()
        self.doc.delete_page(pno)
        self._touch()

    def insert_blank(self, pno):
        """Insert a blank page after page pno, same size as page pno."""
        self._snapshot()
        cur = self.doc[pno]
        self.doc.new_page(pno + 1, width=cur.rect.width, height=cur.rect.height)
        self._touch()

    def move_page(self, pno, delta):
        target = pno + delta
        if not (0 <= target < self.page_count) or delta == 0:
            return pno
        self._snapshot()
        if delta > 0:
            to = target + 1
            if to >= self.page_count:
                to = -1                      # move to the very end
        else:
            to = target
        self.doc.move_page(pno, to)
        self._touch()
        return target

    def reorder_page(self, src, dst):
        """Move a page from index src to index dst (both 0-based). Used when dragging
        thumbnails to reorder; returns the page's real new index."""
        n = self.page_count
        if not (0 <= src < n) or not (0 <= dst < n) or src == dst:
            return src
        self._snapshot()
        # PyMuPDF move_page(src, to): 'to' is the insert-before index; when dragging down
        # add 1 because the source page is removed first
        to = dst + 1 if dst > src else dst
        if to >= n:
            to = -1                          # very end
        self.doc.move_page(src, to)
        self._touch()
        return dst

    def merge(self, path):
        self._snapshot()
        other = fitz.open(path)
        self.doc.insert_pdf(other)
        other.close()
        self._bake_rotations()
        self._touch()

    @staticmethod
    def peek_page_count(path, password=None):
        """Peek at another file's page count (without touching the current document).
        Returns (page_count, need_password)."""
        try:
            d = fitz.open(path)
        except Exception:
            return 0, False
        if d.needs_pass:
            if not password or not d.authenticate(password):
                d.close()
                return 0, True
        n = d.page_count
        d.close()
        return n, False

    def merge_pages(self, path, pages=None, at=None, password=None):
        """Merge only selected pages from another file.
        pages : 1-based page numbers in the desired order, None = all pages.
        at    : insert after this 1-based page of the current document,
                None or >= page count = append at the end.
        Returns the number of pages inserted."""
        other = fitz.open(path)
        if other.needs_pass:
            if not password or not other.authenticate(password):
                other.close()
                raise ValueError("password")
        n = other.page_count
        if pages:
            seq = [p - 1 for p in pages if 1 <= p <= n]
        else:
            seq = list(range(n))
        if not seq:
            other.close()
            raise ValueError("ไม่มีหน้าที่เลือก")

        self._snapshot()
        start_pos = self.page_count if (at is None or at >= self.page_count) else at
        # insert contiguous ranges to preserve the chosen page order
        insert_at = start_pos
        i = 0
        while i < len(seq):
            j = i
            while j + 1 < len(seq) and seq[j + 1] == seq[j] + 1:
                j += 1
            self.doc.insert_pdf(other, from_page=seq[i], to_page=seq[j],
                                start_at=insert_at)
            insert_at += (j - i + 1)
            i = j + 1
        other.close()
        self._bake_rotations()
        self._touch()
        return len(seq)

    def extract_pages(self, start, end, path):
        out = fitz.open()
        out.insert_pdf(self.doc, from_page=start - 1, to_page=end - 1)
        out.save(path, garbage=3, deflate=True)
        out.close()

    @staticmethod
    def parse_page_spec(spec, page_count):
        """Turn a human page spec into a list of 0-based page indices.

        Accepts the notation people already know from print dialogs:
        "1-3,5,8-" -> pages 1,2,3,5 and 8..end. Open-ended on either side
        ("-4" = from the first page, "9-" = to the last), spaces ignored,
        duplicates removed, result kept in the order the user typed so they
        can also REORDER while exporting (e.g. "3,1,2").

        Raises ValueError with a Thai message on anything invalid, so the
        caller can show it straight to the user."""
        if not spec or not spec.strip():
            raise ValueError("ยังไม่ได้ระบุหน้า")
        pages = []
        for chunk in spec.replace(" ", "").split(","):
            if not chunk:
                continue
            if "-" in chunk:
                a, _, b = chunk.partition("-")
                start = int(a) if a else 1
                end = int(b) if b else page_count
            else:
                start = end = int(chunk)
            if start < 1 or end < 1 or start > page_count or end > page_count:
                raise ValueError(
                    f"หน้า '{chunk}' อยู่นอกช่วง 1-{page_count}")
            step = 1 if end >= start else -1
            for p in range(start, end + step, step):
                if (p - 1) not in pages:
                    pages.append(p - 1)
        if not pages:
            raise ValueError("ยังไม่ได้ระบุหน้า")
        return pages

    def save_pages(self, pages, path):
        """Save ONLY `pages` (0-based indices) as a new PDF at `path`.

        Works on a byte copy of the live document, so it exports exactly what
        the user sees right now - including unsaved edits - without touching
        the open document: `self.path` and the undo stack stay pointed at the
        original file, because "save just this page" is an export, not a
        change of what the user is working on.

        Uses select() rather than insert_pdf() so annotations, links and form
        fields survive into the new file. Returns the page count written."""
        pages = list(pages)
        if not pages:
            raise ValueError("ยังไม่ได้ระบุหน้า")
        out = fitz.open("pdf", self.doc.tobytes())
        out.select(pages)
        out.save(path, garbage=3, deflate=True)
        out.close()
        return len(pages)

    # ================= export / search =================
    def export_png(self, pno, path, scale=2):
        self.doc[pno].get_pixmap(matrix=fitz.Matrix(scale, scale)).save(path)

    def export_image(self, pno, path, scale=2.5):
        """Export a page as an image; format guessed from the extension (.png/.jpg/.jpeg)."""
        pix = self.doc[pno].get_pixmap(matrix=fitz.Matrix(scale, scale))
        ext = os.path.splitext(path)[1].lower()
        if ext in (".jpg", ".jpeg"):
            if pix.alpha:                       # JPG has no alpha
                pix = fitz.Pixmap(pix, 0)
            pix.save(path, jpg_quality=92)
        else:
            pix.save(path)

    def export_all_images(self, folder, fmt="png", scale=2.5):
        """Export every page as an image into a folder; returns the file count."""
        ext = "jpg" if fmt.lower() in ("jpg", "jpeg") else "png"
        for i in range(self.page_count):
            self.export_image(i, os.path.join(folder, f"page_{i+1:03d}.{ext}"), scale)
        return self.page_count

    def export_images_zip(self, zip_path, fmt="png", scale=2.5):
        """Render every page and pack the images into ONE zip file.

        Handing the user a single archive beats scattering page_001.png ...
        page_047.png across whatever folder the save dialog happened to be in:
        one file to attach / send / move, and nothing gets separated or
        overwrites an unrelated file with the same name. Images are STORED
        rather than deflated - PNG and JPG are already compressed, so zip
        compression would only burn CPU for ~0% size gain.

        Pages are rendered one at a time and written straight into the
        archive, so peak memory stays at a single page's pixmap even for
        very long documents. Returns the number of pages written."""
        import zipfile
        ext = "jpg" if fmt.lower() in ("jpg", "jpeg") else "png"
        stem = os.path.splitext(os.path.basename(self.path or "pages"))[0]
        mat = fitz.Matrix(scale, scale)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for i in range(self.page_count):
                pix = self.doc[i].get_pixmap(matrix=mat)
                data = pix.tobytes("jpeg" if ext == "jpg" else "png")
                zf.writestr(f"{stem}_page_{i+1:03d}.{ext}", data)
        return self.page_count

    def export_all_text(self, path):
        with open(path, "w", encoding="utf-8") as f:
            for i, page in enumerate(self.doc):
                f.write(f"===== หน้า {i+1} =====\n{page.get_text()}\n")

    def export_docx(self, path, layout=True, pages=None, tables=True,
                    progress=None):
        """Export to Word (.docx). See docx_export.export_docx for the options
        and the returned stats. Imported lazily because building a document is
        the only thing that needs it, and it drags in zipfile."""
        from .docx_export import export_docx
        return export_docx(self, path, layout=layout, pages=pages,
                           tables=tables, progress=progress)

    def search(self, query, start_pno):
        n = self.page_count
        for offset in range(1, n + 1):
            i = (start_pno + offset) % n
            hits = self.doc[i].search_for(query)
            if hits:
                return i, len(hits)
        return None

    def count_matches(self, query):
        """Count matches of the query across the whole file (to report before replacing)."""
        if not query:
            return 0
        total = 0
        for page in self.doc:
            total += len(page.search_for(query))
        return total

    def find_on_page(self, pno, query):
        """Return the rects (fitz.Rect, viewer coords) of every match on that page,
        used to draw the search highlight. Cached per (page, query) so repeated
        repaints during scrolling/dragging don't re-run the search each time."""
        if not query or not (0 <= pno < self.page_count):
            return []
        cache = getattr(self, "_find_cache", None)
        if cache is None:
            cache = self._find_cache = {}
        key = (pno, query)
        if key in cache:
            return cache[key]
        try:
            res = list(self.doc[pno].search_for(query))
        except Exception:
            res = []
        cache[key] = res
        return res

    def replace_text(self, find, repl, fallback_fontpath=None):
        """Find & replace across the whole file, trying to keep each hit's font/size/
        colour. Returns the number of replacements.

        Approach: locate each match, pair it with its span (for font/size/colour),
        surgically remove the old word, then write the new word in the same place
        with the same font."""
        if not find:
            return 0
        self._snapshot()
        replaced = 0
        for pno in range(self.page_count):
            page = self.doc[pno]
            # loop until none remain (positions shift after each edit)
            guard = 0
            while guard < 500:
                guard += 1
                self._span_cache.pop(pno, None)
                hits = page.search_for(find)
                if not hits:
                    break
                rect = hits[0]
                # find the span covering this word to reuse its font/size/colour
                center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
                span = self.span_at(pno, center, slack=1.0)
                if span is None:
                    # span not found (word spans two runs) -> use defaults
                    size = rect.height * 0.72
                    color = (0, 0, 0)
                    embedded = None
                    match = None
                    origin = fitz.Point(rect.x0, rect.y1 - size * 0.22)
                else:
                    size = span["size"]
                    color = int_to_rgb(span.get("color", 0))
                    embedded = self._embedded_fontfile(pno, span)
                    match = self._match_bundled(span.get("font", ""))
                    origin = fitz.Point(rect.x0, self._span_origin(span).y)
                # remove only the matched word (redact its box) without eating neighbours
                self._clear_stale_redacts(page)
                dy = rect.height * 0.16
                page.add_redact_annot(fitz.Rect(rect.x0, rect.y0 + dy,
                                                rect.x1, rect.y1 - dy))
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                if repl:
                    self._insert_text_chain(page, origin, repl, size, color,
                                            [match, embedded, fallback_fontpath, None])
                replaced += 1
                self._span_cache.pop(pno, None)
        self._touch()
        return replaced
