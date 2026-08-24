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
* ``layout=False`` - blocks become ordinary flowing paragraphs (with real Word
  tables where ruled tables are detected), which is the one you can keep
  writing in.
"""

import os
import re
import time
import unicodedata
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
    "thsarabunit9": "TH Sarabun IT๙",
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


def font_family(raw_name):
    """Word family name for a PDF span's font."""
    if not raw_name:
        return "TH SarabunPSK"
    raw = _RE_SUBSET.sub("", raw_name)
    key = re.sub(r"[^a-z0-9]", "", raw.lower())
    if key in _FONT_ALIASES:
        return _FONT_ALIASES[key]
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
    return _prettify(raw)


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
    return font_family(raw), bold, italic, bool(flags & 1)


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
    # w:bidi is the language Word uses to shape and line-break Thai; without it
    # Word may hyphenate/spell-check Thai as if it were English.
    rpr.append('<w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="th-TH"/>')
    return ('<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
            % ("".join(rpr), _esc(text)))


def _ppr(frame=None, spacing=None, ind=None, jc=None, sect=None,
         default_font=None, default_size=None):
    """<w:pPr>, elements in schema order: framePr, spacing, ind, jc, rPr, sectPr."""
    parts = []
    if frame:
        parts.append(frame)
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


def sect_xml(pw, ph, margins):
    left, top, right, bottom = margins
    w = min(_tw(pw), _MAX_TWIP)
    h = min(_tw(ph), _MAX_TWIP)
    orient = ' w:orient="landscape"' if pw > ph else ""
    return ('<w:sectPr><w:type w:val="nextPage"/>'
            '<w:pgSz w:w="%d" w:h="%d"%s/>'
            '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
            'w:header="0" w:footer="0" w:gutter="0"/>'
            '<w:cols w:space="0"/></w:sectPr>'
            % (w, h, orient, _tw(top), _tw(right), _tw(bottom), _tw(left)))


# ================================================================ the zip file
_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')

_XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'


class DocxWriter:
    """Collects the parts of a .docx and writes the zip."""

    def __init__(self):
        self.media = []      # (filename, bytes)
        self.rels = []       # (rId, type, target)
        self._next_rel = 3   # rId1 = styles, rId2 = settings
        self._next_pic = 1

    def add_image(self, data, ext):
        """Store an image part; returns its relationship id."""
        ext = "jpeg" if ext in ("jpg", "jpeg") else "png"
        name = "image%d.%s" % (len(self.media) + 1, ext)
        self.media.append((name, data))
        rid = "rId%d" % self._next_rel
        self._next_rel += 1
        self.rels.append((rid, "image", "media/" + name))
        return rid

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

    @staticmethod
    def _settings():
        return (_XML_HEAD +
                '<w:settings %s><w:defaultTabStop w:val="720"/><w:compat>'
                '<w:compatSetting w:name="compatibilityMode" '
                'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>'
                '</w:compat></w:settings>' % _NS)

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
            for name, data in self.media:
                # PNG/JPEG are already compressed - deflating again only burns CPU
                z.writestr(zipfile.ZipInfo("word/media/" + name), data,
                           zipfile.ZIP_STORED)


# ============================================================== page inspection
def page_blocks(page):
    """Text blocks of a page as {bbox, lines[{bbox, spans}]}, whitespace-only
    lines dropped. Coordinates are already in the rotated (on-screen) space -
    PyMuPDF applies the page rotation to text extraction but not to image
    placements, which is why only the images below need a matrix."""
    out = []
    try:
        d = page.get_text("dict")
    except Exception:
        return out
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        lines = []
        for ln in b.get("lines", []):
            spans = [sp for sp in ln.get("spans", []) if sp.get("text")]
            if not spans or not any(sp["text"].strip() for sp in spans):
                continue
            lines.append({"bbox": fitz.Rect(ln["bbox"]), "spans": spans})
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
def _line_runs(line):
    """Every span of a line as Word runs, adjacent spans that share formatting
    merged so a single word does not become five runs."""
    parts = []
    prev = None
    for sp in line["spans"]:
        text = repair_text(sp.get("text", ""))
        if not text:
            continue
        fam, bold, ital, sup = span_style(sp)
        key = (fam, round(float(sp.get("size", 12)), 1), _color(sp), bold, ital, sup)
        if prev is not None and prev[0] == key:
            prev[1].append(text)
        else:
            prev = (key, [text])
            parts.append(prev)
    return "".join(
        run_xml("".join(chunks), key[0], key[1], key[2], key[3], key[4], key[5])
        for key, chunks in parts)


def layout_page(page, blocks, images, writer, pw, ph):
    """Every line of the page as an absolutely positioned frame, with the
    pictures anchored behind them."""
    body = []
    for xref, rect in images:
        data, ext = image_part(page.parent, xref)
        if not data:
            continue
        rid = writer.add_image(data, ext)
        body.append(anchored_pic_xml(rid, writer.pic_id(), rect.x0, rect.y0,
                                     rect.width, rect.height))
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


# =================================================================== flow mode
def _page_margins(page, blocks, images):
    """Guess the page margins from where the content actually is, so a flowing
    document keeps roughly the original text column instead of defaulting to
    Word's 1 inch everywhere."""
    pw, ph = page.rect.width, page.rect.height
    rects = [b["bbox"] for b in blocks] + [r for _, r in images]
    if not rects:
        return (72.0, 72.0, 72.0, 72.0)
    left = min(r.x0 for r in rects)
    right = pw - max(r.x1 for r in rects)
    top = min(r.y0 for r in rects)
    bottom = ph - max(r.y1 for r in rects)
    clamp = lambda v, hi: float(max(18.0, min(v, hi)))
    return (clamp(left, pw * 0.35), clamp(top, ph * 0.3),
            clamp(right, pw * 0.35), clamp(bottom, ph * 0.3))


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


def _block_paragraph(blk, margins, pw, prev_y, default_font, default_size):
    """One text block as one flowing paragraph."""
    left, _top, right, _bottom = margins
    content_w = max(1.0, pw - left - right)
    runs = []
    text_so_far = ""
    for line in blk["lines"]:
        line_text = "".join(repair_text(sp.get("text", "")) for sp in line["spans"])
        if not line_text:
            continue
        glue = _joiner(text_so_far, line_text) if text_so_far else ""
        if glue:
            sp0 = line["spans"][0]
            fam, bold, ital, sup = span_style(sp0)
            runs.append(run_xml(glue, fam, float(sp0.get("size", 12)),
                                _color(sp0), bold, ital, sup))
        runs.append(_line_runs(line))
        text_so_far += glue + line_text
    if not text_so_far.strip():
        return None, prev_y

    r = blk["bbox"]
    # alignment: centred and right-aligned headings are common and look wrong
    # if everything is flushed left
    jc = None
    centre_off = abs(((r.x0 + r.x1) / 2) - (left + content_w / 2))
    if centre_off < 8 and r.width < content_w * 0.92 and r.x0 > left + 12:
        jc = "center"
    elif r.x1 > pw - right - 6 and r.x0 > left + content_w * 0.45:
        jc = "right"

    ind = ""
    if jc is None:
        indent = max(0.0, r.x0 - left)
        first = blk["lines"][0]["bbox"].x0 - r.x0
        bits = []
        if indent > 4:
            bits.append('w:left="%d"' % _tw(indent))
        if first > 4:
            bits.append('w:firstLine="%d"' % _tw(first))
        if bits:
            ind = "<w:ind %s/>" % " ".join(bits)

    gap = 0.0 if prev_y is None else max(0.0, r.y0 - prev_y)
    pitch = 0.0
    if len(blk["lines"]) > 1:
        tops = [ln["bbox"].y0 for ln in blk["lines"]]
        pitch = (tops[-1] - tops[0]) / (len(tops) - 1)
    spacing = ('<w:spacing w:before="%d" w:after="0" w:line="%d" w:lineRule="%s"/>'
               % (_tw(min(gap, 60.0)),
                  _tw(pitch) if pitch > 1 else 240,
                  "atLeast" if pitch > 1 else "auto"))
    para = para_xml("".join(runs), spacing=spacing, ind=ind or None, jc=jc,
                    default_font=default_font, default_size=default_size)
    return para, r.y1


# ------------------------------------------------------------------- tables
def _spans_in(blocks, rect):
    """The lines whose centre falls inside `rect`, grouped as the cell's text."""
    lines = []
    for blk in blocks:
        for line in blk["lines"]:
            r = line["bbox"]
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            if rect.x0 - 1 <= cx <= rect.x1 + 1 and rect.y0 - 1 <= cy <= rect.y1 + 1:
                lines.append(line)
    lines.sort(key=lambda ln: (round(ln["bbox"].y0, 1), ln["bbox"].x0))
    return lines


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


def _col_index(xs, value):
    """Index of the grid line nearest `value`."""
    best, bd = 0, None
    for i, x in enumerate(xs):
        d = abs(x - value)
        if bd is None or d < bd:
            best, bd = i, d
    return best


def _table_xml(table, blocks, default_font, default_size):
    """A detected ruled table as a real Word table.

    Cell text is pulled from our own spans rather than table.extract(), which
    returns bare strings - going through the spans is what keeps each cell's
    font, size and weight."""
    cells = [c for c in (table.cells or []) if c]
    xs = _grid_columns(cells)
    if len(xs) < 2:
        return None
    widths = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    ncol = len(widths)
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

    rows_xml = []
    for row in table.rows:
        row_cells = [c for c in (row.cells or []) if c]
        row_cells.sort(key=lambda c: c[0])
        used = 0
        tcs = []
        for c in row_cells:
            start = _col_index(xs, c[0])
            end = _col_index(xs, c[2])
            if end <= start:
                end = start + 1
            if start < used:                 # overlaps a cell we already wrote
                start = used
            if start >= ncol or end <= start:
                continue
            if start > used:                 # hole in the row -> blank filler
                tcs.append(_tc_xml(sum(widths[used:start]), start - used, "",
                                   default_font, default_size))
                used = start
            end = min(end, ncol)
            lines = _spans_in(blocks, fitz.Rect(c))
            body = _cell_body(lines, default_font, default_size)
            tcs.append(_tc_xml(sum(widths[start:end]), end - start, body,
                               default_font, default_size))
            used = end
        if used < ncol:
            tcs.append(_tc_xml(sum(widths[used:ncol]), ncol - used, "",
                               default_font, default_size))
        if not tcs:
            continue
        h = max(6.0, float(row.bbox[3] - row.bbox[1]))
        rows_xml.append('<w:tr><w:trPr><w:trHeight w:val="%d" w:hRule="atLeast"/>'
                        '</w:trPr>%s</w:tr>' % (_tw(h), "".join(tcs)))
    if not rows_xml:
        return None
    return "<w:tbl>%s<w:tblGrid>%s</w:tblGrid>%s</w:tbl>" % (
        tbl_pr, grid, "".join(rows_xml))


def _cell_body(lines, default_font, default_size):
    paras = []
    for line in lines:
        runs = _line_runs(line)
        if runs:
            paras.append(para_xml(
                runs,
                spacing='<w:spacing w:before="0" w:after="0" w:line="240" '
                        'w:lineRule="auto"/>',
                default_font=default_font, default_size=default_size))
    return "".join(paras)


def _tc_xml(width_pt, span, body, default_font, default_size):
    span_xml = '<w:gridSpan w:val="%d"/>' % span if span > 1 else ""
    if not body:
        body = para_xml("", default_font=default_font, default_size=default_size)
    return ('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s'
            '<w:vAlign w:val="center"/></w:tcPr>%s</w:tc>'
            % (_tw(width_pt), span_xml, body))


def _find_tables(page):
    try:
        return [t for t in page.find_tables().tables
                if t.row_count > 0 and t.col_count > 1]
    except Exception:
        return []


def flow_page(page, blocks, images, writer, pw, default_font, default_size,
              want_tables=True):
    """The page as ordinary flowing paragraphs, tables and pictures."""
    margins = _page_margins(page, blocks, images)
    left, _top, right, _bottom = margins
    content_w = max(36.0, pw - left - right)

    tables = _find_tables(page) if want_tables else []
    table_rects = [fitz.Rect(t.bbox) for t in tables]

    def in_table(rect):
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        return any(tr.x0 - 2 <= cx <= tr.x1 + 2 and tr.y0 - 2 <= cy <= tr.y1 + 2
                   for tr in table_rects)

    # everything the page holds, put back into reading order
    items = []
    for blk in blocks:
        if not in_table(blk["bbox"]):
            items.append((blk["bbox"].y0, blk["bbox"].x0, "block", blk))
    for t, tr in zip(tables, table_rects):
        items.append((tr.y0, tr.x0, "table", t))
    for xref, rect in images:
        items.append((rect.y0, rect.x0, "image", (xref, rect)))
    items.sort(key=lambda it: (round(it[0], 1), it[1]))

    out = []
    prev_y = None
    for _y, _x, kind, payload in items:
        if kind == "block":
            para, prev_y = _block_paragraph(payload, margins, pw, prev_y,
                                            default_font, default_size)
            if para:
                out.append(para)
        elif kind == "table":
            xml = _table_xml(payload, blocks, default_font, default_size)
            if xml:
                out.append(xml)
                # Word needs a paragraph after every table or it refuses to
                # open the file when two tables end up adjacent
                out.append(para_xml("", default_font=default_font,
                                    default_size=default_size))
                prev_y = payload.bbox[3]
        else:
            xref, rect = payload
            data, ext = image_part(page.parent, xref)
            if not data:
                continue
            rid = writer.add_image(data, ext)
            w = min(rect.width, content_w)
            h = rect.height * (w / rect.width if rect.width else 1)
            jc = None
            if abs(((rect.x0 + rect.x1) / 2) - (left + content_w / 2)) < 10:
                jc = "center"
            gap = 0.0 if prev_y is None else max(0.0, rect.y0 - prev_y)
            out.append(para_xml(
                inline_pic_xml(rid, writer.pic_id(), w, h),
                spacing='<w:spacing w:before="%d" w:after="0"/>' % _tw(min(gap, 60.0)),
                jc=jc, default_font=default_font, default_size=default_size))
            prev_y = rect.y1
    return out, margins


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


def export_docx(pdf, path, layout=True, pages=None, dpi=200, tables=True,
                progress=None):
    """Write the open document out as a .docx.

    `pdf` is a PdfDocument, `pages` an optional list of 0-based page numbers.
    `layout=True` keeps every line where it was (frames); `layout=False`
    produces flowing, freely editable paragraphs. `progress(done, total)` may
    return False to cancel, which raises ExportCancelled.

    Returns {"pages": n, "images": n, "picture_pages": [1-based page numbers
    exported as a picture because their text did not decode]}."""
    doc = pdf.doc
    if doc is None:
        raise ValueError("no document is open")
    idxs = list(range(doc.page_count)) if pages is None else list(pages)
    if not idxs:
        raise ValueError("no pages selected")

    writer = DocxWriter()
    default_font, default_size = _common_font(doc, idxs)
    body = []
    picture_pages = []

    for n, pno in enumerate(idxs):
        page = doc[pno]
        pw, ph = page.rect.width, page.rect.height
        blocks = page_blocks(page)
        text = "".join(sp.get("text", "")
                       for blk in blocks for ln in blk["lines"] for sp in ln["spans"])

        # A page whose text decodes to private-use gibberish has a broken
        # ToUnicode map; nothing we write would be the document's real words,
        # so ship a picture of the page and tell the caller about it.
        as_picture = not blocks or undecodable_ratio(text) > _GARBLED_LIMIT

        if as_picture:
            if blocks:
                picture_pages.append(pno + 1)
            data, ext = page_picture(page, dpi)
            rid = writer.add_image(data, ext)
            sect = sect_xml(pw, ph, (0, 0, 0, 0))
            body.append(para_xml(
                anchored_pic_xml(rid, writer.pic_id(), 0, 0, pw, ph),
                spacing='<w:spacing w:before="0" w:after="0" w:line="20" '
                        'w:lineRule="exact"/>',
                sect=sect if n < len(idxs) - 1 else None,
                default_font=default_font, default_size=2))
            if n == len(idxs) - 1:
                body.append(sect)
        elif layout:
            images = page_images(page, skip_fullpage=False)
            frames, anchors = layout_page(page, blocks, images, writer, pw, ph)
            body.extend(frames)
            sect = sect_xml(pw, ph, (0, 0, 0, 0))
            # the one paragraph that stays in the normal flow: it carries the
            # page's pictures and, for every page but the last, its section
            body.append(para_xml(
                anchors,
                spacing='<w:spacing w:before="0" w:after="0" w:line="20" '
                        'w:lineRule="exact"/>',
                sect=sect if n < len(idxs) - 1 else None,
                default_font=default_font, default_size=1))
            if n == len(idxs) - 1:
                body.append(sect)
        else:
            # in a flowing document a full-page background scan sitting under
            # real text is just a duplicate of that text
            images = page_images(page, skip_fullpage=True)
            paras, margins = flow_page(page, blocks, images, writer, pw,
                                       default_font, default_size, tables)
            sect = sect_xml(pw, ph, margins)
            if not paras:
                paras = [para_xml("", default_font=default_font,
                                  default_size=default_size)]
            if n < len(idxs) - 1:
                # the section break belongs to the page's last paragraph, so
                # there is no stray empty line between pages
                last = paras[-1]
                if last.startswith("<w:p><w:pPr>"):
                    paras[-1] = last.replace("</w:pPr>", sect + "</w:pPr>", 1)
                elif last.startswith("<w:p>"):
                    paras[-1] = last.replace("<w:p>", "<w:p><w:pPr>" + sect
                                             + "</w:pPr>", 1)
                else:                       # a table cannot carry a sectPr
                    paras.append(para_xml("", sect=sect,
                                          default_font=default_font,
                                          default_size=default_size))
            body.extend(paras)
            if n == len(idxs) - 1:
                body.append(sect)

        if progress is not None and progress(n + 1, len(idxs)) is False:
            raise ExportCancelled()

    title = os.path.splitext(os.path.basename(pdf.path or "document"))[0]
    writer.write(path, "".join(body), default_font, default_size, title)
    return {"pages": len(idxs), "images": len(writer.media),
            "picture_pages": picture_pages}
