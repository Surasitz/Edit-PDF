# -*- coding: utf-8 -*-
"""Bridge to the bundled PdfCraft engine (``pdfcraft-cli``).

PdfCraft is an open-source, Rust-native PDF engine (MIT OR Apache-2.0, source
in ``../pdfcraft``). WnyEditPDF keeps PyMuPDF for everything that happens on
the page - Thai text editing, rendering, Word export, compression - and hands
the engine the whole-document jobs PyMuPDF has no answer for: digital
signatures with a certificate, PDF/A, comparing two versions, the
accessibility checker, removing hidden information, flattening, automatic form
field detection, splitting and combining.

The engine runs as a child process driven by a JSON script (``pdfcraft-cli run
--script``), one process per job, so a crash or hang in the engine can never
take the editor - or the user's unsaved work - down with it. Every function
here takes and returns plain bytes / dicts; nothing in this module touches Qt,
so the window decides how to show progress and errors.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

EXE = "pdfcraft-cli.exe" if os.name == "nt" else "pdfcraft-cli"

# The engine is a console program: started from the windowed .exe it would
# flash a black console window for every job unless told not to.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DEFAULT_TIMEOUT = 600          # seconds; comparing or checking a 500-page file takes a while


class EngineError(Exception):
    """The engine ran but refused or failed the job; the message is its own."""


class EngineMissing(EngineError):
    """pdfcraft-cli could not be found (a source checkout that was never built)."""


def _candidates():
    env = os.environ.get("WNYEDITPDF_ENGINE")
    if env:
        yield env
    pkg = os.path.dirname(os.path.abspath(__file__))
    app = os.path.dirname(pkg)
    if getattr(sys, "frozen", False):
        # PyInstaller one-file build: the binary is unpacked next to the fonts
        yield os.path.join(getattr(sys, "_MEIPASS", app), "engine", EXE)
        yield os.path.join(os.path.dirname(sys.executable), "engine", EXE)
    yield os.path.join(app, "engine", EXE)            # copied there by build.bat
    root = os.path.dirname(app)
    for profile in ("release", "debug"):               # a source checkout
        yield os.path.join(root, "pdfcraft", "target", profile, EXE)


def cli_path():
    """Full path of pdfcraft-cli, or None when it is not installed."""
    for p in _candidates():
        if p and os.path.isfile(p):
            return p
    return None


def available():
    return cli_path() is not None


def _decode_stream(text):
    """The CLI prints one JSON value per step (pretty-printed, so values span
    lines); read them back in order."""
    dec = json.JSONDecoder()
    out, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        value, i = dec.raw_decode(text, i)
        out.append(value)
    return out


def _call(args, timeout):
    exe = cli_path()
    if not exe:
        raise EngineMissing("pdfcraft-cli not found")
    try:
        proc = subprocess.run(
            [exe, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise EngineError("timed out after %d s" % timeout)
    except OSError as e:
        raise EngineError(str(e))
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        # "pdfcraft-cli: step 2 (doc_flatten): <reason>" -> "<reason>"
        if err.startswith("pdfcraft-cli:"):
            err = err[len("pdfcraft-cli:"):].strip()
        if err.startswith("step ") and "): " in err:
            err = err.split("): ", 1)[1]
        raise EngineError(err or "exit code %d" % proc.returncode)
    return out


def run(steps, timeout=DEFAULT_TIMEOUT):
    """Run tool steps ``[(tool, args), ...]`` in one engine session and return
    each step's JSON result, in order. Documents opened by ``doc_open`` are
    numbered 1, 2, ... in the order they are opened."""
    work = tempfile.mkdtemp(prefix="wny_engine_")
    try:
        script = os.path.join(work, "steps.json")
        with open(script, "w", encoding="utf-8") as f:
            json.dump([{"tool": t, "args": a} for t, a in steps], f,
                      ensure_ascii=False)
        return _decode_stream(_call(["run", "--script", script], timeout))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def version():
    """'pdfcraft-cli 0.4.0' or None."""
    try:
        first = _call(["--version"], 20).strip().splitlines()
        return first[0] if first else None
    except EngineError:
        return None


class _Workdir:
    """A private temp folder holding the copy of the document the engine works
    on. The file is named after the user's document because the engine names
    split parts and exported images after it."""

    def __init__(self, data=None, name="document.pdf"):
        self.dir = tempfile.mkdtemp(prefix="wny_engine_")
        base = os.path.basename(name or "document.pdf")
        if not base.lower().endswith(".pdf"):
            base += ".pdf"
        self.src = os.path.join(self.dir, base)
        self.out = os.path.join(self.dir, "__result__.pdf")
        if data is not None:
            with open(self.src, "wb") as f:
                f.write(data)

    def result(self):
        with open(self.out, "rb") as f:
            return f.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)


def _open(path, password=None):
    args = {"path": path}
    if password:
        args["password"] = password
    return ("doc_open", args)


def _edit(data, steps, name=None):
    """Open ``data``, run ``steps`` on document 1, save a full rewrite and
    return (new_bytes, results of ``steps``)."""
    with _Workdir(data, name) as w:
        res = run([_open(w.src), *steps,
                   ("doc_save", {"doc": 1, "path": w.out, "full": True})])
        return w.result(), res[1:1 + len(steps)]


def _read(data, steps, name=None, extra_open=()):
    """Open ``data`` (plus ``extra_open`` paths as documents 2, 3, ...) and run
    read-only ``steps``; returns their results."""
    with _Workdir(data, name) as w:
        opens = [_open(w.src)] + [_open(p, pw) for p, pw in extra_open]
        res = run([*opens, *steps])
        return res[len(opens):]


# ======================================================================
#  Document information
# ======================================================================
def info(data, name=None):
    """Metadata, fonts, security, page sizes, attachments... (doc_info)."""
    return _read(data, [("doc_info", {"doc": 1})], name)[0]


def hidden_info(data):
    """What 'remove hidden information' would remove, per category."""
    return _read(data, [("doc_hidden_info", {"doc": 1})])[0]


HIDDEN_CATEGORIES = ("metadata", "attachments", "comments", "form-fields",
                     "hidden-text", "hidden-layers", "bookmarks",
                     "links-actions-scripts", "private-data")


def remove_hidden(data, categories=None):
    """Remove the given categories (all of them when None) -> new bytes."""
    args = {"doc": 1}
    if categories:
        args["categories"] = list(categories)
    return _edit(data, [("doc_remove_hidden", args)])[0]


def flatten(data, comments=True, fields=True):
    """Burn comment and/or form-field appearances into the page content."""
    return _edit(data, [("doc_flatten", {"doc": 1, "comments": comments,
                                         "fields": fields})])[0]


# ======================================================================
#  Standards
# ======================================================================
def pdfa_verify(data, level="2b"):
    return _read(data, [("pdfa_verify", {"doc": 1, "level": level})])[0]


def pdfa_convert(data, level="2b"):
    """-> (new_bytes, report of what was fixed and what remains)."""
    out, res = _edit(data, [("pdfa_convert", {"doc": 1, "level": level})])
    return out, res[0]


def accessibility_report(data, html_path, name=None):
    """Run the full accessibility check and write its HTML report."""
    return _read(data, [("accessibility_report",
                         {"doc": 1, "path": os.path.abspath(html_path)})],
                 name)[0]


# ======================================================================
#  Compare two versions
# ======================================================================
def compare(new_data, old_path, old_password=None, limit=500):
    """Text differences from the older file to the current document."""
    return _read(new_data, [("doc_compare", {"doc": 1, "other": 2,
                                             "limit": limit})],
                 extra_open=[(old_path, old_password)])[0]


def compare_report(new_data, old_path, report_path, old_password=None):
    """Write the summary report (a PDF listing every change)."""
    return _read(new_data, [("doc_compare_report",
                             {"doc": 1, "other": 2,
                              "path": os.path.abspath(report_path)})],
                 extra_open=[(old_path, old_password)])[0]


def compare_mark(new_data, old_path, old_password=None):
    """The current document with every difference added as a comment."""
    with _Workdir(new_data) as w:
        run([_open(w.src), _open(old_path, old_password),
             ("doc_compare_mark", {"doc": 1, "other": 2}),
             ("doc_save", {"doc": 1, "path": w.out, "full": True})])
        return w.result()


# ======================================================================
#  Forms
# ======================================================================
def detect_fields(data):
    """Find the blanks of a printed form and turn them into fillable fields.
    -> (new_bytes, {"fields": [...]} )"""
    out, res = _edit(data, [("form_detect_fields", {"doc": 1, "add": True})])
    return out, res[0]


def form_reset(data):
    """Every field back to its default value."""
    return _edit(data, [("form_reset", {"doc": 1})])[0]


def export_data(data, path, what="all", name=None):
    """Write comments and/or form data; the extension picks the format
    (.xfdf / .fdf, or .xml / .csv / .txt for form data)."""
    return _read(data, [("doc_export_data", {"doc": 1, "path": os.path.abspath(path),
                                             "what": what})], name)[0]


def import_data(data, path):
    """Fill fields / add comments from an XFDF, FDF, XML, CSV or text file.
    -> (new_bytes, report)"""
    out, res = _edit(data, [("doc_import_data", {"doc": 1, "path": os.path.abspath(path)})])
    return out, res[0]


def links_from_urls(data):
    """Make every web address written in the text a clickable link.
    -> (new_bytes, report); (data, {"urls": []}) when there is nothing to link."""
    try:
        out, res = _edit(data, [("links_from_urls", {"doc": 1})])
    except EngineError as e:
        if "no unlinked" in str(e):          # a normal outcome, not a failure
            return data, {"urls": []}
        raise
    rep = res[0]
    rep["urls"] = rep.get("created") or []
    return out, rep


# ======================================================================
#  Pages
# ======================================================================
def replace_pages(data, pages, path, from_pages=None):
    """Swap the content of ``pages`` (1-based) for pages of another PDF; the
    links, comments, fields and bookmarks on the original pages stay, as in
    Acrobat."""
    args = {"doc": 1, "pages": list(pages), "path": os.path.abspath(path)}
    if from_pages:
        args["from_pages"] = list(from_pages)
    return _edit(data, [("page_replace", args)])[0]


def crop(data, margins, pages=None):
    """Crop pages by ``margins`` = [left, bottom, right, top] in points from
    the media box (all pages when ``pages`` is None)."""
    args = {"doc": 1, "box": "crop", "margins": [max(0.0, float(m)) for m in margins]}
    if pages:
        args["pages"] = list(pages)
    return _edit(data, [("page_set_box", args)])[0]


# ======================================================================
#  Split / combine / export
# ======================================================================
def split(data, out_dir, name, every=None, before=None, bookmarks=False,
          max_mb=None):
    """Write <name>-partK.pdf files into out_dir."""
    args = {"doc": 1, "out_dir": os.path.abspath(out_dir)}
    if every:
        args["every"] = int(every)
    if before:
        args["before"] = list(before)
    if bookmarks:
        args["bookmarks"] = True
    if max_mb:
        args["max_mb"] = float(max_mb)
    return _read(data, [("doc_split", args)], name)[0]


def create_multiple(paths, out_path):
    """Join PDFs, images (PNG/JPEG/TIFF/GIF/BMP) and .txt files, in order, into
    one PDF with a bookmark per file."""
    return run([("doc_create_multiple",
                 {"paths": [os.path.abspath(p) for p in paths],
                  "mode": "combine", "out": os.path.abspath(out_path)})])[0]


def export_all_images(data, folder, name=None):
    return _read(data, [("doc_export_all_images",
                         {"doc": 1, "folder": os.path.abspath(folder)})],
                 name)[0]


# ======================================================================
#  Digital signatures
# ======================================================================
def signatures(data, trust=()):
    """Every signature field with its validation status. ``trust`` lists
    certificate files (.cer/.crt/.pem/.p7b) whose signers count as trusted,
    e.g. the organisation's own root certificate; the engine keeps them only
    for this one run."""
    steps = []
    if trust:
        steps.append(("sign_trust", {"paths": [os.path.abspath(p) for p in trust],
                                     "clear": True}))
    steps.append(("sign_list", {"doc": 1}))
    return _read(data, steps)[-1]


def id_info(path, password=""):
    """Open a .p12/.pfx digital ID - which checks its password - and return
    its certificate (name, issuer, validity...)."""
    res = run([("sign_trust", {"paths": [os.path.abspath(path)],
                               "password": password, "clear": True})])[0]
    certs = (res.get("trusted") or []) if isinstance(res, dict) else []
    return certs[0] if certs else {}


def windows_ids():
    """Signing certificates in the Windows 'Personal' store ([] elsewhere)."""
    if os.name != "nt":
        return []
    res = run([("sign_windows_ids", {})])[0]
    if isinstance(res, dict):
        for key in ("ids", "identities", "certificates"):
            if isinstance(res.get(key), list):
                return res[key]
        return []
    return res if isinstance(res, list) else []


def create_id(path, name, password, organization="", unit="", email="",
              country="", years=5):
    """Create a self-signed digital ID saved as a password-protected .p12."""
    args = {"path": os.path.abspath(path), "name": name, "password": password,
            "years": int(years)}
    for k, v in (("organization", organization), ("unit", unit),
                 ("email", email), ("country", country)):
        if v:
            args[k] = v
    return run([("sign_id_create", args)])[0]


def sign(data, out_path, digital_id, password="", page=None, rect=None,
         reason="", location="", contact="", certify=None, name=None):
    """Sign the document and write the signed file to out_path.

    digital_id : a .p12/.pfx path, or "windows:<name or fingerprint>"
    rect       : [x0, y0, x1, y1] in points from the page's top-left, or None
                 for an invisible signature
    Signing always produces a file - a signature covers exact bytes, so there
    is nothing left to 'edit and save later'."""
    ref = digital_id
    if not ref.startswith(("windows:", "keychain:")):
        ref = os.path.abspath(ref)
    args = {"doc": 1, "id": ref, "out": os.path.abspath(out_path)}
    if password:
        args["password"] = password
    if page:
        args["page"] = int(page)
    if rect:
        args["rect"] = [float(v) for v in rect]
    for k, v in (("reason", reason), ("location", location),
                 ("contact", contact)):
        if v:
            args[k] = v
    if certify:
        args["certify"] = certify
    return _read(data, [("sign_document", args)], name)[0]
