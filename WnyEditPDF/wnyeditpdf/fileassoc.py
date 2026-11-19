# -*- coding: utf-8 -*-
"""Windows file association for WnyEditPDF ("Open with" / default PDF app).

Everything is written under HKEY_CURRENT_USER, so registering needs no
administrator rights and only affects the user who asked for it:

    HKCU\\Software\\Classes\\WnyEditPDF.pdf           the file type (ProgID)
    HKCU\\Software\\Classes\\Applications\\<exe>      puts us in "Open with"
    HKCU\\Software\\Classes\\.pdf\\OpenWithProgids    lists us for .pdf
    HKCU\\Software\\WnyEdit\\WnyEditPDF\\Capabilities for Settings > Default apps
    HKCU\\Software\\RegisteredApplications           points at the above

Windows 10/11 does not let a program make itself the default handler (the
UserChoice key is hash-protected), so make_default() shows the system's own
"Open with" dialog and the user confirms there.
"""

import os
import sys

from .config import APP_NAME, VERSION

IS_WINDOWS = sys.platform.startswith("win")

PROGID = "WnyEditPDF.pdf"
TYPE_NAME_TH = "เอกสาร PDF (WnyEditPDF)"
TYPE_NAME_EN = "PDF Document (WnyEditPDF)"
CAPABILITIES_KEY = r"Software\WnyEdit\WnyEditPDF\Capabilities"
CLASSES = r"Software\Classes"

if IS_WINDOWS:
    import winreg
    import ctypes
    from ctypes import wintypes

    HKCU = winreg.HKEY_CURRENT_USER
else:                                   # keep the module importable elsewhere
    winreg = None
    ctypes = None
    wintypes = None
    HKCU = None


# ----------------------------------------------------------------------
#  which command line launches us
# ----------------------------------------------------------------------
def is_frozen():
    """True for the PyInstaller build (a real WnyEditPDF.exe)."""
    return bool(getattr(sys, "frozen", False))


def launcher_exe():
    """The .exe Windows should start: our own build, or the Python launcher."""
    exe = os.path.abspath(sys.executable)
    if is_frozen():
        return exe
    # prefer pythonw.exe so a dev-mode launch has no console window
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else exe


def _entry_script():
    """main.py of this checkout (only needed when not frozen)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "main.py")


def open_command():
    """The full shell\\open\\command string, with %1 for the chosen file."""
    if is_frozen():
        return '"%s" "%%1"' % launcher_exe()
    return '"%s" "%s" "%%1"' % (launcher_exe(), _entry_script())


def app_key_name():
    """Key name under Classes\\Applications. Always our own exe name, so a
    dev-mode registration never hijacks python.exe for every other project."""
    if is_frozen():
        return os.path.basename(launcher_exe())
    return "WnyEditPDF.exe"


def _asset(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)


def app_icon_spec():
    """Icon for the program itself (the "Open with" list, Default apps):
    the application logo."""
    if is_frozen():
        return '"%s",0' % launcher_exe()          # first icon in the .exe
    ico = _asset("logo.ico")
    return '"%s",0' % (ico if os.path.exists(ico) else launcher_exe())


def doc_icon_spec():
    """Icon Explorer puts on the .pdf files themselves.

    This must NOT be the application logo: with the logo every PDF in a folder
    looks like a copy of the program. It is a document icon — a sheet of paper
    with the PDF tag — kept as the second icon resource inside the .exe, so the
    single-file build stays a single file."""
    if is_frozen():
        return '"%s",1' % launcher_exe()          # second icon in the .exe
    ico = _asset("pdf-doc.ico")
    return '"%s",0' % (ico if os.path.exists(ico) else launcher_exe())


# ----------------------------------------------------------------------
#  small registry helpers
# ----------------------------------------------------------------------
def _set(path, value=None, name=None):
    """Create `path` (with any missing parents) and set one string value."""
    with winreg.CreateKeyEx(HKCU, path, 0, winreg.KEY_WRITE) as k:
        if value is not None:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _get(path, name=None):
    try:
        with winreg.OpenKey(HKCU, path, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, name)
            return val
    except OSError:
        return None


def _del_value(path, name):
    try:
        with winreg.OpenKey(HKCU, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _delete_tree(path):
    """Delete a key and everything under it; a missing key is not an error."""
    try:
        with winreg.OpenKey(HKCU, path, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(path + "\\" + sub)
    except OSError:
        return
    try:
        winreg.DeleteKey(HKCU, path)
    except OSError:
        pass


def notify_shell():
    """Tell Explorer the associations changed, so its menus refresh at once."""
    if not IS_WINDOWS:
        return
    shcne_assocchanged = 0x08000000
    shcnf_idlist = 0x0000
    try:
        ctypes.windll.shell32.SHChangeNotify(
            wintypes.LONG(shcne_assocchanged), wintypes.UINT(shcnf_idlist),
            None, None)
    except Exception:
        pass


# ----------------------------------------------------------------------
#  register / unregister
# ----------------------------------------------------------------------
def register(lang="th"):
    """Add WnyEditPDF to the "Open with" list for .pdf files.

    Returns None on success, or an error message."""
    if not IS_WINDOWS:
        return "รองรับเฉพาะ Windows"
    cmd = open_command()
    appkey = app_key_name()
    friendly = TYPE_NAME_EN if lang == "en" else TYPE_NAME_TH
    verb_edit = "Edit with WnyEditPDF" if lang == "en" else "แก้ไขด้วย WnyEditPDF"
    descr = ("PDF reader and editor" if lang == "en"
             else "โปรแกรมอ่านและแก้ไข PDF")
    try:
        # ---- the file type itself ----
        progid = CLASSES + "\\" + PROGID
        _set(progid, friendly)
        _set(progid, friendly, "FriendlyTypeName")
        _set(progid + "\\DefaultIcon", doc_icon_spec())
        _set(progid + "\\shell", "open")
        _set(progid + "\\shell\\open", APP_NAME, "FriendlyAppName")
        _set(progid + "\\shell\\open\\command", cmd)
        # an "edit" verb too, so the right-click menu offers editing
        _set(progid + "\\shell\\edit", verb_edit)
        _set(progid + "\\shell\\edit\\command", cmd)

        # ---- the application entry: this is what "Open with" lists ----
        base = CLASSES + "\\Applications\\" + appkey
        _set(base, APP_NAME, "FriendlyAppName")
        _set(base + "\\DefaultIcon", app_icon_spec())
        _set(base + "\\shell\\open", APP_NAME, "FriendlyAppName")
        _set(base + "\\shell\\open\\command", cmd)
        _set(base + "\\SupportedTypes", "", ".pdf")

        # ---- offer us for .pdf without stealing the current default ----
        _set(CLASSES + "\\.pdf\\OpenWithProgids", "", PROGID)

        # ---- so we appear in Settings > Apps > Default apps ----
        _set(CAPABILITIES_KEY, APP_NAME, "ApplicationName")
        _set(CAPABILITIES_KEY, descr, "ApplicationDescription")
        _set(CAPABILITIES_KEY, app_icon_spec(), "ApplicationIcon")
        _set(CAPABILITIES_KEY + "\\FileAssociations", PROGID, ".pdf")
        _set(r"Software\RegisteredApplications", CAPABILITIES_KEY, APP_NAME)

        # remember what we wrote, to spot a registration left by an old copy
        _set(r"Software\WnyEdit\WnyEditPDF", cmd, "RegisteredCommand")
        _set(r"Software\WnyEdit\WnyEditPDF", VERSION, "RegisteredVersion")
    except OSError as e:
        return str(e)
    notify_shell()
    return None


def unregister():
    """Remove every key register() wrote. Returns None, or an error message."""
    if not IS_WINDOWS:
        return "รองรับเฉพาะ Windows"
    try:
        _delete_tree(CLASSES + "\\" + PROGID)
        _delete_tree(CLASSES + "\\Applications\\" + app_key_name())
        _delete_tree(CAPABILITIES_KEY)
        # drop our ProgID from the .pdf open-with list, leaving other apps alone
        _del_value(CLASSES + "\\.pdf\\OpenWithProgids", PROGID)
        _del_value(r"Software\RegisteredApplications", APP_NAME)
        _del_value(r"Software\WnyEdit\WnyEditPDF", "RegisteredCommand")
        _del_value(r"Software\WnyEdit\WnyEditPDF", "RegisteredVersion")
    except OSError as e:
        return str(e)
    notify_shell()
    return None


# ----------------------------------------------------------------------
#  state queries
# ----------------------------------------------------------------------
def registered_command():
    """The command line currently registered for our ProgID, or None."""
    if not IS_WINDOWS:
        return None
    return _get(CLASSES + "\\" + PROGID + "\\shell\\open\\command", None)


def is_registered():
    return bool(registered_command())


def registered_doc_icon():
    """The icon currently registered for the .pdf file type, or None."""
    if not IS_WINDOWS:
        return None
    return _get(CLASSES + "\\" + PROGID + "\\DefaultIcon", None)


def _same(a, b):
    """Compare two registry strings the way Windows compares paths: the drive
    letter's case is not meaningful, and "D:\\x" and "d:\\x" are one file."""
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def is_stale():
    """Registered, but not with what this copy of the program would write —
    the .exe moved, or an update changed the command or the file icon."""
    cur = registered_command()
    if not cur:
        return False
    if not _same(cur, open_command()):
        return True
    return not _same(registered_doc_icon(), doc_icon_spec())


def _user_choice():
    return _get(r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\FileExts\.pdf\UserChoice", "ProgId")


def is_default():
    """True when .pdf files currently open with us."""
    if not IS_WINDOWS:
        return False
    choice = _user_choice()
    if choice:
        return choice == PROGID
    # no explicit user choice yet: fall back to the per-user class default
    return _get(CLASSES + "\\.pdf", None) == PROGID


def default_handler_name():
    """ProgID that handles .pdf right now (to show the user), or None."""
    if not IS_WINDOWS:
        return None
    return _user_choice() or _get(CLASSES + "\\.pdf", None)


# ----------------------------------------------------------------------
#  becoming the default (Windows insists the user confirms this)
# ----------------------------------------------------------------------
OAIF_ALLOW_REGISTRATION = 0x00000001
OAIF_REGISTER_EXT = 0x00000002
OAIF_EXEC = 0x00000004
OAIF_HIDE_REGISTRATION = 0x00000020

_CANCELLED = -2147023673        # HRESULT_FROM_WIN32(ERROR_CANCELLED)

if IS_WINDOWS:
    class _OPENASINFO(ctypes.Structure):
        _fields_ = [("pcszFile", wintypes.LPCWSTR),
                    ("pcszClass", wintypes.LPCWSTR),
                    ("oaifInFlags", ctypes.c_int)]


def open_with_dialog(sample_pdf=None, hwnd=0):
    """Show Windows' own "How do you want to open this file?" dialog, where
    ticking "Always use this app" makes us the default. Returns None on
    success, "cancelled" if the user backed out, else an error message."""
    if not IS_WINDOWS:
        return "รองรับเฉพาะ Windows"
    info = _OPENASINFO()
    has_file = bool(sample_pdf) and os.path.exists(sample_pdf or "")
    info.pcszFile = sample_pdf if has_file else None
    info.pcszClass = None if has_file else ".pdf"
    info.oaifInFlags = OAIF_ALLOW_REGISTRATION | OAIF_REGISTER_EXT
    try:
        hr = ctypes.windll.shell32.SHOpenWithDialog(
            wintypes.HWND(hwnd), ctypes.byref(info))
    except Exception as e:
        return str(e)
    if hr == _CANCELLED:
        return "cancelled"
    if hr == 0:
        notify_shell()
        return None
    return "SHOpenWithDialog: 0x%08X" % (hr & 0xFFFFFFFF)


def open_default_apps_settings():
    """Open Settings > Default apps, deep-linked to us where Windows allows."""
    if not IS_WINDOWS:
        return "รองรับเฉพาะ Windows"
    for target in ("ms-settings:defaultapps?registeredAEN=" + app_key_name(),
                   "ms-settings:defaultapps?registeredAppUser=" + APP_NAME,
                   "ms-settings:defaultapps"):
        try:
            os.startfile(target)
            return None
        except OSError:
            continue
    return "เปิดหน้าตั้งค่าไม่สำเร็จ"
