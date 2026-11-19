# -*- coding: utf-8 -*-
"""One window, many "Open with" clicks.

When Windows launches us for a PDF while WnyEditPDF is already running, the
second process hands the file path to the first one over a local socket and
quits, so the user keeps a single window instead of collecting one per file —
the way Acrobat behaves.

Every failure here is non-fatal: if the socket cannot be created or reached,
the new process simply opens its own window.
"""

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .config import APP_NAME

# per-user name, so two accounts on one PC do not fight over the socket
def _server_name():
    import getpass
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return "%s-ipc-%s" % (APP_NAME, user)


SERVER_NAME = _server_name()
_TIMEOUT_MS = 500


def send_to_running_instance(path):
    """Try to hand `path` (may be "") to an instance that is already running.

    Returns True when another instance accepted it — the caller should quit."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(_TIMEOUT_MS):
        return False
    try:
        sock.write((path or "").encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(_TIMEOUT_MS)
        sock.disconnectFromServer()
        # wait for the close to go through, so this process does not exit (and
        # drop the socket) before the other one has taken the bytes
        if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(_TIMEOUT_MS)
    except Exception:
        return False
    return True


class InstanceServer(QObject):
    """Listens for paths sent by later launches. Emits `opened(path)`."""

    opened = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        # a crashed run can leave the socket behind; clear it before listening
        QLocalServer.removeServer(SERVER_NAME)
        self._ok = self._server.listen(SERVER_NAME)
        if self._ok:
            self._server.newConnection.connect(self._on_connection)

    def is_listening(self):
        return self._ok

    def _on_connection(self):
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        sock.disconnected.connect(sock.deleteLater)
        # the path is one small write, so waiting for it here keeps the whole
        # exchange in one place; readyRead stays connected as a safety net in
        # case the sender was slower than the timeout
        sock.readyRead.connect(lambda s=sock: self._on_ready(s))
        if sock.bytesAvailable() or sock.waitForReadyRead(_TIMEOUT_MS):
            self._on_ready(sock)

    def _on_ready(self, sock):
        try:
            data = bytes(sock.readAll()).decode("utf-8", "replace").strip()
        except Exception:
            data = ""
        if not data:
            return
        try:                      # one message per connection, no repeats
            sock.readyRead.disconnect()
        except TypeError:
            pass
        self.opened.emit(data)
