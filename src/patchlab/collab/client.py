"""Cliente WebSocket del Colaborador (transporte ``QtWebSockets``).

:class:`CollabClient` encapsula la conexión con el Host: realiza el *handshake*
de autenticación, recibe los mensajes de coordinación del flujo distribuido y
los reexpone como **señales Qt** de alto nivel, y ofrece métodos para pedir la
siguiente imagen del shard y enviar las etiquetas. No contiene lógica de
etiquetado: de eso se ocupa
:class:`~patchlab.collab.remote_controller.RemoteGridController`.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket

from patchlab.collab import protocol

#: Tope de tamaño de los mensajes entrantes (el snapshot JPEG puede pesar MB).
_MAX_INCOMING_BYTES = 64 * 1024 * 1024


class CollabClient(QObject):
    """Conexión con un Host de PatchLab y traductor de su protocolo a señales."""

    #: Conexión establecida (antes de autenticarse).
    connectedToHost = Signal()
    #: Acceso concedido: ``(you_id, labels, phase)``.
    welcomed = Signal(int, list, str)
    #: Acceso rechazado por el Host.
    denied = Signal(str)
    #: Estado del lobby: ``(participants, total_images, phase)``.
    lobbyReceived = Signal(list, int, str)
    #: Tamaño del shard asignado: ``(count, total_images)``.
    assignmentReceived = Signal(int, int)
    #: Snapshot de una imagen a etiquetar (diccionario del mensaje ``image``).
    imageReceived = Signal(dict)
    #: Progreso: ``(me, all)``.
    progressReceived = Signal(dict, list)
    #: Transición de fase de la sesión.
    phaseReceived = Signal(str)
    #: El cliente completó toda su porción.
    shardDone = Signal()
    #: La conexión se cerró (motivo o error como texto).
    connectionClosed = Signal(str)

    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        name: str,
        parent: Optional[QObject] = None,
    ) -> None:
        """
        Args:
            host: IP o nombre del Host.
            port: Puerto del servicio colaborativo.
            token: Contraseña de sesión.
            name: Nombre visible del colaborador.
        """
        super().__init__(parent)
        self._host = host
        self._port = port
        self._token = token
        self._name = name
        self._socket = QWebSocket()
        if hasattr(self._socket, "setMaxAllowedIncomingMessageSize"):
            self._socket.setMaxAllowedIncomingMessageSize(_MAX_INCOMING_BYTES)

        self._socket.connected.connect(self._on_connected)
        self._socket.textMessageReceived.connect(self._on_text)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.errorOccurred.connect(self._on_error)

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def open(self) -> None:
        """Inicia la conexión con el Host."""
        self._socket.open(QUrl(f"ws://{self._host}:{self._port}"))

    def close(self) -> None:
        """Cierra la conexión de forma ordenada."""
        self._socket.close()

    # ------------------------------------------------------------------ #
    # Envío de comandos (Colaborador → Host)
    # ------------------------------------------------------------------ #
    def request_next(self) -> None:
        """Pide la siguiente imagen del shard asignado."""
        self._send(protocol.build_request_next())

    def submit(self, index: int, labels: List[Optional[str]]) -> None:
        """Envía el vector de etiquetas de la imagen ``index`` ya etiquetada."""
        self._send(protocol.build_submit(index, labels))

    # ------------------------------------------------------------------ #
    # Reacciones del socket
    # ------------------------------------------------------------------ #
    def _on_connected(self) -> None:
        """Tras conectar, envía el *handshake* de autenticación."""
        self.connectedToHost.emit()
        self._send(protocol.build_hello(self._token, self._name))

    def _on_text(self, raw: str) -> None:
        """Decodifica un mensaje del Host y emite la señal correspondiente."""
        try:
            msg = protocol.parse_server_message(raw)
        except protocol.ProtocolError:
            return

        kind = msg["t"]
        if kind == protocol.T_WELCOME:
            self.welcomed.emit(msg["you"], msg["labels"], msg["phase"])
        elif kind == protocol.T_DENIED:
            self.denied.emit(msg.get("reason", "Acceso denegado."))
        elif kind == protocol.T_LOBBY:
            self.lobbyReceived.emit(
                msg["participants"], msg["total_images"], msg["phase"]
            )
        elif kind == protocol.T_ASSIGNMENT:
            self.assignmentReceived.emit(msg["count"], msg["total_images"])
        elif kind == protocol.T_IMAGE:
            self.imageReceived.emit(msg)
        elif kind == protocol.T_PROGRESS:
            self.progressReceived.emit(msg["me"], msg["all"])
        elif kind == protocol.T_PHASE:
            self.phaseReceived.emit(msg["phase"])
        elif kind == protocol.T_SHARD_DONE:
            self.shardDone.emit()
        elif kind == protocol.T_BYE:
            self.connectionClosed.emit(msg.get("reason", "Sesión finalizada."))

    def _on_disconnected(self) -> None:
        """Notifica el cierre de la conexión."""
        self.connectionClosed.emit("Conexión cerrada.")

    def _on_error(self, _error) -> None:
        """Propaga un error de socket como cierre con su descripción."""
        self.connectionClosed.emit(self._socket.errorString())

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #
    def _send(self, message: dict) -> None:
        """Serializa y envía un mensaje al Host."""
        self._socket.sendTextMessage(protocol.encode(message))
