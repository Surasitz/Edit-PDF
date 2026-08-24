# -*- coding: utf-8 -*-
"""Shrink PDF files, with nothing but PyMuPDF.

Every "compress PDF" service on the web is an upload - which is exactly what a
hospital or a government office cannot do with a document full of citizens'
names. So the whole thing happens here, offline, with the library the app
already ships.

Three things actually make a PDF big, and they are handled in that order:

1. **Images.** A page scanned at 600 dpi and then placed on A4 carries four
   times the pixels a printer will ever use. Each image is re-rendered at the
   resolution it is really shown at and re-encoded as JPEG. This is the lossy
   part and it is where the megabytes are.
2. **Fonts.** A fully embedded TH SarabunPSK family is ~1 MB for a page that
   uses forty glyphs. Subsetting fixes that, but it rewrites the very font
   programs this app works so hard to keep faithful, so it is opt-in
   (``subset_fonts=True``) rather than part of the default recipe.
3. **The file structure itself** - dead objects left behind by every editor
   that ever touched the file, uncompressed streams, no object streams. That
   part is lossless and always applied.

Two rules keep this safe to point at someone's only copy of a document:

* The source file is never written to. Callers pass an explicit destination,
  and passing the same path writes to a temp file and swaps only on success.
* The result is opened and page-counted before it is accepted. If it came out
  broken - or simply bigger than the original, which happens with files that
  are already optimised - the original is copied through untouched and the
  caller is told so with ``unchanged``.

Images that would be ruined by a JPEG round-trip are left exactly as they are:
bitonal fax scans (1 bit per pixel, already tiny under CCITT G4), stencil
masks, and anything carrying a soft mask, because the transparency lives in a
separate object that a replacement would orphan - a logo would gain a white
box around it.
"""

import os
import shutil

import fitz


class CompressCancelled(Exception):
    """Raised when the progress callback asks us to stop."""


class CompressError(Exception):
    """The file cannot be compressed (locked, damaged, not a PDF)."""


# level -> how far to push the images.
#   dpi     - resolution to keep, measured at the size the image is displayed
#   quality - JPEG quality for the re-encode
#   floor   - leave images whose stored stream is smaller than this alone
#             unless they are being downscaled anyway; icons and logos cost
#             nothing to keep and are the first thing a user notices going soft
PRESETS = {
    "light":    {"dpi": 220, "quality": 88, "floor": 60 * 1024},
    "balanced": {"dpi": 150, "quality": 72, "floor": 24 * 1024},
    "max":      {"dpi": 110, "quality": 55, "floor": 8 * 1024},
}
LEVELS = ("light", "balanced", "max")

_MIN_PIXELS = 10000        # ~100x100: below this there is nothing to win
_MIN_GAIN = 0.92           # keep the new image only if it saves >= 8%
_A4_LONG_IN = 11.7         # fallback page size when a placement is unknown


def human_size(n):
    """'1.4 MB' - sizes the way a file manager shows them."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def output_path(src, out_dir=None, suffix="_compressed"):
    """Where the compressed copy of `src` should go.

    Never returns an existing path: the point of this feature is a smaller
    copy, and silently eating the file the user compressed last week (or, if
    they picked the source folder, the source itself) is not part of the deal.
    """
    folder = out_dir or os.path.dirname(os.path.abspath(src))
    stem, ext = os.path.splitext(os.path.basename(src))
    ext = ext or ".pdf"
    cand = os.path.join(folder, stem + suffix + ext)
    i = 2
    while os.path.exists(cand):
        cand = os.path.join(folder, f"{stem}{suffix} ({i}){ext}")
        i += 1
    return cand


# ------------------------------------------------------------------ images
def _xref_key(doc, xref, key):
    """One /Key of an image object, or None when it is not there."""
    try:
        typ, val = doc.xref_get_key(xref, key)
    except Exception:
        return None
    return None if typ in (None, "null") else val


def _collect_images(doc):
    """{xref: (pno, widest_display_pt)} for every image the pages reference.

    full=True also reports images nested inside form XObjects, which is where
    scanners and 'print to PDF' drivers like to put the page scan.
    """
    found = {}
    for pno in range(doc.page_count):
        page = doc[pno]
        try:
            items = page.get_images(full=True)
        except Exception:
            continue
        for it in items:
            xref = it[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            shown = max((r.width for r in rects), default=0.0)
            prev = found.get(xref)
            if prev is None:
                found[xref] = (pno, shown)
            elif shown > prev[1]:
                found[xref] = (prev[0], shown)
    return found


def _skip_reason(doc, xref):
    """Why this image must be left alone, or None if it may be re-encoded."""
    if _xref_key(doc, xref, "SMask"):
        return "smask"                       # transparency lives elsewhere
    if _xref_key(doc, xref, "Mask"):
        return "mask"
    if (_xref_key(doc, xref, "ImageMask") or "").lower() == "true":
        return "stencil"
    bpc = _xref_key(doc, xref, "BitsPerComponent")
    if bpc and bpc.strip() == "1":
        return "bitonal"                     # CCITT G4 already beats JPEG here
    return None


def _shrink_one(doc, page, xref, shown_pt, preset, grayscale):
    """Re-encode one image in place. Returns bytes saved (0 = left alone)."""
    if _skip_reason(doc, xref):
        return 0
    try:
        old = len(doc.xref_stream_raw(xref))
    except Exception:
        return 0
    if old <= 0:
        return 0

    try:
        pix = fitz.Pixmap(doc, xref)
    except Exception:
        return 0                              # unsupported codec - leave it
    try:
        if pix.width * pix.height < _MIN_PIXELS:
            return 0

        # How many pixels are actually useful at the size it is displayed?
        if shown_pt > 1:
            eff_dpi = pix.width * 72.0 / shown_pt
            scale = min(1.0, preset["dpi"] / eff_dpi) if eff_dpi > 0 else 1.0
        else:
            cap = preset["dpi"] * _A4_LONG_IN   # placement unknown: assume A4
            scale = min(1.0, cap / max(pix.width, pix.height))

        if scale > 0.95 and old < preset["floor"] and not grayscale:
            return 0                          # small and already fine

        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)         # JPEG has no alpha channel
        if pix.colorspace is None:
            return 0
        if grayscale and pix.colorspace.n != 1:
            pix = fitz.Pixmap(fitz.csGRAY, pix)
        elif pix.colorspace.n == 4:
            pix = fitz.Pixmap(fitz.csRGB, pix)   # CMYK JPEGs confuse viewers
        if scale <= 0.95:
            pix = fitz.Pixmap(pix, max(1, int(pix.width * scale)),
                              max(1, int(pix.height * scale)), None)

        data = pix.tobytes("jpeg", jpg_quality=preset["quality"])
    except Exception:
        return 0
    finally:
        pix = None

    if len(data) >= old * _MIN_GAIN:
        return 0                              # not worth the quality loss
    try:
        page.replace_image(xref, stream=data)
    except Exception:
        return 0
    return old - len(data)


# ------------------------------------------------------------------- saving
def _save(doc, path):
    """Write the smallest structurally-valid file this build can produce."""
    opts = dict(garbage=4, deflate=True, deflate_images=True,
                deflate_fonts=True, clean=True)
    try:
        doc.save(path, use_objstms=1, **opts)   # PyMuPDF >= 1.24
    except TypeError:
        doc.save(path, **opts)


def _verify(path, pages):
    """True when `path` is a readable PDF with the page count we expect."""
    try:
        with fitz.open(path) as check:
            return check.page_count == pages and not check.is_repaired
    except Exception:
        return False


def _unlink(path):
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def compress_file(src, dst, level="balanced", grayscale=False,
                  subset_fonts=False, password=None, progress=None):
    """Write a smaller copy of `src` to `dst`; return what it cost.

    level        - "light" | "balanced" | "max" (see PRESETS)
    grayscale    - drop colour from the images; a colour scan of a black-and-
                   white document is three times the size for nothing
    subset_fonts - also strip unused glyphs out of the embedded fonts
    progress     - progress(done, total) called as it goes; return False to
                   cancel, which raises CompressCancelled and leaves `dst`
                   untouched

    Returns {"before", "after", "saved", "percent", "images", "pages",
             "unchanged"}. `unchanged` means the original was already as small
    as we can make it, so it was copied through as-is.
    """
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    before = os.path.getsize(src)
    in_place = src == dst
    tmp = dst + ".partial" if in_place or os.path.exists(dst) else dst

    try:
        doc = fitz.open(src)
    except Exception as e:
        raise CompressError(str(e))

    def tick(done, total):
        if progress and progress(done, total) is False:
            raise CompressCancelled()

    try:
        if doc.needs_pass and not doc.authenticate(password or ""):
            raise CompressError("locked")
        if not doc.is_pdf:
            raise CompressError("not a pdf")

        images = _collect_images(doc)
        pages = doc.page_count
        total = len(images) + 2
        tick(0, total)

        preset = PRESETS.get(level, PRESETS["balanced"])
        touched = 0
        for i, (xref, (pno, shown)) in enumerate(images.items(), 1):
            if _shrink_one(doc, doc[pno], xref, shown, preset, grayscale):
                touched += 1
            tick(i, total)

        if subset_fonts:
            try:
                doc.subset_fonts()
            except Exception:
                pass                          # never fail the job over fonts
        tick(len(images) + 1, total)

        _save(doc, tmp)
    except CompressCancelled:
        doc.close()
        _unlink(None if tmp == src else tmp)
        raise
    except CompressError:
        doc.close()
        raise
    except Exception as e:
        doc.close()
        _unlink(None if tmp == src else tmp)
        raise CompressError(str(e))
    doc.close()

    after = os.path.getsize(tmp) if os.path.exists(tmp) else before
    good = _verify(tmp, pages)
    unchanged = False
    if not good or after >= before:
        # Already optimal, or the rewrite came out wrong: hand back the
        # original rather than a file that is worse in either sense.
        _unlink(tmp)
        if not in_place:
            shutil.copyfile(src, dst)
        after = before
        unchanged = True
        touched = 0
    elif tmp != dst:
        os.replace(tmp, dst)

    tick(total, total)
    return {"before": before, "after": after, "saved": before - after,
            "percent": (before - after) * 100.0 / before if before else 0.0,
            "images": touched, "pages": pages, "unchanged": unchanged}
