# -*- coding: utf-8 -*-
"""Build the program's Windows icons from artwork, with PyMuPDF alone.

Two icons ship inside WnyEditPDF.exe and they must stay different pictures:

    wnyeditpdf/assets/logo.ico     the application  (taskbar, "Open with")
    wnyeditpdf/assets/pdf-doc.ico  the .pdf files themselves, in Explorer

Using the application logo for both is what makes every PDF in a folder look
like a copy of the program, which is why the document icon is a sheet of paper.

    python tools/make_icon.py --from assets/logo.png -o assets/logo.ico
    python tools/make_icon.py --from art.png --preview   # see every size
    python tools/make_icon.py                            # draw a fallback

The picture is trimmed of its transparent border, fitted into a square frame
(keeping its shape, the spare room left transparent) and redrawn at each icon
size. Without --from a plain document icon is drawn instead; it exists as a
fallback and because it stays sharp at 16 px, where detailed artwork turns to
porridge. --preview writes a strip of every size at its true pixel size, which
is the only honest way to judge an icon.
"""

import argparse
import os
import struct
import sys

import fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "wnyeditpdf", "assets")
FONT_BOLD = os.path.join(ROOT, "fonts", "tahomabd.ttf")

# colours lifted from the logo
WHITE = (1.0, 1.0, 1.0)
PAGE_EDGE = (0.74, 0.76, 0.80)
FOLD_FILL = (0.87, 0.89, 0.92)
RED = (0.827, 0.125, 0.153)        # #D32027
NAVY = (0.078, 0.122, 0.235)       # #142040

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _draw(size):
    """Render one frame of the icon as RGBA bytes, `size` x `size`."""
    # one drawing unit = one pixel, so edges can be put exactly on the pixel
    # grid; at 16 px a half-pixel border is a grey blur instead of a line
    doc = fitz.open()
    page = doc.new_page(width=size, height=size)
    shape = page.new_shape()

    fold_shown = size >= 32        # the folded corner needs ~3 px to read
    detailed = size >= 40          # "PDF" in letters needs ~5 px of height
    snap = size < 48               # pixel-align everything on the small frames

    def px(percent):
        """A percentage of the icon turned into pixels, on the grid if small."""
        v = percent * size / 100.0
        return float(round(v)) if snap else v

    line = 1.0 if snap else size / 100.0 * 1.3

    # ---- the sheet of paper ----
    left, right = px(13), px(87)
    top, bottom = px(5), px(95)
    fold = px(24) if fold_shown else 0.0
    radius = px(3.5)

    if fold_shown:
        # page outline with the top-right corner cut off
        shape.draw_polyline([
            fitz.Point(left, top + radius),
            fitz.Point(left + radius, top),
            fitz.Point(right - fold, top),
            fitz.Point(right, top + fold),
            fitz.Point(right, bottom - radius),
            fitz.Point(right - radius, bottom),
            fitz.Point(left + radius, bottom),
            fitz.Point(left, bottom - radius),
            fitz.Point(left, top + radius),
        ])
        shape.finish(color=PAGE_EDGE, fill=WHITE, width=line, closePath=True)
        # the folded-over corner
        shape.draw_polyline([
            fitz.Point(right - fold, top),
            fitz.Point(right - fold, top + fold),
            fitz.Point(right, top + fold),
            fitz.Point(right - fold, top),
        ])
        shape.finish(color=PAGE_EDGE, fill=FOLD_FILL, width=line, closePath=True)
    else:
        shape.draw_rect(fitz.Rect(left, top, right, bottom))
        shape.finish(color=PAGE_EDGE, fill=WHITE, width=line)

    # ---- faint text lines, so it reads as a document at a glance ----
    if size >= 64:
        for i, y in enumerate((px(33), px(41), px(49))):
            shape.draw_line(fitz.Point(left + px(9), y),
                            fitz.Point(right - px(9 if i < 2 else 22), y))
            shape.finish(color=(0.80, 0.82, 0.86), width=line * 1.6)

    # ---- the red PDF tag, hanging off the left edge like on the logo ----
    if detailed:
        tag = fitz.Rect(left - px(6), px(58), left + px(52), px(82))
        shape.draw_rect(tag, radius=0.14)
    else:
        # too small for letters: a solid red footer along the foot of the page
        tag = fitz.Rect(left + line, bottom - px(30), right - line, bottom - line)
        shape.draw_rect(tag)
    shape.finish(color=None, fill=RED, width=0)
    shape.commit()

    if detailed:
        font = fitz.Font(fontfile=FONT_BOLD)
        fontsize = tag.height * 0.72
        tw = font.text_length("PDF", fontsize=fontsize)
        page.insert_text(
            fitz.Point(tag.x0 + (tag.width - tw) / 2.0,
                       tag.y0 + tag.height / 2.0 + fontsize * 0.35),
            "PDF", fontsize=fontsize, fontfile=FONT_BOLD, fontname="tbd",
            color=WHITE, render_mode=0)

    pix = page.get_pixmap(alpha=True)            # 1 unit = 1 px, so no scaling
    data = pix.samples                           # RGBA, top-down
    doc.close()
    return data


# ----------------------------------------------------------------------
#  using a supplied picture instead of the drawing
# ----------------------------------------------------------------------
_CROPPED = {}


def _trimmed(src):
    """The artwork with its transparent border cut away.

    Exported artwork usually carries a wide empty margin. Left in, it shrinks
    the drawing inside the icon frame — at 16 px that is the difference between
    a readable tag and a smudge — so the empty edges go before scaling."""
    if src in _CROPPED:
        return _CROPPED[src]
    pix = fitz.Pixmap(src)
    if not pix.alpha:
        _CROPPED[src] = pix
        return pix
    w, h = pix.width, pix.height
    alpha = bytes(pix.samples)[3::4]          # one byte per pixel
    rows = [y for y in range(h) if max(alpha[y * w:(y + 1) * w]) > 8]
    cols = [x for x in range(w) if max(alpha[x::w]) > 8]
    if not rows or not cols:                  # fully transparent: nothing to do
        _CROPPED[src] = pix
        return pix
    clip = fitz.IRect(cols[0], rows[0], cols[-1] + 1, rows[-1] + 1)
    out = fitz.Pixmap(fitz.csRGB, clip, True)
    out.copy(pix, clip)
    out.set_origin(0, 0)
    _CROPPED[src] = out
    return out


def _from_image(src, size, margin=0.015):
    """Fit `src` into a transparent `size` x `size` frame, keeping its shape.

    Icon frames are square; artwork usually is not. The picture is centred and
    scaled to the largest size that fits, and the rest of the frame is left
    transparent so Explorer draws nothing there."""
    doc = fitz.open()
    page = doc.new_page(width=size, height=size)
    pad = size * margin
    box = fitz.Rect(pad, pad, size - pad, size - pad)
    # keep_proportion centres the image inside the box without distorting it
    page.insert_image(box, pixmap=_trimmed(src), keep_proportion=True)
    pix = page.get_pixmap(alpha=True)
    doc.close()
    return pix.samples


# ----------------------------------------------------------------------
#  .ico assembly (no Pillow in this project, and none needed)
# ----------------------------------------------------------------------
def _bmp_frame(rgba, size):
    """A frame in the old DIB form: BITMAPINFOHEADER + BGRA + AND mask."""
    header = struct.pack("<IiiHHIIiiII",
                         40,            # biSize
                         size,          # biWidth
                         size * 2,      # biHeight: image + mask
                         1, 32, 0,      # planes, bitcount, compression
                         size * size * 4, 0, 0, 0, 0)
    rows = []
    for y in range(size - 1, -1, -1):           # DIBs are stored bottom-up
        row = bytearray()
        base = y * size * 4
        for x in range(size):
            r, g, b, a = rgba[base + x * 4: base + x * 4 + 4]
            row += bytes((b, g, r, a))          # BGRA
        rows.append(bytes(row))
    mask_row = b"\x00" * (((size + 31) // 32) * 4)   # 1 bpp, 4-byte aligned
    return header + b"".join(rows) + mask_row * size


def _png_frame(rgba, size):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size), True)
    pix.samples_mv[:] = rgba
    return pix.tobytes("png")


def write_ico(path, sizes=SIZES, src=None):
    frames = []
    for size in sizes:
        rgba = _from_image(src, size) if src else _draw(size)
        # PNG compression for the big frames (the .ico would be 350 KB of
        # bitmap otherwise), the classic bitmap form for everything small
        blob = _png_frame(rgba, size) if size >= 128 else _bmp_frame(rgba, size)
        frames.append((size, blob))

    out = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    offset = 6 + 16 * len(frames)
    for size, blob in frames:
        out += struct.pack("<BBBBHHII",
                           0 if size >= 256 else size,
                           0 if size >= 256 else size,
                           0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    for _, blob in frames:
        out += blob
    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="src", default=None,
                    help="picture to turn into the icon instead of drawing one")
    ap.add_argument("--preview", action="store_true",
                    help="also write a strip showing every size at actual size")
    ap.add_argument("-o", "--out", default=os.path.join(ASSETS, "pdf-doc.ico"))
    args = ap.parse_args()

    if args.src and not os.path.exists(args.src):
        sys.exit("no such picture: " + args.src)
    if not args.src and not os.path.exists(FONT_BOLD):
        sys.exit("missing font: " + FONT_BOLD)

    path = write_ico(args.out, src=args.src)
    print("wrote %s (%d bytes)" % (path, os.path.getsize(path)))

    if args.preview:
        prev = os.path.splitext(path)[0] + "-preview.png"
        write_preview(prev, src=args.src)
        print("wrote", prev)


def write_preview(path, src=None, sizes=(16, 20, 24, 32, 48, 64, 128)):
    """A strip of every frame at its true pixel size, next to a big one —
    what Explorer will actually show, not a smooth blow-up of the artwork."""
    doc = fitz.open()
    width = sum(s + 16 for s in sizes) + 300
    page = doc.new_page(width=width, height=200)
    page.draw_rect(fitz.Rect(0, 0, width, 200), color=None, fill=(0.93, 0.94, 0.95))
    x = 16.0
    for size in sizes:
        rgba = _from_image(src, size) if src else _draw(size)
        page.insert_image(fitz.Rect(x, 90 - size / 2.0, x + size, 90 + size / 2.0),
                          stream=_png_frame(rgba, size))
        page.insert_text(fitz.Point(x, 160), "%d" % size, fontsize=9)
        x += size + 16
    big = 128
    rgba = _from_image(src, big) if src else _draw(big)
    page.insert_image(fitz.Rect(x + 20, 26, x + 20 + big, 26 + big),
                      stream=_png_frame(rgba, big))
    page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(path)
    return path


if __name__ == "__main__":
    main()
