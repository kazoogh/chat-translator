from __future__ import annotations

from collections.abc import Callable
from typing import Any


class SingleInstanceGuard:
    """Keep one desktop owner and ask the existing instance to show itself."""

    def __init__(self, name: str, on_activate: Callable[[], None]) -> None:
        if not name.strip():
            raise ValueError("single-instance name must not be empty")
        from PySide6.QtNetwork import QLocalServer, QLocalSocket

        self._server: Any = None
        self._client: Any = None
        self._connections: list[Any] = []
        self._on_activate = on_activate
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(250):
            probe.write(b"activate\n")
            probe.waitForBytesWritten(250)
            self._client = probe
            self.is_primary = False
            return

        QLocalServer.removeServer(name)
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(name):
            raise RuntimeError("the desktop single-instance endpoint could not be opened")
        server.newConnection.connect(self._accept_connections)
        self._server = server
        self.is_primary = True

    def _accept_connections(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._connections.append(socket)
            socket.readyRead.connect(lambda selected=socket: self._read_activation(selected))
            socket.disconnected.connect(lambda selected=socket: self._release_connection(selected))
            if socket.bytesAvailable():
                self._read_activation(socket)

    def _read_activation(self, socket: Any) -> None:
        payload = bytes(socket.readAll())
        if payload.startswith(b"activate"):
            self._on_activate()
        socket.disconnectFromServer()

    def _release_connection(self, socket: Any) -> None:
        if socket in self._connections:
            self._connections.remove(socket)
        socket.deleteLater()

    def close(self) -> None:
        if self._client is not None:
            self._client.abort()
            self._client = None
        if self._server is None:
            return
        self._server.close()
        self._server = None
        for socket in tuple(self._connections):
            socket.abort()
            self._release_connection(socket)
