# -*- coding: utf-8 -*-
"""PDF -> Word (.docx) export, written without any third-party library.

A .docx is just a zip of XML parts, so we build the handful of parts Word
needs by hand instead of pulling in python-docx: the app ships as one
PyInstaller exe and every extra dependency has to be vendored (see
vendor/qrcode) or it goes missing in the build.

The whole point of this exporter is that the text comes out *unchanged*:

* Every run carries an explicit complex-script font (``w:cs``), complex-script
  size (``w:szCs``) and ``w:lang w:bidi``. Word picks the face for Thai from
  the complex-script slot, never from ``w:ascii`` - leave those out and a 16 pt
  TH SarabunPSK document opens as 11 pt Calibri-with-fallback. That single
  omission is what most "PDF to Word wrecked my document" complaints are.
* SARA AM that the PDF stored decomposed (NIKHAHIT + SARA AA) is put back
  together, and vowel/tone pairs that came out of the file in the wrong order
  are sorted back into canonical Thai order.
* A page whose text decodes to private-use gibberish (a PDF with a broken or
  missing ToUnicode map) is exported as a picture of the page instead. No text
  beats wrong text, and the caller is told which pages those were so it can say
  so rather than letting the user discover it later.

Two shapes of output, chosen by the caller:

* ``layout=True``  - every line of the PDF becomes an absolutely positioned
  Word frame, so tables, forms and multi-column pages land exactly where they
  were. This is the faithful one.
* ``layout=False`` - the lines are stitched back into real paragraphs that
  flow from page to page (with real Word tables where ruled tables are
  detected, and page numbers moved into Word's header/footer), which is the
  one you can keep writing in.

Fonts the app ships in fonts/ are embedded in the .docx when the document uses
them. A PDF made with Sarabun opens on a machine without Sarabun; without the
embedded copy Word silently swaps in a fallback face and every line reflows.
"""

import html
import os
import re
import struct
import time
import unicodedata
import uuid
import zipfile

import fitz


class ExportCancelled(Exception):
    """Raised when the progress callback asks us to stop."""


# ============================================================ Thai text repair
_SARA_AA = "า"          # า
_SARA_AM = "ำ"          # ำ
_NIKHAHIT = "ํ"         # ํ
_TONES = "่้๊๋"                       # ่ ้ ๊ ๋
_ABOVE = "ัิีึื็ํ"     # ั ิ ี ึ ื ็ ํ
_BELOW = "ฺุู"                             # ุ ู ฺ
_THANTHAKHAT = "์๎"                             # ์ ๎
_MARKS = _TONES + _ABOVE + _BELOW + _THANTHAKHAT

# NIKHAHIT + (optional tone) + SARA AA is a decomposed SARA AM. PDF producers
# emit it because the two pieces are separate glyphs in the font; left alone it
# renders as "ํา" instead of "ำ" and breaks every search for the word. A tone
# mark written before the NIKHAHIT needs no rule of its own - it simply stays
# where it is while the two halves either side of it join up.
_RE_AM = re.compile("%s([%s]?)%s" % (_NIKHAHIT, _TONES, _SARA_AA))

# A space in front of a vowel or mark that can never begin a syllable. Some
# producers position SARA AM etc. with a gap, and extraction reads the gap as a
# space: "คำนำ" comes out as "ค ำน ำ".
_RE_STRAY_SPACE = re.compile("(?<=[ก-ฮะ-๎]) +(?=[ะาำๅ%s])"
                             % "".join(_TONES + _ABOVE + _BELOW + _THANTHAKHAT))

# invisible junk that only exists to help the PDF line-break; Word does its own
_RE_INVISIBLE = re.compile("[​­﻿]")


def _mark_rank(ch):
    """Sort key putting a Thai mark cluster into canonical order:
    vowel (below or above), then tone, then thanthakhat."""
    if ch in _BELOW:
        return 0
    if ch in _ABOVE:
        return 1
    if ch in _TONES:
        return 2
    return 3


def _order_marks(s):
    """Sort each run of Thai combining marks into canonical order.

    Some producers write the tone mark before the upper vowel ("ก่ิ" instead of
    "กิ่") because that is the order the glyphs were drawn in. The two look
    almost the same on screen but are different strings, so search, spell-check
    and any later edit in Word all fail on them. Sorting is stable and a no-op
    on well-formed text."""
    if not any(c in _MARKS for c in s):
        return s
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] in _MARKS:
            j = i
            while j < n and s[j] in _MARKS:
                j += 1
            out.extend(sorted(s[i:j], key=_mark_rank))
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _xml_safe(s):
    """Drop characters XML 1.0 cannot carry (control codes, lone surrogates)."""
    out = []
    for ch in s:
        o = ord(ch)
        if o in (0x09, 0x0A, 0x0D) or 0x20 <= o <= 0xD7FF \
                or 0xE000 <= o <= 0xFFFD or o >= 0x10000:
            out.append(ch)
    return "".join(out)


def repair_text(s):
    """Clean up one span of extracted text so Word shows exactly what the PDF
    showed. Safe to run on non-Thai text - it only touches Thai code points and
    characters that are invisible anyway."""
    if not s:
        return ""
    s = _RE_INVISIBLE.sub("", s)
    s = s.replace(" ", " ").replace("\t", " ")
    s = _RE_AM.sub("\\1" + _SARA_AM, s)
    s = _RE_STRAY_SPACE.sub("", s)
    s = _order_marks(s)
    # NFC only outside Thai: Thai has no useful compositions and normalising it
    # would undo the SARA AM repair above.
    if any(ord(c) > 0x2FF and not (0x0E00 <= ord(c) <= 0x0E7F) for c in s):
        try:
            s = unicodedata.normalize("NFC", s)
        except Exception:
            pass
    return _xml_safe(s)


def _is_undecodable(ch):
    """True for a character that means "the PDF's ToUnicode map failed here"."""
    o = ord(ch)
    return (0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0x10FFFD
            or o == 0xFFFD or unicodedata.category(ch) == "Cn")


def undecodable_ratio(text):
    """Share of the text that did not decode to real characters."""
    real = [c for c in text if not c.isspace()]
    if not real:
        return 0.0
    return sum(1 for c in real if _is_undecodable(c)) / len(real)


# ================================================================ font mapping
# PDFs name fonts by their PostScript name ("THSarabunPSK", "ArialMT"); Word
# wants the family name a user would see in the font box. Only the families
# that actually turn up in Thai office documents are worth listing - anything
# else falls through to _prettify().
_FONT_ALIASES = {
    "thsarabunnew": "TH Sarabun New",
    "thsarabunpsk": "TH SarabunPSK",
    "thsarabunit9": "TH SarabunIT๙",       # the family name the font itself declares
    "thsarabun": "TH Sarabun New",
    "sarabun": "Sarabun",
    "angsananew": "Angsana New",
    "angsanaupc": "AngsanaUPC",
    "cordianew": "Cordia New",
    "cordiaupc": "CordiaUPC",
    "browallianew": "Browallia New",
    "browalliaupc": "BrowalliaUPC",
    "dilleniaupc": "DilleniaUPC",
    "eucrosiaupc": "EucrosiaUPC",
    "freesiaupc": "FreesiaUPC",
    "irisupc": "IrisUPC",
    "jasmineupc": "JasmineUPC",
    "kodchiangupc": "KodchiangUPC",
    "lilyupc": "LilyUPC",
    "leelawadee": "Leelawadee",
    "leelawadeeui": "Leelawadee UI",
    "notosansthai": "Noto Sans Thai",
    "notoseriftha": "Noto Serif Thai",
    "notoserifthai": "Noto Serif Thai",
    "timesnewroman": "Times New Roman",
    "timesnewromanps": "Times New Roman",
    "times": "Times New Roman",
    "arial": "Arial",
    "arialunicodems": "Arial Unicode MS",
    "helvetica": "Arial",
    "couriernew": "Courier New",
    "courier": "Courier New",
    "calibri": "Calibri",
    "cambria": "Cambria",
    "tahoma": "Tahoma",
    "verdana": "Verdana",
    "segoeui": "Segoe UI",
    "symbol": "Symbol",
    "wingdings": "Wingdings",
    "zapfdingbats": "Wingdings",
}

_STYLE_WORDS = ("bolditalic", "boldoblique", "semibold", "demibold", "extrabold",
                "ultrabold", "extralight", "ultralight", "bold", "italic",
                "oblique", "black", "heavy", "medium", "light", "thin",
                "regular", "book", "normal", "psmt", "ps", "mt", "std")

_RE_SUBSET = re.compile(r"^[A-Z]{6}\+")


def _prettify(raw):
    """Turn a PostScript font name into something a user would recognise:
    'THSarabunNew' -> 'TH Sarabun New'."""
    name = re.split(r"[-,]", raw)[0]
    name = re.sub(r"(PSMT|PSM|PS|MT)$", "", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    name = " ".join(name.replace("_", " ").split())
    return name or "TH SarabunPSK"


def _fkey(name):
    """Compare font names ignoring case, spaces and punctuation."""
    return re.sub("[^0-9a-zก-๙]", "", (name or "").lower())


def font_family(raw_name):
    """Word family name for a PDF span's font.

    A family we ship is named exactly the way its own name table names it:
    that is the name Word matches an embedded font by, so 'TH Sarabun IT๙'
    for a font that calls itself 'TH SarabunIT๙' would embed it for nothing."""
    if not raw_name:
        return "TH SarabunPSK"
    raw = _RE_SUBSET.sub("", raw_name)
    key = re.sub(r"[^a-z0-9]", "", raw.lower())
    bundled = _font_index()
    if key in _FONT_ALIASES:
        return _FONT_ALIASES[key]
    if key in bundled:                  # 'Sarabun-Medium' -> 'Sarabun Medium'
        return bundled[key][0]
    # strip trailing style words ("THSarabunPSKBold" -> "THSarabunPSK") and
    # try again before giving up and prettifying whatever is left
    trimmed = key
    changed = True
    while changed and trimmed:
        changed = False
        for w in _STYLE_WORDS:
            if trimmed.endswith(w) and len(trimmed) > len(w):
                trimmed = trimmed[:-len(w)]
                changed = True
        if trimmed in _FONT_ALIASES:
            return _FONT_ALIASES[trimmed]
        if trimmed in bundled:
            return bundled[trimmed][0]
    return _prettify(raw)


# ============================================================ font embedding
# Families that come with every Windows install. Embedding them only bloats the
# file (Tahoma alone is ~900 KB).
_WINDOWS_FAMILIES = {"tahoma", "arial", "timesnewroman", "couriernew", "calibri",
                     "cambria", "segoeui", "verdana", "symbol", "wingdings",
                     "leelawadee", "leelawadeeui", "angsananew", "cordianew",
                     "browallianew", "angsanaupc", "cordiaupc", "browalliaupc"}

_SUBFAMILY_STYLE = {"regular": "Regular", "normal": "Regular", "book": "Regular",
                    "roman": "Regular", "bold": "Bold", "italic": "Italic",
                    "oblique": "Italic", "bolditalic": "BoldItalic",
                    "boldoblique": "BoldItalic"}

_font_index_cache = None


def _fonts_dir():
    try:
        from .config import resource_path
        return resource_path("fonts")
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "fonts")


def ttf_info(data):
    """(family, subfamily, fsType) of a TrueType font, or None.

    Only plain TrueType qualifies: Word embeds nothing else (no CFF .otf, no
    .ttc). fsType is the foundry's embedding permission."""
    if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"true"):
        return None
    count = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(count):
        tag, _sum, off, ln = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        tables[tag] = (off, ln)
    fs_type = 0
    if b"OS/2" in tables:
        off = tables[b"OS/2"][0]
        fs_type = struct.unpack(">H", data[off + 8:off + 10])[0]
    if b"name" not in tables:
        return None
    off = tables[b"name"][0]
    _fmt, n, store = struct.unpack(">HHH", data[off:off + 6])
    names = {}
    for i in range(n):
        pid, _eid, lid, nid, ln, noff = struct.unpack(
            ">HHHHHH", data[off + 6 + 12 * i:off + 18 + 12 * i])
        if nid not in (1, 2) or pid not in (0, 1, 3):
            continue
        raw = data[off + store + noff:off + store + noff + ln]
        text = raw.decode("latin-1" if pid == 1 else "utf-16-be", "replace")
        rank = 0 if (pid == 3 and lid == 0x409) else 1 if pid == 3 else 2
        if nid not in names or rank < names[nid][0]:
            names[nid] = (rank, text)
    if 1 not in names:
        return None
    return names[1][1], names.get(2, (0, "Regular"))[1], fs_type


def _font_index():
    """{family key: (family name, {style: path})} for the shipped fonts."""
    global _font_index_cache
    if _font_index_cache is not None:
        return _font_index_cache
    index = {}
    folder = _fonts_dir()
    try:
        files = sorted(os.listdir(folder))
    except OSError:
        files = []
    for fn in files:
        if not fn.lower().endswith(".ttf"):
            continue
        path = os.path.join(folder, fn)
        try:
            with open(path, "rb") as f:
                info = ttf_info(f.read())
        except Exception:
            continue
        if not info:
            continue
        family, sub, fs_type = info
        # 0x0002 = "restricted license embedding": the foundry says no
        if fs_type & 0x000F == 0x0002:
            continue
        style = _SUBFAMILY_STYLE.get(re.sub("[^a-z]", "", sub.lower()))
        if not style:
            continue
        entry = index.setdefault(_fkey(family), (family, {}))
        entry[1].setdefault(style, path)
    _font_index_cache = index
    return index


def obfuscate_font(data, key):
    """ECMA-376 font obfuscation: XOR the first 32 bytes with the GUID in
    `key`, its bytes taken in reverse order of how the string spells them."""
    k = bytes.fromhex(key.strip("{}").replace("-", ""))[::-1]
    head = bytes(b ^ k[i % 16] for i, b in enumerate(data[:32]))
    return head + data[32:]


_fitz_fonts = {}


def _measure_font(path):
    if path not in _fitz_fonts:
        try:
            _fitz_fonts[path] = fitz.Font(fontfile=path)
        except Exception:
            _fitz_fonts[path] = None
    return _fitz_fonts[path]


def _width_ratio(files, samples):
    """Median of (width in the PDF / width set in this font) over the
    samples, or None. 1.0 means the font has the PDF font's metrics."""
    ratios = []
    for bold, italic, size, text, width in samples:
        style = ("Bold" if bold else "") + ("Italic" if italic else "") or "Regular"
        path = files.get(style) or files.get("Bold" if bold else "Regular") \
            or files.get("Regular")
        font = _measure_font(path) if path else None
        if font is None:
            continue
        try:
            w = font.text_length(text, fontsize=size)
        except Exception:
            continue
        if w > 0:
            ratios.append(width / w)
    if not ratios:
        return None
    ratios.sort()
    return ratios[len(ratios) // 2]


_FIT = 0.06        # how far a font's widths may stray and still count as "the same"


def fit_fonts(doc, idxs):
    """Check each font family the PDF uses against the TrueType files we
    ship, by width rather than by name.

    Names lie: Google Docs' "Sarabun" is the old Sarabun, metrically TH Sarabun
    New, while the "Sarabun" in fonts/ is the 2018 redesign - a third wider.
    Embedding a font by name alone would make every line overflow. Returns
    (renames {pdf family: family to write instead}, families not to embed)."""
    samples = {}
    for pno in idxs[:12]:
        try:
            d = doc[pno].get_text("dict")
        except Exception:
            continue
        for b in d.get("blocks", []):
            for ln in b.get("lines", []) if b.get("type") == 0 else []:
                for sp in ln.get("spans", []):
                    text = repair_text(sp.get("text", ""))
                    if len(text.strip()) < 6:
                        continue
                    fam, bold, ital, _sup = span_style(sp)
                    lst = samples.setdefault(fam, [])
                    if len(lst) < 80:
                        r = sp["bbox"]
                        lst.append((bold, ital, float(sp.get("size", 12)), text,
                                    r[2] - r[0]))
    index = _font_index()
    renames, reject = {}, set()
    for fam, smp in samples.items():
        key = _fkey(fam)
        if key in _WINDOWS_FAMILIES:
            continue
        if key in index:
            r = _width_ratio(index[key][1], smp)
            if r is None or abs(r - 1) <= _FIT:
                continue
            reject.add(fam)             # same name, different font
        best, best_d = None, _FIT
        for _k, (name, files) in sorted(index.items()):
            r = _width_ratio(files, smp)
            # strictly better only: on a tie the first in name order wins,
            # which puts TH Sarabun New ahead of its twin TH SarabunPSK
            if r is not None and (abs(r - 1) < best_d
                                  or best is None and abs(r - 1) <= _FIT):
                best, best_d = name, abs(r - 1)
        if best and best != fam:
            renames[fam] = best
    return renames, reject


def rename_fonts(xml, renames):
    """Swap font family names in every rFonts attribute."""
    for old, new in renames.items():
        xml = re.sub(r'(w:(?:ascii|hAnsi|cs|eastAsia)=")%s(")' % re.escape(_esc(old)),
                     lambda m: m.group(1) + _esc(new) + m.group(2), xml)
    return xml


_RE_RUN_FONT = re.compile(r'<w:rFonts w:ascii="([^"]*)"[^>]*/>(<w:b/>)?'
                          r'(?:<w:bCs/>)?(<w:i/>)?')


def used_fonts(*xml_parts):
    """{family: {style}} for every run in the given WordprocessingML."""
    out = {}
    for xml in xml_parts:
        for m in _RE_RUN_FONT.finditer(xml):
            style = ("Bold" if m.group(2) else "") + ("Italic" if m.group(3) else "")
            out.setdefault(html.unescape(m.group(1)), set()).add(style or "Regular")
    return out


def span_style(span):
    """(family, bold, italic, superscript) for a PyMuPDF span.

    The font name and the span flags disagree often enough that we trust
    either one saying bold: a subset called 'ABCDEF+THSarabunPSK-Bold' may
    carry no bold flag, and a synthesised bold carries the flag with no hint in
    the name."""
    raw = span.get("font", "") or ""
    flags = int(span.get("flags", 0) or 0)
    low = raw.lower()
    bold = bool(flags & 16) or any(w in low for w in ("bold", "black", "heavy"))
    italic = bool(flags & 2) or "italic" in low or "oblique" in low
    family = font_family(raw)
    if re.search("bold|black|heavy", family, re.I):
        bold = False     # 'Sarabun SemiBold' is already heavy; <w:b/> would double it
    return family, bold, italic, bool(flags & 1)


# ====================================================================== units
def _tw(pt):
    """Points -> twips (1/20 pt), the unit most of WordprocessingML uses."""
    return int(round(pt * 20))


def _emu(pt):
    """Points -> EMU (1/914400 inch), the unit DrawingML uses."""
    return int(round(pt * 12700))


def _halfpt(pt):
    return max(2, int(round(pt * 2)))


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _color(span):
    return "%06X" % (int(span.get("color", 0) or 0) & 0xFFFFFF)


# ================================================================ XML builders
def run_xml(text, family, size_pt, color="000000", bold=False, italic=False,
            superscript=False):
    """One <w:r>. Element order inside w:rPr follows the schema sequence -
    Word rejects the file outright if they are shuffled."""
    if not text:
        return ""
    fam = _esc(family)
    hp = _halfpt(size_pt)
    rpr = ['<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s" w:eastAsia="%s"/>'
           % (fam, fam, fam, fam)]
    if bold:
        rpr.append("<w:b/><w:bCs/>")
    if italic:
        rpr.append("<w:i/><w:iCs/>")
    rpr.append('<w:color w:val="%s"/>' % color)
    rpr.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (hp, hp))
    if superscript:
        rpr.append('<w:vertAlign w:val="superscript"/>')
    head = "".join(rpr)
    # w:bidi is the language Word uses to shape and line-break Thai; without it
    # Word may hyphenate/spell-check Thai as if it were English.
    lang = '<w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="th-TH"/>'
    out = []
    for piece, thai in _script_pieces(text):
        # a tab inside w:t is not a tab to Word - it has to be its own element
        body = "<w:tab/>".join('<w:t xml:space="preserve">%s</w:t>' % _esc(p)
                               if p else "" for p in piece.split("\t"))
        # <w:cs/> marks the run as complex script, which is what switches on
        # Word's Thai word breaker. Without it Word wraps Thai only at spaces
        # and, when a stretch is too long, cuts it mid-word ("เชิงก|ลยุทธ์").
        # Word itself writes Thai and Latin as separate runs, cs on Thai only.
        out.append('<w:r><w:rPr>%s%s%s</w:rPr>%s</w:r>'
                   % (head, "<w:cs/>" if thai else "", lang, body))
    return "".join(out)


# Thai letters, plus the spaces, digits and punctuation between them
_RE_THAI_STRETCH = re.compile(
    "[฀-๿]+(?:[\\s0-9.,:;()\"'“”‘’!?%/\\-–—]+[฀-๿]+)*")


def _script_pieces(text):
    """Split text into (piece, is_thai) runs."""
    out = []
    pos = 0
    for m in _RE_THAI_STRETCH.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def field_xml(instr, shown, key):
    """A simple field (PAGE, NUMPAGES) displaying `shown` until Word updates it."""
    return ('<w:fldSimple w:instr=" %s ">%s</w:fldSimple>'
            % (_esc(instr), run_xml(shown, *key)))


def _ppr(frame=None, spacing=None, ind=None, jc=None, sect=None,
         default_font=None, default_size=None, tabs=None, page_break=False,
         border=None):
    """<w:pPr>, elements in schema order: pageBreakBefore, framePr, pBdr,
    tabs, spacing, ind, jc, rPr, sectPr."""
    parts = []
    if page_break:
        parts.append("<w:pageBreakBefore/>")
    if frame:
        parts.append(frame)
    if border:
        parts.append(border)
    if tabs:
        # a tab stop is a position, or (position, "right", "dot") for a
        # right-aligned stop with a dotted leader - a table of contents
        stops = [t if isinstance(t, tuple) else (t, "left", None) for t in tabs]
        parts.append("<w:tabs>%s</w:tabs>" % "".join(
            '<w:tab w:val="%s"%s w:pos="%d"/>'
            % (val, ' w:leader="%s"' % leader if leader else "", _tw(pos))
            for pos, val, leader in sorted(stops)))
    if spacing:
        parts.append(spacing)
    if ind:
        parts.append(ind)
    if jc:
        parts.append('<w:jc w:val="%s"/>' % jc)
    if default_font:
        fam = _esc(default_font)
        hp = _halfpt(default_size or 16)
        parts.append('<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/>'
                     '<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>'
                     % (fam, fam, fam, hp, hp))
    if sect:
        parts.append(sect)
    return "<w:pPr>%s</w:pPr>" % "".join(parts) if parts else ""


def para_xml(runs, **kw):
    return "<w:p>%s%s</w:p>" % (_ppr(**kw), runs)


def frame_para_xml(x_pt, y_pt, w_pt, line_pt, runs):
    """A paragraph pinned to an absolute spot on the page.

    w:framePr with page anchors takes the paragraph out of the normal flow, so
    hundreds of them can sit on one page without pushing each other around -
    which is exactly what a PDF page is. Line spacing is 'atLeast' rather than
    'exact' on purpose: exact spacing clips Thai tone marks, which stack two
    levels above the base character."""
    frame = ('<w:framePr w:w="%d" w:hSpace="0" w:vSpace="0" w:wrap="none" '
             'w:hAnchor="page" w:vAnchor="page" w:x="%d" w:y="%d" '
             'w:hRule="auto"/>' % (_tw(w_pt), _tw(x_pt), _tw(y_pt)))
    spacing = ('<w:spacing w:before="0" w:after="0" w:line="%d" '
               'w:lineRule="atLeast"/>' % _tw(line_pt))
    return "<w:p>%s%s</w:p>" % (_ppr(frame=frame, spacing=spacing), runs)


def _pic_xml(rid, pic_id, cx, cy):
    """The <a:graphic> payload shared by inline and anchored pictures."""
    return (
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="%d" name="Picture %d"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic>' % (pic_id, pic_id, rid, cx, cy))


def inline_pic_xml(rid, pic_id, w_pt, h_pt):
    cx, cy = _emu(w_pt), _emu(h_pt)
    return ('<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            '<wp:extent cx="%d" cy="%d"/>'
            '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
            '<wp:docPr id="%d" name="Picture %d"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'noChangeAspect="1"/></wp:cNvGraphicFramePr>%s'
            '</wp:inline></w:drawing></w:r>'
            % (cx, cy, pic_id, pic_id, _pic_xml(rid, pic_id, cx, cy)))


def anchored_pic_xml(rid, pic_id, x_pt, y_pt, w_pt, h_pt, z=1):
    """A picture nailed to page coordinates and pushed behind the text, so
    scans and logos sit under the frames instead of shoving them aside."""
    cx, cy = _emu(w_pt), _emu(h_pt)
    return ('<w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" '
            'simplePos="0" relativeHeight="%d" behindDoc="1" locked="0" '
            'layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/>'
            '<wp:positionH relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionV>'
            '<wp:extent cx="%d" cy="%d"/>'
            '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            '<wp:docPr id="%d" name="Picture %d"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'noChangeAspect="1"/></wp:cNvGraphicFramePr>%s'
            '</wp:anchor></w:drawing></w:r>'
            % (z, _emu(x_pt), _emu(y_pt), cx, cy, pic_id, pic_id,
               _pic_xml(rid, pic_id, cx, cy)))


_MAX_TWIP = 31680      # Word's hard limit on a page dimension (22 inches)


def sect_xml(pw, ph, margins, header=None, footer=None, header_dist=0.0,
             footer_dist=0.0, pgnum=None):
    """<w:sectPr>. `header`/`footer` are relationship ids of those parts,
    `pgnum` an optional (number format, first page number)."""
    left, top, right, bottom = margins
    w = min(_tw(pw), _MAX_TWIP)
    h = min(_tw(ph), _MAX_TWIP)
    orient = ' w:orient="landscape"' if pw > ph else ""
    refs = ""
    if header:
        refs += '<w:headerReference w:type="default" r:id="%s"/>' % header
    if footer:
        refs += '<w:footerReference w:type="default" r:id="%s"/>' % footer
    return ('<w:sectPr>%s<w:type w:val="nextPage"/>'
            '<w:pgSz w:w="%d" w:h="%d"%s/>'
            '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
            'w:header="%d" w:footer="%d" w:gutter="0"/>%s'
            '<w:cols w:space="0"/></w:sectPr>'
            % (refs, w, h, orient, _tw(top), _tw(right), _tw(bottom), _tw(left),
               _tw(header_dist), _tw(footer_dist),
               '<w:pgNumType w:fmt="%s" w:start="%d"/>' % pgnum if pgnum else ""))


# ================================================================ the zip file
_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')

_XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'


class DocxWriter:
    """Collects the parts of a .docx and writes the zip."""

    _PART_TYPES = {
        "header": ("hdr", "application/vnd.openxmlformats-officedocument."
                          "wordprocessingml.header+xml"),
        "footer": ("ftr", "application/vnd.openxmlformats-officedocument."
                          "wordprocessingml.footer+xml"),
    }

    def __init__(self):
        self.media = []      # (filename, bytes)
        self.rels = []       # (rId, type, target)
        self.parts = []      # (zip name, xml, content type)
        self.fonts = []      # (family, [(style, rId, key, file name, bytes)])
        self._next_rel = 3   # rId1 = styles, rId2 = settings
        self._next_pic = 1

    def _rel(self, kind, target):
        rid = "rId%d" % self._next_rel
        self._next_rel += 1
        self.rels.append((rid, kind, target))
        return rid

    def add_part(self, kind, paras):
        """A header or footer holding `paras`; returns its relationship id."""
        root, ctype = self._PART_TYPES[kind]
        name = "%s%d.xml" % (kind, sum(1 for p in self.parts if kind in p[0]) + 1)
        xml = _XML_HEAD + "<w:%s %s>%s</w:%s>" % (root, _NS, paras, root)
        self.parts.append(("word/" + name, xml, ctype))
        return self._rel(kind, name)

    def embed_fonts(self, used):
        """Embed the shipped TrueType files for the families in `used`
        ({family: {style}}), so the document looks the same on a machine
        that does not have them installed."""
        index = _font_index()
        n = 0
        for family in sorted(used):
            key = _fkey(family)
            if key in _WINDOWS_FAMILIES or key not in index:
                continue
            name, files = index[key]
            if name != family:
                continue        # Word matches by exact name; a near miss is useless
            styles = set(used[family]) | {"Regular"}
            entries = []
            for style in ("Regular", "Bold", "Italic", "BoldItalic"):
                if style not in styles or style not in files:
                    continue
                try:
                    with open(files[style], "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                n += 1
                fkey = "{%s}" % str(uuid.uuid4()).upper()
                entries.append((style, "rId%d" % n, fkey, "font%d.odttf" % n,
                                obfuscate_font(data, fkey)))
            if entries:
                self.fonts.append((family, entries))
        if self.fonts:
            self._rel("fontTable", "fontTable.xml")
        return [f for f, _e in self.fonts]

    def _font_table(self):
        ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
        fonts = []
        for family, entries in self.fonts:
            embeds = "".join('<w:embed%s r:id="%s" w:fontKey="%s"/>'
                             % (style, rid, key) for style, rid, key, _n, _d in entries)
            fonts.append('<w:font w:name="%s"><w:pitch w:val="variable"/>%s</w:font>'
                         % (_esc(family), embeds))
        rels = "".join(
            '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/font" Target="fonts/%s"/>'
            % (rid, name) for _f, entries in self.fonts
            for _s, rid, _k, name, _d in entries)
        return (_XML_HEAD + "<w:fonts %s>%s</w:fonts>" % (ns, "".join(fonts)),
                _XML_HEAD + '<Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships">' + rels + "</Relationships>")

    def add_image(self, data, ext):
        """Store an image part; returns its relationship id."""
        ext = "jpeg" if ext in ("jpg", "jpeg") else "png"
        name = "image%d.%s" % (len(self.media) + 1, ext)
        self.media.append((name, data))
        return self._rel("image", "media/" + name)

    def pic_id(self):
        """Drawing ids have to be unique across the document and non-zero."""
        self._next_pic += 1
        return self._next_pic

    # ---------- the fixed parts ----------
    def _content_types(self):
        exts = {os.path.splitext(n)[1][1:].lower() for n, _ in self.media}
        defaults = ['<Default Extension="rels" ContentType="application/'
                    'vnd.openxmlformats-package.relationships+xml"/>',
                    '<Default Extension="xml" ContentType="application/xml"/>']
        for e in sorted(exts):
            defaults.append('<Default Extension="%s" ContentType="image/%s"/>'
                            % (e, "jpeg" if e in ("jpg", "jpeg") else e))
        if self.fonts:
            defaults.append('<Default Extension="odttf" ContentType="application/'
                            'vnd.openxmlformats-officedocument.obfuscatedFont"/>')
            defaults.append('<Override PartName="/word/fontTable.xml" '
                            'ContentType="application/vnd.openxmlformats-'
                            'officedocument.wordprocessingml.fontTable+xml"/>')
        for name, _xml, ctype in self.parts:
            defaults.append('<Override PartName="/%s" ContentType="%s"/>'
                            % (name, ctype))
        return (_XML_HEAD +
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                'content-types">' + "".join(defaults) +
                '<Override PartName="/word/document.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '<Override PartName="/word/styles.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                '<Override PartName="/word/settings.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
                '<Override PartName="/docProps/core.xml" ContentType="application/'
                'vnd.openxmlformats-package.core-properties+xml"/>'
                '<Override PartName="/docProps/app.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.extended-properties+xml"/>'
                '</Types>')

    @staticmethod
    def _root_rels():
        base = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
        return (_XML_HEAD +
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                '2006/relationships">'
                '<Relationship Id="rId1" Type="%sofficeDocument" Target="word/document.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
                'package/2006/relationships/metadata/core-properties" '
                'Target="docProps/core.xml"/>'
                '<Relationship Id="rId3" Type="%sextended-properties" '
                'Target="docProps/app.xml"/></Relationships>' % (base, base))

    def _doc_rels(self):
        base = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
        out = ['<Relationship Id="rId1" Type="%sstyles" Target="styles.xml"/>' % base,
               '<Relationship Id="rId2" Type="%ssettings" Target="settings.xml"/>' % base]
        for rid, kind, target in self.rels:
            out.append('<Relationship Id="%s" Type="%s%s" Target="%s"/>'
                       % (rid, base, kind, target))
        return (_XML_HEAD +
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                '2006/relationships">' + "".join(out) + "</Relationships>")

    @staticmethod
    def _styles(font, size_pt):
        """docDefaults so that anything the user types afterwards also comes out
        in the document's own Thai font instead of Word's Calibri default."""
        fam = _esc(font)
        hp = _halfpt(size_pt)
        return (_XML_HEAD +
                '<w:styles %s><w:docDefaults><w:rPrDefault><w:rPr>'
                '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s" w:eastAsia="%s"/>'
                '<w:sz w:val="%d"/><w:szCs w:val="%d"/>'
                '<w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="th-TH"/>'
                '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
                '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>'
                '</w:pPr></w:pPrDefault></w:docDefaults>'
                '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
                '<w:name w:val="Normal"/><w:qFormat/></w:style></w:styles>'
                % (_NS, fam, fam, fam, fam, hp, hp))

    def _settings(self):
        # embedTrueTypeFonts also tells Word to keep the fonts embedded when
        # the user saves the file again
        embed = "<w:embedTrueTypeFonts/>" if self.fonts else ""
        return (_XML_HEAD +
                '<w:settings %s>%s<w:defaultTabStop w:val="720"/><w:compat>'
                '<w:compatSetting w:name="compatibilityMode" '
                'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>'
                '</w:compat></w:settings>' % (_NS, embed))

    @staticmethod
    def _core(title):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return (_XML_HEAD +
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
                'package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                '<dc:title>%s</dc:title><dc:creator>WnyEditPDF</dc:creator>'
                '<cp:lastModifiedBy>WnyEditPDF</cp:lastModifiedBy>'
                '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
                '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
                '</cp:coreProperties>' % (_esc(title or ""), now, now))

    @staticmethod
    def _app():
        return (_XML_HEAD +
                '<Properties xmlns="http://schemas.openxmlformats.org/'
                'officeDocument/2006/extended-properties">'
                '<Application>WnyEditPDF</Application></Properties>')

    def write(self, path, body, font, size_pt, title=""):
        doc = (_XML_HEAD + '<w:document %s><w:body>%s</w:body></w:document>'
               % (_NS, body))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", self._content_types())
            z.writestr("_rels/.rels", self._root_rels())
            z.writestr("docProps/core.xml", self._core(title))
            z.writestr("docProps/app.xml", self._app())
            z.writestr("word/document.xml", doc)
            z.writestr("word/_rels/document.xml.rels", self._doc_rels())
            z.writestr("word/styles.xml", self._styles(font, size_pt))
            z.writestr("word/settings.xml", self._settings())
            for name, xml, _ctype in self.parts:
                z.writestr(name, xml)
            if self.fonts:
                table, rels = self._font_table()
                z.writestr("word/fontTable.xml", table)
                z.writestr("word/_rels/fontTable.xml.rels", rels)
                for _family, entries in self.fonts:
                    for _s, _rid, _k, name, data in entries:
                        z.writestr("word/fonts/" + name, data)
            for name, data in self.media:
                # PNG/JPEG are already compressed - deflating again only burns CPU
                z.writestr(zipfile.ZipInfo("word/media/" + name), data,
                           zipfile.ZIP_STORED)


# ============================================================== page inspection
def _origin_key(p, ch):
    # the character is part of the key: a zero-width Thai mark is drawn at
    # the same origin as the letter after it
    return (round(p[0], 1), round(p[1], 1), ch)


def _font_cmap(doc, xref, cache):
    """{glyph id: [code points]} from an embedded font's own cmap."""
    if xref not in cache:
        rev = {}
        try:
            buf = doc.extract_font(xref)[3]
            font = fitz.Font(fontbuffer=buf) if buf else None
            for cp in (font.valid_codepoints() if font else []):
                rev.setdefault(font.has_glyph(cp), []).append(cp)
        except Exception:
            rev = {}
        cache[xref] = rev
    return cache[xref]


def glyph_fixes(page):
    """{char origin: correct character} for text whose ToUnicode map lies.

    Some producers write a broken ToUnicode table for one font: a Noto Sans
    Thai subset in the wild maps SARA AA to SARA AM and THO THONG, SARA E and
    THANTHAKHAT to spaces ("โรงพยำบำลนรำ ิวำส"). The embedded font's own cmap
    still says which character each glyph draws, so where the two disagree
    the font is believed - but only for a span where most characters agree,
    which proves we are reading the right font."""
    if page.rotation:
        return {}
    doc = page.parent
    cache = getattr(doc, "_wny_cmaps", None)
    if cache is None:
        cache = {}
        try:
            doc._wny_cmaps = cache
        except Exception:
            pass
    by_name = {}
    try:
        for f in doc.get_page_fonts(page.number):
            by_name.setdefault(_RE_SUBSET.sub("", f[3]), []).append(f[0])
        trace = page.get_texttrace()
    except Exception:
        return {}
    fixes = {}
    for span in trace:
        chars = span.get("chars") or []
        cands = by_name.get(_RE_SUBSET.sub("", span.get("font", "")), [])
        if not chars or not cands:
            continue
        best, best_ok = None, -1
        for xref in cands:
            rev = _font_cmap(doc, xref, cache)
            ok = sum(1 for c in chars if c[0] in rev.get(c[1], ()))
            if ok > best_ok:
                best, best_ok = rev, ok
        if not best or best_ok * 2 < len(chars) or best_ok == len(chars):
            continue
        for c in chars:
            # only a character that already looks wrong is replaced: a space
            # where a glyph was drawn, SARA AM, a private-use or replacement
            # code. Everything else the ToUnicode map says is kept - Thai
            # fonts also map shifted tone marks to private-use code points in
            # their cmap, and those must never win over a correct mark.
            if not (c[0] in _SUSPECT or 0xE000 <= c[0] <= 0xF8FF):
                continue
            cps = [cp for cp in best.get(c[1], ()) if not 0xE000 <= cp <= 0xF8FF
                   and cp > 0x20]
            if cps and c[0] not in cps:
                thai = [cp for cp in cps if 0x0E00 <= cp <= 0x0E7F]
                fixes[_origin_key(c[2], chr(c[0]))] = chr((thai or cps)[0])
    return fixes


_SUSPECT = {0x20, 0xA0, 0x0E33, 0xFFFD}


def page_blocks(page):
    """Text blocks of a page as {bbox, lines[{bbox, spans}]}, whitespace-only
    lines dropped. Coordinates are already in the rotated (on-screen) space -
    PyMuPDF applies the page rotation to text extraction but not to image
    placements, which is why only the images below need a matrix."""
    out = []
    fixes = glyph_fixes(page)
    try:
        d = page.get_text("rawdict" if fixes else "dict")
    except Exception:
        return out
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        lines = []
        for ln in b.get("lines", []):
            if fixes:
                for sp in ln.get("spans", []):
                    sp["text"] = "".join(
                        fixes.get(_origin_key(ch["origin"], ch["c"]), ch["c"])
                        for ch in sp.get("chars", []))
            spans = [sp for sp in ln.get("spans", []) if sp.get("text")]
            if not spans or not any(sp["text"].strip() for sp in spans):
                continue
            lines.append({"bbox": fitz.Rect(ln["bbox"]), "spans": spans,
                          "dir": tuple(ln.get("dir", (1.0, 0.0)))})
        if lines:
            out.append({"bbox": fitz.Rect(b["bbox"]), "lines": lines})
    return out


def page_images(page, skip_fullpage=False):
    """[(xref, rect)] of the pictures placed on a page, in viewer coordinates."""
    out = []
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:
        return out
    parea = page.rect.get_area() or 1.0
    for info in infos:
        urect = fitz.Rect(info["bbox"])
        if urect.is_empty or not info.get("xref"):
            continue
        if info.get("width", 99) <= 2 and info.get("height", 99) <= 2:
            continue                       # 1x1 ghost left behind by a delete
        rect = (fitz.Rect(urect) * page.rotation_matrix).normalize()
        if skip_fullpage and rect.get_area() > parea * 0.85:
            continue
        out.append((info["xref"], rect))
    return out


def image_part(doc, xref):
    """(bytes, ext) for an image xref, transparency kept. PDF stores alpha in a
    separate soft mask, so pulling only the base image would turn a signature's
    clear background black."""
    try:
        ex = doc.extract_image(xref)
    except Exception:
        return None, None
    data = ex.get("image")
    ext = (ex.get("ext") or "png").lower()
    if not data:
        return None, None
    if ex.get("smask"):
        try:
            base = fitz.Pixmap(data)
            if base.alpha:
                base = fitz.Pixmap(base, 0)
            mask = fitz.Pixmap(doc.extract_image(ex["smask"])["image"])
            data, ext = fitz.Pixmap(base, mask).tobytes("png"), "png"
        except Exception:
            pass
    if ext not in ("png", "jpeg", "jpg"):
        try:
            pix = fitz.Pixmap(data)
            if pix.colorspace is not None and pix.colorspace.n > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)     # CMYK / separation -> RGB
            data, ext = pix.tobytes("png"), "png"
        except Exception:
            return None, None
    return data, ("jpeg" if ext == "jpg" else ext)


_PNG_BUDGET = 900 * 1024


def page_picture(page, dpi):
    """Render a whole page. PNG keeps text-like pages crisp and tiny; a photo
    or scan blows past the budget, and those compress far better as JPEG."""
    scale = max(0.5, dpi / 72.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    data = pix.tobytes("png")
    if len(data) > _PNG_BUDGET:
        try:
            return pix.tobytes("jpeg", jpg_quality=88), "jpeg"
        except Exception:
            pass
    return data, "png"


# ================================================================= layout mode
def _line_segments(line):
    """A line's spans as (style key, repaired text) pairs; the key is exactly
    run_xml's formatting arguments."""
    segs = []
    for sp in line["spans"]:
        text = repair_text(sp.get("text", ""))
        if not text:
            continue
        fam, bold, ital, sup = span_style(sp)
        segs.append(((fam, round(float(sp.get("size", 12)), 1), _color(sp),
                      bold, ital, sup), text))
    return segs


def _segments_xml(segs):
    """Word runs for (key, text) pairs, adjacent pairs that share formatting
    merged so a single word does not become five runs."""
    merged = []
    for key, text in segs:
        if merged and merged[-1][0] == key:
            merged[-1][1].append(text)
        else:
            merged.append((key, [text]))
    return "".join(run_xml("".join(chunks), *key) for key, chunks in merged)


def _line_runs(line):
    return _segments_xml(_line_segments(line))


def layout_page(page, blocks, images, writer, pw, ph, scale=1.0):
    """Every line of the page as an absolutely positioned frame, with the
    pictures anchored behind them. `blocks` are already scaled by `scale`
    (see _scaled_blocks); `images` are in page coordinates."""
    body = []
    for xref, rect in images:
        data, ext = image_part(page.parent, xref)
        if not data:
            continue
        rid = writer.add_image(data, ext)
        body.append(anchored_pic_xml(rid, writer.pic_id(), rect.x0 * scale,
                                     rect.y0 * scale, rect.width * scale,
                                     rect.height * scale))
    frames = []
    for blk in blocks:
        for line in blk["lines"]:
            runs = _line_runs(line)
            if not runs:
                continue
            r = line["bbox"]
            size = max((float(sp.get("size", 12)) for sp in line["spans"]),
                       default=12.0)
            # Word measures text a hair wider than the PDF did, so give every
            # frame slack: too narrow and the line wraps, which is the one way
            # a frame can still ruin the layout.
            width = min(max(r.width * 1.10 + 8.0, size * 2), max(pw - r.x0, 20.0))
            x = max(0.0, min(r.x0, pw - 10.0))
            y = max(0.0, min(r.y0, ph - 6.0))
            frames.append((y, x, frame_para_xml(x, y, width,
                                                max(r.height, size * 1.05), runs)))
    frames.sort(key=lambda t: (t[0], t[1]))
    return [f[2] for f in frames], "".join(body)


def _fit_scale(pw, ph):
    """Shrink factor that brings a page within Word's 22 inch limit."""
    return min(1.0, _MAX_TWIP / 20.0 / max(pw, ph, 1.0))


def _scaled_blocks(blocks, s):
    """Copies of `blocks` with every box and font size multiplied by `s`."""
    if s == 1.0:
        return blocks
    out = []
    for blk in blocks:
        lines = []
        for ln in blk["lines"]:
            spans = [dict(sp, size=float(sp.get("size", 12)) * s) for sp in ln["spans"]]
            lines.append(dict(ln, bbox=ln["bbox"] * s, spans=spans))
        out.append(dict(blk, bbox=blk["bbox"] * s, lines=lines))
    return out


def _is_flat(line):
    """Horizontal text - the only kind a Word frame can hold."""
    dx_, dy_ = line.get("dir", (1.0, 0.0))
    return dx_ > 0.99 and abs(dy_) < 0.05


def is_designed(page, blocks):
    """A page made to be looked at rather than read: a cover, a divider, a
    poster. Turned or giant lettering, or artwork (pictures and filled
    shapes) over much of the page, with not much text on it."""
    lines = [ln for blk in blocks for ln in blk["lines"]]
    if lines and _is_diagram(page, lines):
        return True
    if len(lines) > 60:
        return False
    if len(lines) <= 40:
        if any(not _is_flat(ln) for ln in lines):
            return True
        if any(float(sp.get("size", 0)) >= 36 for ln in lines for sp in ln["spans"]):
            return True
    area = page.rect.get_area() or 1.0
    covered = sum((r & page.rect).get_area() for _x, r in page_images(page))
    if covered < area * 0.45:
        try:
            drawings = _drawings(page)
        except Exception:
            drawings = []
        for d in drawings:
            fill = d.get("fill")
            if fill and min(fill) < 0.92:          # a coloured, not white, shape
                covered += (fitz.Rect(d["rect"]) & page.rect).get_area()
    return covered >= area * 0.45


def graphic_regions(page, tables=None):
    """Areas of the page drawn with vector graphics - charts, diagrams, org
    charts - as rectangles, tables left out. Word has nowhere to put PDF
    line art, so the flowing export pictures these areas instead of losing
    them. A lone rule or a box round a paragraph is not a region: it takes
    several shapes close together."""
    try:
        drawings = _drawings(page)
    except Exception:
        return []
    if len(drawings) < 4:
        return []
    if tables is None:
        tables = _find_tables(page)
    trects = [fitz.Rect(t.bbox) + (-3, -3, 3, 3) for t in tables]
    area = page.rect.get_area()
    clusters = []                   # [rect, shape count]
    for d in drawings:
        r = fitz.Rect(d["rect"])
        if r.width * r.height > area * 0.8:
            continue                # a page background
        mid = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if any(t.contains(mid) for t in trects):
            continue
        r = fitz.Rect(r.x0 - 6, r.y0 - 6, r.x1 + 6, r.y1 + 6)
        clusters.append([r, len(d.get("items", ())) or 1])
    merged = True
    while merged:
        merged = False
        out = []
        for c in clusters:
            for o in out:
                if o[0].intersects(c[0]):
                    o[0] |= c[0]
                    o[1] += c[1]
                    merged = True
                    break
            else:
                out.append(c)
        clusters = out
    return [fitz.Rect(r.x0 + 6, r.y0 + 6, r.x1 - 6, r.y1 - 6) & page.rect
            for r, n in clusters if n >= 6 and r.width >= 72 and r.height >= 52]


def _is_diagram(page, lines):
    """An org chart or a full-page diagram: most of the page's text sits
    inside drawn graphics. That text has no reading order to flow in - out of
    its boxes it is a heap of labels - so the page is pinned whole."""
    if len(lines) < 8:
        return False
    regions = graphic_regions(page)
    if not regions:
        return False
    # counted in characters, not lines: a chart's forty axis labels must not
    # outvote the three real paragraphs above it
    total = inside = 0
    for ln in lines:
        n = len(_line_text(ln).strip())
        total += n
        mid = fitz.Point((ln["bbox"].x0 + ln["bbox"].x1) / 2,
                         (ln["bbox"].y0 + ln["bbox"].y1) / 2)
        if any(r.contains(mid) for r in regions):
            inside += n
    return total > 0 and inside >= total * 0.7


def _designed_section(page, blocks, writer, dpi, s, default_font, carrier):
    """A designed page pinned as it is: the page drawn without its horizontal
    text as a background picture, that text in frames on top. Turned text
    stays in the picture - a frame cannot turn."""
    pw, ph = page.rect.width, page.rect.height
    flat = [dict(blk, lines=[ln for ln in blk["lines"] if _is_flat(ln)])
            for blk in blocks]
    flat = [blk for blk in flat if blk["lines"]]
    data, ext = _text_free_picture(page, [ln for blk in flat for ln in blk["lines"]], dpi)
    rid = writer.add_image(data, ext)
    background = anchored_pic_xml(rid, writer.pic_id(), 0, 0, pw * s, ph * s)
    frames, _ = layout_page(page, _scaled_blocks(flat, s), [], writer,
                            pw * s, ph * s, s)
    return (frames + [para_xml(background, spacing=carrier,
                               default_font=default_font, default_size=1)],
            {"pw": pw * s, "ph": ph * s, "margins": (0, 0, 0, 0)})


def _text_free_picture(page, lines, dpi):
    """The page rendered with the given lines' text removed - shapes, photos
    and everything else left exactly as they are."""
    tmp = fitz.open()
    try:
        tmp.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
        p = tmp[0]
        for ln in lines:
            # fill=False: take the letters away, paint nothing in their place
            p.add_redact_annot(ln["bbox"] * p.derotation_matrix, fill=False)
        p.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                           graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                           text=fitz.PDF_REDACT_TEXT_REMOVE)
        return page_picture(p, dpi)
    except Exception:
        return page_picture(page, dpi)       # text twice beats no artwork
    finally:
        tmp.close()


# =================================================================== flow mode
# A PDF only knows lines and Word only knows paragraphs, so the flowing export
# has to rebuild what the PDF threw away. PyMuPDF's blocks are no substitute:
# a Word-made PDF routinely puts a centred subtitle, a heading and three body
# paragraphs into one block, and pouring that into one Word paragraph is what
# wrecked the old flowing export. Instead a line joins the paragraph above it
# only when that paragraph's last line ran out of room, the gap between them is
# ordinary leading, it starts where the paragraph's other lines start and it is
# not the next item of a list. That also stitches together a paragraph the PDF
# split across a page break, so the text flows in Word like typed text.

_BAND = 0.08      # share of the page height where running headers/footers sit

# a printed page number: 12, ๑๒, a Thai letter (front matter: ก ข ค) or a
# roman numeral, optionally "หน้า"/"page" before and "/ 30" after
_PAGE_TOKEN = r"(?:[0-9]{1,4}|[๐-๙]{1,4}|[ก-ฮ]|[ivxlc]{1,6}|[IVXLC]{1,6})"
_RE_PAGE_NO = re.compile(
    r"^[\s\-–—|]*(?:(?:หน้า|[Pp]age|[Pp]\.)\s*)?(%s)"
    r"(?:\s*(?:/|of|จาก)\s*([0-9๐-๙]{1,4}))?[\s\-–—|]*$" % _PAGE_TOKEN)

# a table-of-contents leader: "บทที่ 1 ........ 12"
_RE_LEADER = re.compile(r"[ \t]*(?:[.…·_][ \t]?){4,}[ \t]*(?=%s[ \t]*$)" % _PAGE_TOKEN)

# Word's "thaiLetters" page numbering skips the obsolete ฃ and ฅ
_THAI_LETTERS = "กขคงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"


def _roman(s):
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    total = 0
    for a, b in zip(s.lower(), s.lower()[1:] + " "):
        v = vals[a]
        total += -v if vals.get(b, 0) > v else v
    return total


def page_label(token):
    """(Word page number format, value) of a printed page number, or None."""
    if token.isdigit() and token.isascii():
        return "decimal", int(token)
    if token and all("๐" <= c <= "๙" for c in token):
        return "thaiNumbers", int("".join(str(ord(c) - 0x0E50) for c in token))
    if len(token) == 1 and token in _THAI_LETTERS:
        return "thaiLetters", _THAI_LETTERS.index(token) + 1
    if re.fullmatch("[ivxlc]+", token):
        return "lowerRoman", _roman(token)
    if re.fullmatch("[IVXLC]+", token):
        return "upperRoman", _roman(token)
    return None


def _page_number_of(blocks, ph):
    """The page's printed number as page_label() gives it, or None."""
    for blk in blocks:
        for line in blk["lines"]:
            r = line["bbox"]
            if r.y1 <= ph * _BAND or r.y0 >= ph * (1 - _BAND):
                m = _RE_PAGE_NO.match(_line_text(line))
                if m:
                    return page_label(m.group(1))
    return None

# the start of a list item: a bullet, "1." "1)" "(1)" "1.2" "ก." "a)"
_RE_MARKER = re.compile(
    r"^\s*(?:[●•○◦■□▪▫◆◇►▶➢➤✓✔❖\-–—*]"
    r"|\(?[0-9๐-๙]{1,3}(?:(?:\.[0-9๐-๙]{1,3})+\.?|[.)])"
    r"|\(?[A-Za-zก-ฮ][.)])(?=\s)")


def _line_text(line):
    return "".join(repair_text(sp.get("text", "")) for sp in line["spans"])


def _line_size(line):
    return max((float(sp.get("size", 12)) for sp in line["spans"]), default=12.0)


def _is_thai(ch):
    return bool(ch) and 0x0E00 <= ord(ch) <= 0x0E7F


def _joiner(prev, nxt):
    """What to put between two lines of the same paragraph. Thai is written
    without spaces between words, so gluing wrapped Thai lines with a space
    would insert a word break that was never in the document."""
    if not prev or not nxt:
        return ""
    if prev[-1].isspace() or nxt[0].isspace():
        return ""
    if _is_thai(prev[-1]) and _is_thai(nxt[0]):
        return ""
    return " "


def _furniture_key(text):
    return re.sub("[0-9๐-๙]+", "#", "".join(text.split()))


def find_furniture(pages):
    """Running headers, footers and page numbers.

    `pages` is [(blocks, page height)]. A line counts when it sits in the top
    or bottom band of its page and is either a bare page number or text that
    repeats on most of the pages. Left in a flowing document they would turn
    up mid-sentence wherever the old page break happened to be. Returns, per
    page, the set of (block index, line index)."""
    candidates = []
    seen = {}
    for blocks, ph in pages:
        mine = []
        for bi, blk in enumerate(blocks):
            for li, line in enumerate(blk["lines"]):
                r = line["bbox"]
                if r.y1 <= ph * _BAND or r.y0 >= ph * (1 - _BAND):
                    text = _line_text(line)
                    if text.strip():
                        mine.append((bi, li, text))
        candidates.append(mine)
        for key in {_furniture_key(t) for _b, _l, t in mine}:
            seen[key] = seen.get(key, 0) + 1
    need = max(2, (len(pages) + 1) // 2)
    return [{(bi, li) for bi, li, text in mine
             if _RE_PAGE_NO.match(text) or seen[_furniture_key(text)] >= need}
            for mine in candidates]


def _same_row(a, b):
    """`b` sits on the same baseline as `a`, further right: a tabbed row."""
    ra, rb = a["bbox"], b["bbox"]
    overlap = min(ra.y1, rb.y1) - max(ra.y0, rb.y0)
    return overlap > 0.5 * min(ra.height, rb.height) and rb.x0 >= ra.x1 - 1


def _continues(para, line, new_page):
    """Does `line` carry on the paragraph `para`?"""
    rows = para["rows"]
    if len(rows[-1]) > 1:                  # a tabbed row stands on its own
        return False
    last = rows[-1][0]
    ra, rb = last["bbox"], line["bbox"]
    size = _line_size(last)
    if abs(size - _line_size(line)) > 0.6:
        return False
    if _RE_MARKER.match(_line_text(line)):
        return False
    # a contents entry ends at its page number, however wide the line is
    if _RE_LEADER.search(_line_text(last)):
        return False
    if not new_page:
        if rb.y0 < ra.y0 + 0.5 * ra.height:      # beside it, not below it
            return False
        if rb.y0 - ra.y1 > 0.5 * size:           # a paragraph gap
            return False
    left, right = last["_left"], last["_right"]
    # the line above stopped well short of the margin: it ended on purpose
    if ra.x1 < right - max(3.0 * size, (right - left) * 0.1):
        return False
    if len(rows) >= 2:
        return abs(rb.x0 - rows[1][0]["bbox"].x0) <= 3.0
    return left - 3.0 <= rb.x0 <= rows[0][0]["bbox"].x0 + 2.5 * size + 3.0


def _group(stream):
    """Turn a reading-order stream of ("line", page, line) items into
    ("para", page, {"rows": [[line, ...], ...]}) items. Anything else passes
    through untouched and ends the paragraph in progress."""
    out = []
    cur = None
    for item in stream:
        kind, pno, obj = item
        if kind != "line":
            cur = None
            out.append(item)
            continue
        if cur is not None:
            if cur["last_page"] == pno and _same_row(cur["rows"][-1][-1], obj):
                cur["rows"][-1].append(obj)
                continue
            if _continues(cur, obj, cur["last_page"] != pno):
                cur["rows"].append([obj])
                cur["last_page"] = pno
                continue
        cur = {"rows": [[obj]], "last_page": pno}
        out.append(("para", pno, cur))
    return out


def _pitches(paras):
    """size -> the document's own distance between line tops (its line
    spacing), measured from the paragraphs that have more than one line."""
    per = {}
    for p in paras:
        rows = p["rows"]
        for a, b in zip(rows, rows[1:]):
            size = _line_size(a[0])
            d = b[0]["bbox"].y0 - a[0]["bbox"].y0
            if 0.8 * size < d < 3.0 * size:
                per.setdefault(round(size), []).append(d)
    med = {s: sorted(ds)[len(ds) // 2] for s, ds in per.items()}
    ratios = sorted(d / s for s, ds in per.items() for d in ds)
    ratio = ratios[len(ratios) // 2] if ratios else None

    def pitch(size):
        if round(size) in med:
            return med[round(size)]
        return ratio * size if ratio else None
    return pitch


def _strip(segs):
    """Drop the spaces a PDF leaves at both ends of a line - in Word they
    would push a centred heading off-centre."""
    segs = list(segs)
    while segs and not segs[0][1].lstrip(" "):
        segs.pop(0)
    if segs:
        segs[0] = (segs[0][0], segs[0][1].lstrip(" "))
    while segs and not segs[-1][1].rstrip(" "):
        segs.pop()
    if segs:
        segs[-1] = (segs[-1][0], segs[-1][1].rstrip(" "))
    return segs


def _splice(segs, start, end, repl):
    """Replace characters [start, end) of the joined segment text."""
    out = []
    pos = 0
    done = False
    for key, text in segs:
        a, b = pos, pos + len(text)
        pos = b
        if b <= start or a >= end:
            out.append((key, text))
            continue
        piece = text[:max(0, start - a)] + ("" if done else repl)
        if end < b:
            piece += text[end - a:]
        done = True
        if piece:
            out.append((key, piece))
    return out


def _para_segments(rows, left):
    """(segments, tab stops) for a paragraph's rows."""
    segs, tabs, text = [], [], ""
    for ri, row in enumerate(rows):
        for li, line in enumerate(row):
            ls = _line_segments(line)
            if not ls:
                continue
            lt = "".join(t for _k, t in ls)
            glue = ""
            if li > 0:
                glue = "\t"
                tabs.append(max(0.0, line["bbox"].x0 - left))
            elif ri > 0 and text:
                glue = _joiner(text, lt)
            if glue:
                segs.append((ls[0][0], glue))
                text += glue
            segs.extend(ls)
            text += lt
    return segs, tabs


def _flow_para(rows, left, right, before, pitch, default_font, default_size,
               indent=True, page_break=False, border=None):
    """One rebuilt paragraph as <w:p>, or None if it holds no text."""
    segs, tabs = _para_segments(rows, left)
    segs = _strip(segs)
    if not segs:
        return None
    xs0 = [row[0]["bbox"].x0 for row in rows]
    xs1 = [row[-1]["bbox"].x1 for row in rows]
    width = max(1.0, right - left)
    mid = (left + right) / 2

    # "Chapter 1 ........ 12": the dots become a right-aligned tab with a dot
    # leader, so the number stays at the margin however Word wraps the title
    full = "".join(t for _k, t in segs)
    m = _RE_LEADER.search(full)
    if m:
        segs = _splice(segs, m.start(), m.end(), "\t")
        tabs = tabs + [(width, "right", "dot")]

    jc = None
    if not tabs:                    # alignment would drag the tab stops along
        if min(xs0) > left + 12 and all(
                abs((a + b) / 2 - mid) < max(6.0, width * 0.02)
                for a, b in zip(xs0, xs1)):
            jc = "center"
        elif len(rows) == 1 and xs1[0] > right - 6 and xs0[0] > left + width * 0.45:
            jc = "right"
        elif len(rows) >= 3 and all(x > right - max(2.5, width * 0.015)
                                    for x in xs1[:-1]):
            # Thai justification spreads the letters and leaves the last line
            # alone, which is what a justified Thai PDF looks like
            thai = sum(1 for c in full if _is_thai(c))
            jc = "thaiDistribute" if thai > len(full) / 2 else "both"

    ind = None
    if indent and jc in (None, "both", "thaiDistribute"):
        first_x = xs0[0]
        cont_x = xs0[1] if len(rows) > 1 else first_x
        bits = []
        if cont_x - left > 2:
            bits.append('w:left="%d"' % _tw(cont_x - left))
        if first_x - cont_x > 2:
            bits.append('w:firstLine="%d"' % _tw(first_x - cont_x))
        elif cont_x - first_x > 2:
            bits.append('w:hanging="%d"' % _tw(cont_x - first_x))
            # "● text" on a hanging indent: a tab after the marker lines the
            # first line's text up with the rest, the way Word's own lists do
            full = "".join(t for _k, t in segs)
            m = _RE_MARKER.match(full)
            if m:
                end = m.end()
                while end < len(full) and full[end] == " ":
                    end += 1
                if end > m.end():
                    segs = _splice(segs, m.end(), end, "\t")
        if bits:
            ind = "<w:ind %s/>" % " ".join(bits)

    # 'atLeast' rather than 'exact': exact clips Thai tone marks whenever the
    # line ends up taller than the PDF's, e.g. with a fallback font
    if pitch:
        spacing = ('<w:spacing w:before="%d" w:after="0" w:line="%d" '
                   'w:lineRule="atLeast"/>' % (_tw(before), _tw(pitch)))
    else:
        spacing = ('<w:spacing w:before="%d" w:after="0" w:line="240" '
                   'w:lineRule="auto"/>' % _tw(before))
    return para_xml(_segments_xml(segs), tabs=tabs or None, spacing=spacing,
                    ind=ind, jc=jc, default_font=default_font,
                    default_size=default_size, page_break=page_break,
                    border=border)


def page_rules(page, exclude=()):
    """Horizontal rules drawn on the page, as [(x0, x1, y, thickness,
    colour hex)], leaving out any inside the `exclude` rectangles (tables)."""
    out = []
    try:
        drawings = _drawings(page)
    except Exception:
        return out
    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) > 0.5:
                    continue
                x0, x1, y = min(p1.x, p2.x), max(p1.x, p2.x), p1.y
                thick = float(d.get("width") or 1.0)
                colour = d.get("color")
            elif item[0] == "re":
                r = fitz.Rect(item[1])
                if r.height > 4 or r.width < 20:
                    continue
                x0, x1, y, thick = r.x0, r.x1, (r.y0 + r.y1) / 2, max(r.height, 0.5)
                colour = d.get("fill") or d.get("color")
            else:
                continue
            if any(t.x0 - 2 <= (x0 + x1) / 2 <= t.x1 + 2 and t.y0 - 2 <= y <= t.y1 + 2
                   for t in exclude):
                continue
            rgb = "%02X%02X%02X" % tuple(int(round(c * 255)) for c in (colour or (0, 0, 0))[:3])
            out.append((x0, x1, y, thick, rgb))
    return out


def _border_below(rows, rules, left, right):
    """A <w:pBdr> for the rule(s) drawn just under the paragraph - the line
    under a chapter heading - taking them out of `rules`; None if none."""
    last = rows[-1]
    y1 = max(ln["bbox"].y1 for ln in last)
    need = (right - left) * 0.5
    mine = [r for r in rules
            if y1 - 2 <= r[2] <= y1 + 14 and min(r[1], right) - max(r[0], left) >= need]
    if not mine:
        return None
    for r in mine:
        rules.remove(r)
    mine.sort(key=lambda r: r[2])
    thick = max(r[3] for r in mine)
    if len(mine) == 1:
        style = "single"
    elif mine[0][3] > mine[-1][3] + 0.3:
        style = "thickThinSmallGap"
    elif mine[-1][3] > mine[0][3] + 0.3:
        style = "thinThickSmallGap"
    else:
        style = "double"
    sz = max(2, min(96, int(round(thick * 8))))
    return ('<w:pBdr><w:bottom w:val="%s" w:sz="%d" w:space="1" w:color="%s"/></w:pBdr>'
            % (style, sz, mine[0][4]))


def _hf_paras(lines, pw, default_font, default_size):
    """Header/footer paragraphs from one page's furniture lines. Page numbers
    become PAGE (and NUMPAGES) fields, so they keep counting once Word
    repaginates the flowing text."""
    out = []
    for line in sorted(lines, key=lambda ln: (ln["bbox"].y0, ln["bbox"].x0)):
        segs = _strip(_line_segments(line))
        if not segs:
            continue
        text = "".join(t for _k, t in segs)
        r = line["bbox"]
        cx = (r.x0 + r.x1) / 2
        jc = ("center" if abs(cx - pw / 2) < pw * 0.1
              else "right" if cx > pw / 2 else None)
        m = _RE_PAGE_NO.match(text)
        if m:
            key = segs[0][0]
            # PAGE takes its style (ก ข ค, ๑ ๒ ๓, i ii iii) from the section's
            # pgNumType; NUMPAGES has no section to follow
            runs = (run_xml(text[:m.start(1)], *key)
                    + field_xml("PAGE", m.group(1), key))
            tail = text[m.end(1):]
            if m.group(2):
                fmt = r" \* ThaiArabic" if _is_thai(m.group(2)[0]) else ""
                runs += (run_xml(text[m.end(1):m.start(2)], *key)
                         + field_xml("NUMPAGES" + fmt, m.group(2), key))
                tail = text[m.end(2):]
            runs += run_xml(tail, *key)
        else:
            runs = _segments_xml(segs)
        out.append(para_xml(runs, jc=jc,
                            spacing='<w:spacing w:before="0" w:after="0"/>',
                            default_font=default_font, default_size=default_size))
    return "".join(out)


# ------------------------------------------------------------------- tables
def _spans_in(lines, rect):
    """The lines whose centre falls inside `rect`: the cell's text."""
    out = []
    for line in lines:
        r = line["bbox"]
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if rect.x0 - 1 <= cx <= rect.x1 + 1 and rect.y0 - 1 <= cy <= rect.y1 + 1:
            out.append(line)
    out.sort(key=lambda ln: (round(ln["bbox"].y0, 1), ln["bbox"].x0))
    return out


def _grid_columns(cells, tol=3.0):
    """Column boundaries shared by every cell of the table."""
    xs = []
    for c in cells:
        if not c:
            continue
        for v in (c[0], c[2]):
            if not any(abs(v - x) <= tol for x in xs):
                xs.append(float(v))
    xs.sort()
    return xs


def _index(grid, value):
    """Index of the grid line nearest `value`."""
    return min(range(len(grid)), key=lambda i: abs(grid[i] - value))


def page_fills(page):
    """[(rect, colour hex)] of the coloured (not white) filled shapes."""
    out = []
    try:
        drawings = _drawings(page)
    except Exception:
        return out
    for d in drawings:
        fill = d.get("fill")
        if fill and min(fill[:3]) < 0.97:
            out.append((fitz.Rect(d["rect"]),
                        "%02X%02X%02X" % tuple(int(round(v * 255)) for v in fill[:3])))
    return out


def table_parts(table, lines, fills, pitch, default_font, default_size):
    """A detected ruled table as Word table rows, or None.

    PyMuPDF reports a cell with a coloured background as a stack of extra
    rows inside the real cell (the fill's edges look like rules), and rows
    that overlap each other. Writing those out as rows is what turned one
    table row into five. So the table is rebuilt from its cells instead:
    cells lying inside a bigger cell are dropped, the remaining edges make the
    grid, and a cell taller than one grid row becomes a vertical merge.

    Cell text comes from our own spans rather than table.extract(), which
    returns bare strings - going through the spans is what keeps each cell's
    font, size and weight. Returns {"xs", "widths", "rows": [(trHeight xml,
    cells xml, row text)]}."""
    cells = []
    for c in table.cells or []:
        if not c:
            continue
        r = fitz.Rect(c)
        if r.width > 2 and r.height > 2 and not any(
                abs(r.x0 - o.x0) < 1 and abs(r.y0 - o.y0) < 1
                and abs(r.x1 - o.x1) < 1 and abs(r.y1 - o.y1) < 1 for o in cells):
            cells.append(r)

    def inside(c, o):
        return (o is not c and o.x0 - 1.5 <= c.x0 and c.x1 <= o.x1 + 1.5
                and o.y0 - 1.5 <= c.y0 and c.y1 <= o.y1 + 1.5
                and o.get_area() > c.get_area() * 1.05)
    cells = [c for c in cells if not any(inside(c, o) for o in cells)]
    xs = _grid_columns([(c.x0, 0, c.x1, 0) for c in cells])
    ys = _grid_columns([(c.y0, 0, c.y1, 0) for c in cells])
    if len(xs) < 2 or len(ys) < 2:
        return None
    ncol, nrow = len(xs) - 1, len(ys) - 1
    widths = [xs[i + 1] - xs[i] for i in range(ncol)]

    owner = [[None] * ncol for _ in range(nrow)]
    spans = []                     # (rect, r0, r1, c0, c1)
    for c in sorted(cells, key=lambda c: (c.y0, c.x0)):
        c0, c1 = _index(xs, c.x0), _index(xs, c.x1)
        r0, r1 = _index(ys, c.y0), _index(ys, c.y1)
        if c1 <= c0 or r1 <= r0:
            continue
        if any(owner[r][k] is not None for r in range(r0, r1) for k in range(c0, c1)):
            continue
        for r in range(r0, r1):
            for k in range(c0, c1):
                owner[r][k] = len(spans)
        spans.append((c, r0, r1, c0, c1))

    tarea = fitz.Rect(table.bbox).get_area()
    shade, bodies, texts = {}, {}, {}
    for i, (c, _r0, _r1, _c0, _c1) in enumerate(spans):
        mid = fitz.Point((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2)
        hits = [(f.get_area(), col) for f, col in fills
                if f.contains(mid) and f.get_area() >= c.get_area() * 0.5
                and f.get_area() < tarea * 0.9]
        if hits:
            shade[i] = min(hits)[1]
        mine = _spans_in(lines, c)
        texts[i] = "".join(_line_text(ln) for ln in mine).strip()
        valign = "top"
        if mine:
            # a cell whose text sits in its middle is vertically centred
            top = min(ln["bbox"].y0 for ln in mine) - c.y0
            bottom = c.y1 - max(ln["bbox"].y1 for ln in mine)
            if top > 6 and abs(top - bottom) < max(4.0, c.height * 0.15):
                valign = "center"
        bodies[i] = (_cell_body(mine, c, pitch, default_font, default_size), valign)

    rows = []
    for r in range(nrow):
        tcs, text = [], []
        k = 0
        while k < ncol:
            own = owner[r][k]
            end = k
            while end < ncol and owner[r][end] == own:
                end += 1
            width = sum(widths[k:end])
            if own is None:
                tcs.append(_tc_xml(width, end - k, "", default_font, default_size))
            else:
                _c, r0, r1, _c0, _c1 = spans[own]
                merge = None if r1 - r0 == 1 else "restart" if r == r0 else "continue"
                body, valign = bodies[own]
                tcs.append(_tc_xml(width, end - k, body if r == r0 else "",
                                   default_font, default_size, merge=merge,
                                   fill=shade.get(own), valign=valign))
                if r == r0:
                    text.append(texts[own])
            k = end
        h = max(6.0, ys[r + 1] - ys[r])
        rows.append(('<w:trHeight w:val="%d" w:hRule="atLeast"/>' % _tw(h),
                     "".join(tcs), "|".join(text)))
    return {"xs": xs, "widths": widths, "rows": rows}


def table_continues(prev, nxt):
    """Is `nxt` (first thing on a page) the rest of `prev` (last thing on the
    page before)? Same columns, give or take a few points."""
    return (len(prev["xs"]) == len(nxt["xs"])
            and all(abs(a - b) < 3 for a, b in zip(prev["xs"], nxt["xs"])))


def join_table(prev, nxt):
    """Append `nxt`'s rows to `prev`. A header repeated at the top of the new
    page is dropped and the first table's header marked to repeat instead,
    which is how Word itself carries a header over a page break."""
    k = 0
    while (k < min(3, len(prev["rows"]), len(nxt["rows"]) - 1)
           and prev["rows"][k][2] and prev["rows"][k][2] == nxt["rows"][k][2]):
        k += 1
    prev["header"] = max(prev.get("header", 0), k)
    prev["rows"] = prev["rows"] + nxt["rows"][k:]
    return prev


def table_xml(parts):
    widths = parts["widths"]
    grid = "".join('<w:gridCol w:w="%d"/>' % _tw(w) for w in widths)
    borders = ("<w:tblBorders>" + "".join(
        '<w:%s w:val="single" w:sz="4" w:space="0" w:color="000000"/>' % side
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")
    ) + "</w:tblBorders>")
    tbl_pr = ('<w:tblPr><w:tblW w:w="%d" w:type="dxa"/>%s'
              '<w:tblLayout w:type="fixed"/><w:tblCellMar>'
              '<w:top w:w="0" w:type="dxa"/><w:left w:w="60" w:type="dxa"/>'
              '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="60" w:type="dxa"/>'
              '</w:tblCellMar></w:tblPr>' % (_tw(sum(widths)), borders))
    header = parts.get("header", 0)
    rows = "".join('<w:tr><w:trPr>%s%s</w:trPr>%s</w:tr>'
                   % (h, "<w:tblHeader/>" if i < header else "", tcs)
                   for i, (h, tcs, _t) in enumerate(parts["rows"]))
    return "<w:tbl>%s<w:tblGrid>%s</w:tblGrid>%s</w:tbl>" % (tbl_pr, grid, rows)


def _cell_body(lines, rect, pitch, default_font, default_size):
    """A cell's lines rebuilt into paragraphs, the cell being their column."""
    left, right = rect.x0 + 3.0, rect.x1 - 3.0      # 60 twips cell margin
    for line in lines:
        line["_left"], line["_right"] = left, right
    paras = []
    for _kind, _p, para in _group([("line", 0, ln) for ln in lines]):
        xml = _flow_para(para["rows"], left, right, 0.0,
                         pitch(_line_size(para["rows"][0][0])),
                         default_font, default_size, indent=False)
        if xml:
            paras.append(xml)
    return "".join(paras)


def _tc_xml(width_pt, span, body, default_font, default_size, merge=None,
            fill=None, valign="center"):
    """<w:tc>; tcPr children in schema order: tcW, gridSpan, vMerge, shd,
    vAlign."""
    pr = '<w:tcW w:w="%d" w:type="dxa"/>' % _tw(width_pt)
    if span > 1:
        pr += '<w:gridSpan w:val="%d"/>' % span
    if merge == "restart":
        pr += '<w:vMerge w:val="restart"/>'
    elif merge == "continue":
        pr += "<w:vMerge/>"
    if fill:
        pr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill
    pr += '<w:vAlign w:val="%s"/>' % valign
    if not body:
        body = para_xml("", default_font=default_font, default_size=default_size)
    return "<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>" % (pr, body)


def _page_cache(page):
    """Per-page memo for the expensive scans (drawings, tables), which the
    page classification and the section builder both need. Lives on the
    document and is dropped when the export ends."""
    doc = page.parent
    cache = getattr(doc, "_wny_page_cache", None)
    if cache is None:
        cache = {}
        try:
            doc._wny_page_cache = cache
        except Exception:
            pass
    return cache.setdefault(page.number, {})


def _drawings(page):
    memo = _page_cache(page)
    if "drawings" not in memo:
        memo["drawings"] = page.get_drawings()
    return memo["drawings"]


def _find_tables(page):
    memo = _page_cache(page)
    if "tables" not in memo:
        memo["tables"] = _scan_tables(page)
    return memo["tables"]


def _scan_tables(page):
    """Ruled tables on the page. "lines_strict" is preferred: it ignores the
    edges of filled shapes, and Word shades a cell paragraph line by
    paragraph line, which the plain strategy reads as a stack of tiny extra
    cells. The plain strategy still runs - alone it finds tables drawn with
    nothing but fills, and next to a strict table it supplies the header row
    that was marked out by shading only."""
    found = {}
    for strategy in ("lines_strict", "lines"):
        try:
            found[strategy] = [t for t in page.find_tables(strategy=strategy).tables
                               if t.row_count > 0 and t.col_count > 1]
        except Exception:
            found[strategy] = []
    strict, plain = found["lines_strict"], found["lines"]
    if not strict:
        return plain
    out = []
    for t in strict:
        r = fitz.Rect(t.bbox)
        cells = [c for c in t.cells if c]
        # a header row marked out by shading alone is invisible to "strict";
        # the plain table over the same spot has it, so its rows above or
        # below the strict table are added
        for o in plain:
            if (fitz.Rect(o.bbox) & r).get_area() < r.get_area() * 0.5:
                continue
            for row in o.rows:
                if row.bbox[3] <= r.y0 + 2 or row.bbox[1] >= r.y1 - 2:
                    cells += [c for c in row.cells if c]
                    r |= fitz.Rect(row.bbox)
        out.append(_Table(cells, tuple(r)))
    return out


class _Table:
    """The part of a PyMuPDF table that table_parts() uses."""

    def __init__(self, cells, bbox):
        self.cells, self.bbox = cells, bbox


# ---------------------------------------------------------------- a section
def _region_picture(page, rect, dpi):
    """A picture of one area of the page."""
    try:
        scale = max(1.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                              clip=rect + (-2, -2, 2, 2), alpha=False)
        return pix.tobytes("png"), "png"
    except Exception:
        return None, None


def _flow_section(pages, writer, default_font, default_size, want_tables=True,
                  dpi=200):
    """A run of same-sized pages as one Word section whose text flows freely
    from page to page. `pages` is [{"page", "blocks", "pw", "ph"}].
    Returns (block-level xml list, sect_xml keyword arguments)."""
    pw, ph = pages[0]["pw"], pages[0]["ph"]
    furniture = find_furniture([(p["blocks"], ph) for p in pages])

    # what each page holds, with headers/footers and table text set aside
    per_page = []
    for pi, p in enumerate(pages):
        tables = _find_tables(p["page"]) if want_tables else []
        trects = [fitz.Rect(t.bbox) for t in tables]
        # text counts as table text only inside an actual cell: anything
        # else inside the table's outline would be written nowhere
        cell_rects = [fitz.Rect(c) for t in tables for c in t.cells if c]
        # charts and diagrams drawn as line art go in as pictures of their
        # area, their labels with them
        regions = graphic_regions(p["page"], tables)
        groups, table_lines, hf = [], [], []
        for bi, blk in enumerate(p["blocks"]):
            body = []
            for li, line in enumerate(blk["lines"]):
                r = line["bbox"]
                cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
                home = [g for g in regions if g.contains(fitz.Point(cx, cy))]
                if (bi, li) in furniture[pi]:
                    hf.append(line)
                elif home:
                    home[0] |= r            # a label sticking out is kept whole
                elif any(c.x0 - 1 <= cx <= c.x1 + 1 and c.y0 - 1 <= cy <= c.y1 + 1
                         for c in cell_rects):
                    table_lines.append(line)
                else:
                    body.append(line)
            if body:
                groups.append((blk, body))
        # a full-page background scan under real text is just a duplicate of it
        images = [(x, r) for x, r in page_images(p["page"], skip_fullpage=True)
                  if not any(g.contains(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
                             for g in regions)]
        # xref None: a graphic region, pictured straight off the page
        images += [(None, g) for g in regions]
        per_page.append((tables, trects, groups, table_lines, hf, images))

    # one set of margins for the whole section, from where the content is
    rects = []
    for _t, trects, groups, _tl, _hf, images in per_page:
        rects += [ln["bbox"] for _b, body in groups for ln in body]
        rects += trects + [r for _x, r in images]
    if rects:
        clamp = lambda v, hi: float(max(18.0, min(v, hi)))
        margins = (clamp(min(r.x0 for r in rects), pw * 0.35),
                   clamp(min(r.y0 for r in rects), ph * 0.3),
                   clamp(pw - max(r.x1 for r in rects), pw * 0.35),
                   clamp(ph - max(r.y1 for r in rects), ph * 0.3))
    else:
        margins = (72.0, 72.0, 72.0, 72.0)
    left, right = margins[0], pw - margins[2]
    width = max(36.0, right - left)

    # everything in reading order, as one stream across the pages
    stream = []
    for pi, (tables, trects, groups, _tl, _hf, images) in enumerate(per_page):
        items = []
        for blk, body in groups:
            b = blk["bbox"]
            # a narrow block of several lines is a column of its own (or a
            # table cell without rules): its lines wrap at its own edge
            narrow = len(body) > 1 and b.width < width * 0.6
            for ln in body:
                ln["_left"] = b.x0 if narrow else left
                ln["_right"] = b.x1 if narrow else right
            items.append((min(ln["bbox"].y0 for ln in body), b.x0, "lines", body))
        for t, tr in zip(tables, trects):
            items.append((tr.y0, tr.x0, "table", t))
        for xref, rect in images:
            items.append((rect.y0, rect.x0, "image", (xref, rect)))
        items.sort(key=lambda it: (round(it[0], 1), it[1]))
        for _y, _x, kind, obj in items:
            if kind == "lines":
                stream.extend(("line", pi, ln) for ln in obj)
            else:
                stream.append((kind, pi, obj))

    grouped = _group(stream)
    pitch = _pitches([obj for kind, _pi, obj in grouped if kind == "para"])

    # where each page's content ends: a page that stopped with a fifth of it
    # still empty was broken on purpose (a new chapter), and Word should
    # start the next thing on a new page too rather than run it on
    bottoms = {}
    for kind, pi, obj in stream:
        y = (obj["bbox"].y1 if kind == "line" else obj.bbox[3] if kind == "table"
             else obj[1].y1)
        bottoms[pi] = max(bottoms.get(pi, 0.0), y)
    ends_early = {pi for pi, y in bottoms.items()
                  if y < ph - margins[3] - ph * 0.2}
    # lines drawn under headings, kept as paragraph borders
    rules = {pi: page_rules(p["page"], per_page[pi][1]) for pi, p in enumerate(pages)}

    out = []
    prev = None                 # (page, bottom) of the last thing written
    fills = {}                  # page -> coloured shapes, for cell shading
    open_table = None           # [parts, bottom, index in out] of the last table
    for kind, pi, obj in grouped:
        # first thing on a page, the page before having ended early
        brk = prev is not None and prev[0] == pi - 1 and (pi - 1) in ends_early
        if kind == "para":
            rows = obj["rows"]
            first = rows[0][0]
            pt = pitch(_line_size(first))
            before = 0.0
            if prev is not None and prev[0] == pi:
                # the gap above, minus the leading Word adds by itself
                lead = max(0.0, pt - first["bbox"].height) if pt else 0.0
                before = min(72.0, max(0.0, first["bbox"].y0 - prev[1] - lead))
            last_pi = obj["last_page"]
            border = _border_below(rows, rules[last_pi], left, right)
            # a ruled heading that opened a page opens one in Word as well
            brk = brk or (border is not None and prev is not None and prev[0] < pi)
            xml = _flow_para(rows, left, right, before, pt,
                             default_font, default_size,
                             page_break=brk, border=border)
            if xml:
                out.append(xml)
            prev = (last_pi, max(ln["bbox"].y1 for ln in rows[-1]))
        elif kind == "table":
            if pi not in fills:
                fills[pi] = page_fills(pages[pi]["page"])
            parts = table_parts(obj, per_page[pi][3], fills[pi], pitch,
                                default_font, default_size)
            if parts:
                if (open_table is not None and prev is not None
                        and prev == (pi - 1, open_table[1])
                        and table_continues(open_table[0], parts)):
                    # the same table, carried on over the page break
                    join_table(open_table[0], parts)
                    out[open_table[2]] = table_xml(open_table[0])
                else:
                    if brk:
                        out.append(para_xml("", page_break=True,
                                            default_font=default_font,
                                            default_size=default_size))
                    out.append(table_xml(parts))
                    # Word needs a paragraph after every table or it refuses
                    # to open the file when two tables end up adjacent; kept
                    # 1 pt tall so a table that fills a page leaves no blank one
                    out.append(para_xml("", spacing='<w:spacing w:before="0" '
                                        'w:after="0" w:line="20" w:lineRule="exact"/>',
                                        default_font=default_font, default_size=1))
                    open_table = [parts, None, len(out) - 2]
                open_table[1] = obj.bbox[3]
                prev = (pi, obj.bbox[3])
        else:
            xref, rect = obj
            if xref is None:
                data, ext = _region_picture(pages[pi]["page"], rect, dpi)
            else:
                data, ext = image_part(pages[pi]["page"].parent, xref)
            if not data:
                continue
            rid = writer.add_image(data, ext)
            w = min(rect.width, width)
            h = rect.height * (w / rect.width if rect.width else 1)
            jc = None
            if abs(((rect.x0 + rect.x1) / 2) - (left + width / 2)) < 10:
                jc = "center"
            gap = 0.0 if prev is None or prev[0] != pi else max(0.0, rect.y0 - prev[1])
            out.append(para_xml(
                inline_pic_xml(rid, writer.pic_id(), w, h),
                spacing='<w:spacing w:before="%d" w:after="0"/>' % _tw(min(gap, 60.0)),
                jc=jc, default_font=default_font, default_size=default_size,
                page_break=brk))
            prev = (pi, rect.y1)

    sect = {"pw": pw, "ph": ph, "margins": margins}
    # keep the document's own numbering: ก ข ค in the front matter, 1 2 3 from
    # chapter one, starting from whatever number the first page printed
    for pi, p in enumerate(pages):
        label = _page_number_of(p["blocks"], ph)
        if label:
            sect["pgnum"] = (label[0], max(1, label[1] - pi))
            break
    for kind, top in (("header", True), ("footer", False)):
        for _t, _tr, _g, _tl, hf, _im in per_page:
            mine = [ln for ln in hf if (ln["bbox"].y1 <= ph / 2) == top]
            paras = _hf_paras(mine, pw, default_font, default_size) if mine else ""
            if paras:
                sect[kind] = writer.add_part(kind, paras)
                if top:
                    sect["header_dist"] = min(ln["bbox"].y0 for ln in mine)
                else:
                    sect["footer_dist"] = ph - max(ln["bbox"].y1 for ln in mine)
                break
    return out, sect


# ====================================================================== export
_GARBLED_LIMIT = 0.15


def _common_font(doc, idxs):
    """The document's most-used (family, size), used for Word's own defaults so
    that text the user types afterwards matches what is already there."""
    tally = {}
    for pno in idxs[:20]:                      # a sample is plenty
        try:
            d = doc[pno].get_text("dict")
        except Exception:
            continue
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for ln in b.get("lines", []):
                for sp in ln.get("spans", []):
                    n = len(sp.get("text", "").strip())
                    if not n:
                        continue
                    fam = span_style(sp)[0]
                    key = (fam, round(float(sp.get("size", 16)) * 2) / 2)
                    tally[key] = tally.get(key, 0) + n
    if not tally:
        return "TH SarabunPSK", 16.0
    return max(tally.items(), key=lambda kv: kv[1])[0]


def _attach_sect(paras, sect):
    """Put a section break into the last paragraph of `paras`, so there is no
    stray empty line between sections."""
    paras = list(paras)
    last = paras[-1]
    if last.startswith("<w:p><w:pPr>"):
        paras[-1] = last.replace("</w:pPr>", sect + "</w:pPr>", 1)
    elif last.startswith("<w:p>"):
        paras[-1] = last.replace("<w:p>", "<w:p><w:pPr>" + sect + "</w:pPr>", 1)
    else:                                   # a table cannot carry a sectPr
        paras.append("<w:p><w:pPr>%s</w:pPr></w:p>" % sect)
    return paras


def export_docx(pdf, path, layout=True, pages=None, dpi=200, tables=True,
                progress=None):
    """Write the open document out as a .docx.

    `pdf` is a PdfDocument, `pages` an optional list of 0-based page numbers.
    `layout=True` keeps every line where it was (frames); `layout=False`
    produces flowing, freely editable paragraphs. `progress(done, total)` may
    return False to cancel, which raises ExportCancelled.

    Returns {"pages": n, "images": n, "picture_pages": [1-based page numbers
    exported as a picture because their text did not decode], "fonts":
    [families embedded in the file]}."""
    doc = pdf.doc
    if doc is None:
        raise ValueError("no document is open")
    idxs = list(range(doc.page_count)) if pages is None else list(pages)
    if not idxs:
        raise ValueError("no pages selected")

    for attr in ("_wny_page_cache", "_wny_cmaps"):     # left by a cancelled run
        try:
            delattr(doc, attr)
        except Exception:
            pass
    writer = DocxWriter()
    default_font, default_size = _common_font(doc, idxs)
    renames, reject = fit_fonts(doc, idxs)
    sections = []        # (block-level xml list, sect_xml keyword arguments)
    pending = []         # flowing pages waiting to become one section
    pending_label = [None]   # the page numbering the pending pages use
    picture_pages = []
    carrier = ('<w:spacing w:before="0" w:after="0" w:line="20" '
               'w:lineRule="exact"/>')

    def flush():
        if pending:
            sections.append(_flow_section(pending, writer, default_font,
                                          default_size, tables, dpi))
            del pending[:]

    for n, pno in enumerate(idxs):
        page = doc[pno]
        pw, ph = page.rect.width, page.rect.height
        blocks = page_blocks(page)
        text = "".join(sp.get("text", "")
                       for blk in blocks for ln in blk["lines"] for sp in ln["spans"])
        # Word cannot make a page over 22 inches; a bigger one (a poster-size
        # cover) is shrunk to fit rather than cut off
        s = _fit_scale(pw, ph)

        # A page whose text decodes to private-use gibberish has a broken
        # ToUnicode map; nothing we write would be the document's real words,
        # so ship a picture of the page and tell the caller about it.
        as_picture = not blocks or undecodable_ratio(text) > _GARBLED_LIMIT

        if as_picture:
            flush()
            if blocks:
                picture_pages.append(pno + 1)
            data, ext = page_picture(page, dpi)
            rid = writer.add_image(data, ext)
            sections.append(([para_xml(
                anchored_pic_xml(rid, writer.pic_id(), 0, 0, pw * s, ph * s),
                spacing=carrier, default_font=default_font, default_size=2)],
                {"pw": pw * s, "ph": ph * s, "margins": (0, 0, 0, 0)}))
        elif layout:
            images = page_images(page, skip_fullpage=False)
            frames, anchors = layout_page(page, _scaled_blocks(blocks, s), images,
                                          writer, pw * s, ph * s, s)
            # the one paragraph that stays in the normal flow: it carries the
            # page's pictures and the page's section break
            sections.append((frames + [para_xml(
                anchors, spacing=carrier, default_font=default_font,
                default_size=1)],
                {"pw": pw * s, "ph": ph * s, "margins": (0, 0, 0, 0)}))
        elif is_designed(page, blocks):
            # A cover or a poster page: colour bands, photos, turned or huge
            # lettering. Poured into paragraphs it falls apart, so it is kept
            # as one pinned page - the artwork as a picture, every line of
            # text still a real, editable frame on top of it.
            flush()
            sections.append(_designed_section(page, blocks, writer, dpi, s,
                                              default_font, carrier))
        else:
            label = _page_number_of(blocks, ph)
            if pending and (abs(pending[0]["pw"] - pw) > 1
                            or abs(pending[0]["ph"] - ph) > 1
                            or label and pending_label[0]
                            and label[0] != pending_label[0][0]):
                # a new page size needs a new section, and so does a change of
                # page numbering (ก ข ค front matter -> 1 2 3)
                flush()
            if not pending:
                pending_label[0] = None
            pending_label[0] = label or pending_label[0]
            pending.append({"page": page, "blocks": blocks, "pw": pw, "ph": ph})

        if progress is not None and progress(n + 1, len(idxs)) is False:
            raise ExportCancelled()
    flush()

    # a section without a header of its own would inherit the previous one's
    for kind in ("header", "footer"):
        if any(kind in s for _p, s in sections):
            blank = None
            for _p, s in sections:
                if kind not in s:
                    blank = blank or writer.add_part(kind, para_xml(""))
                    s[kind] = blank

    body = []
    for i, (paras, sk) in enumerate(sections):
        sect = sect_xml(**sk)
        if not paras:
            paras = [para_xml("", default_font=default_font,
                              default_size=default_size)]
        if i < len(sections) - 1:
            body.extend(_attach_sect(paras, sect))
        else:
            body.extend(paras)
            body.append(sect)
    body = rename_fonts("".join(body), renames)
    writer.parts = [(n, rename_fonts(xml, renames), c) for n, xml, c in writer.parts]
    default_font = renames.get(default_font, default_font)

    used = used_fonts(body, *[xml for _n, xml, _c in writer.parts])
    used.setdefault(default_font, set()).add("Regular")
    for fam in reject:
        used.pop(fam, None)
    fonts = writer.embed_fonts(used)

    for attr in ("_wny_page_cache", "_wny_cmaps"):
        try:
            delattr(doc, attr)
        except Exception:
            pass

    title = os.path.splitext(os.path.basename(pdf.path or "document"))[0]
    writer.write(path, body, default_font, default_size, title)
    return {"pages": len(idxs), "images": len(writer.media),
            "picture_pages": picture_pages, "fonts": fonts}
