"""Servidor colaborativo del Host: adaptador de red del coordinador.

:class:`CollabServer` es una capa **fina** de transporte (``QtWebSockets``) sobre
el :class:`~patchlab.collab.coordinator.SessionCoordinator`. Sus únicas
responsabilidades son:

- aceptar conexiones, **autenticarlas** con el token de sesión y traducir cada
  socket en un ``worker_id`` del coordinador;
- **encaminar** los comandos validados del cliente (``request_next``/``submit``)
  hacia el coordinador, y los mensajes unicast del coordinador (``image``,
  ``assignment``, ``shard_done``) hacia el socket correspondiente;
- **difundir** las señales de estado del coordinador (lobby, progreso, fase) a
  todos los clientes.

Toda la lógica de reparto, consolidación y progreso vive en el coordinador; aquí
no hay estado de sesión, solo el mapa socket ↔ trabajador.
"""

from __future__ import annotations

import hmac
from typing import Dict, Optional, Set

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocket, QWebSocketServer

from patchlab.collab import protocol
from patchlab.collab.coordinator import SessionCoordinator

#: Plazo para completar el *handshake* antes de cerrar la conexión.
_HANDSHAKE_TIMEOUT_MS = 5000


class CollabServer(QObject):
    """Servidor WebSocket que conecta a los colaboradores con el coordinador."""

    #: El servidor empezó a escuchar (ip, puerto, token).
    serverStarted = Signal(str, int, str)
    #: El servidor se detuvo.
    serverStopped = Signal()
    #: Error no recuperable al iniciar o durante la sesión.
    errorOccurred = Signal(str)

    def __init__(
        self, coordinator: SessionCoordinator, parent: Optional[QObject] = None
    ) -> None:
        """
        Args:
            coordinator: Coordinador autoritativo de la sesión distribuida.
        """
        super().__init__(parent)
        self._coordinator = coordinator
        self._token = ""
        self._server: Optional[QWebSocketServer] = None

        self._sockets: Dict[int, QWebSocket] = {}   # worker_id → socket
        self._ids: Dict[QWebSocket, int] = {}       # socket → worker_id
        self._pending: Set[QWebSocket] = set()

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def start(self, token: str, port: int) -> bool:
        """Empieza a escuchar en ``port`` con el ``token`` dado."""
        if self._server is not None:
            return True
        self._token = token
        server = QWebSocketServer(
            "PatchLab Collab", QWebSocketServer.SslMode.NonSecureMode, self
        )
        if not server.listen(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), port):
            self.errorOccurred.emit(
                f"No se pudo escuchar en el puerto {port}: {server.errorString()}"
            )
            server.deleteLater()
            return False

        self._server = server
        server.newConnection.connect(self._on_new_connection)
        self._coordinator.messageForWorker.connect(self._on_message_for_worker)
        self._coordinator.lobbyChanged.connect(self._broadcast_lobby)
        self._coordinator.progressChanged.connect(self._broadcast_progress)
        self._coordinator.phaseChanged.connect(self._broadcast_phase)

        self.serverStarted.emit(
            server.serverAddress().toString(), int(server.serverPort()), token
        )
        return True

    def stop(self) -> None:
        """Cierra todas las conexiones y deja de escuchar."""
        if self._server is None:
            return
        bye = protocol.encode(protocol.build_bye("La sesión se ha cerrado."))
        for socket in list(self._ids):
            socket.sendTextMessage(bye)
            socket.close()
        for socket in list(self._pending):
            socket.close()

        for signal, slot in (
            (self._coordinator.messageForWorker, self._on_message_for_worker),
            (self._coordinator.lobbyChanged, self._broadcast_lobby),
            (self._coordinator.progressChanged, self._broadcast_progress),
            (self._coordinator.phaseChanged, self._broadcast_phase),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

        self._server.close()
        self._server.deleteLater()
        self._server = None
        self._sockets.clear()
        self._ids.clear()
        self._pending.clear()
        self.serverStopped.emit()

    @property
    def is_running(self) -> bool:
        """``True`` si el servidor está escuchando."""
        return self._server is not None

    # ------------------------------------------------------------------ #
    # Aceptación y autenticación
    # ------------------------------------------------------------------ #
    def _on_new_connection(self) -> None:
        """Acepta un socket entrante y arranca su ventana de *handshake*."""
        assert self._server is not None
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        if hasattr(socket, "setMaxAllowedIncomingMessageSize"):
            socket.setMaxAllowedIncomingMessageSize(protocol.MAX_CLIENT_MESSAGE_BYTES)
        self._pending.add(socket)
        socket.textMessageReceived.connect(
            lambda raw, s=socket: self._on_message(s, raw)
        )
        socket.disconnected.connect(lambda s=socket: self._on_disconnected(s))
        QTimer.singleShot(
            _HANDSHAKE_TIMEOUT_MS, lambda s=socket: self._drop_if_pending(s)
        )

    def _drop_if_pending(self, socket: QWebSocket) -> None:
        """Cierra un socket que no completó el *handshake* en plazo."""
        if socket in self._pending:
            self._send(socket, protocol.build_denied("Tiempo de autenticación agotado."))
            socket.close()

    def _authenticate(self, socket: QWebSocket, raw: str) -> None:
        """Procesa el ``hello`` inicial; concede o rechaza el acceso."""
        try:
            hello = protocol.parse_hello(raw)
        except protocol.ProtocolError as exc:
            self._send(socket, protocol.build_denied(f"Handshake inválido: {exc}"))
            socket.close()
            return
        if not hmac.compare_digest(hello["token"], self._token):
            self._send(socket, protocol.build_denied("Contraseña de sesión incorrecta."))
            socket.close()
            return

        identity = self._coordinator.add_remote_worker(hello["name"])
        worker_id = identity["id"]
        self._pending.discard(socket)
        self._sockets[worker_id] = socket
        self._ids[socket] = worker_id

        self._send(
            socket,
            protocol.build_welcome(
                worker_id, self._coordinator.labels, self._coordinator.phase.value
            ),
        )
        self._send(
            socket,
            protocol.build_lobby(
                self._coordinator.participants(),
                self._coordinator.total_images(),
                self._coordinator.phase.value,
            ),
        )

    # ------------------------------------------------------------------ #
    # Mensajería de clientes autenticados
    # ------------------------------------------------------------------ #
    def _on_message(self, socket: QWebSocket, raw: str) -> None:
        """Encamina un mensaje según el socket esté o no autenticado."""
        if socket in self._pending:
            self._authenticate(socket, raw)
            return
        worker_id = self._ids.get(socket)
        if worker_id is None:
            return
        try:
            msg = protocol.parse_client_message(raw, label_set=self._coordinator.labels)
        except protocol.ProtocolError:
            return  # Comando inválido o no permitido: se ignora.

        if msg["t"] == protocol.T_REQUEST_NEXT:
            self._coordinator.request_next(worker_id)
        elif msg["t"] == protocol.T_SUBMIT:
            self._coordinator.submit(worker_id, msg["index"], msg["labels"])

    def _on_disconnected(self, socket: QWebSocket) -> None:
        """Limpia el estado de un colaborador que se desconecta."""
        self._pending.discard(socket)
        worker_id = self._ids.pop(socket, None)
        try:
            socket.deleteLater()
        except RuntimeError:
            pass
        if worker_id is None:
            return
        self._sockets.pop(worker_id, None)
        self._coordinator.remove_remote_worker(worker_id)

    # ------------------------------------------------------------------ #
    # Salida hacia los clientes
    # ------------------------------------------------------------------ #
    def _on_message_for_worker(self, worker_id: int, message: object) -> None:
        """Entrega un mensaje unicast del coordinador al socket del trabajador."""
        socket = self._sockets.get(worker_id)
        if socket is not None:
            self._send(socket, message)  # type: ignore[arg-type]

    def _broadcast_lobby(self, participants: list) -> None:
        """Difunde el estado del lobby a todos los clientes."""
        self._broadcast(
            protocol.build_lobby(
                participants,
                self._coordinator.total_images(),
                self._coordinator.phase.value,
            )
        )

    def _broadcast_phase(self, phase: str) -> None:
        """Difunde una transición de fase a todos los clientes."""
        self._broadcast(protocol.build_phase(phase))

    def _broadcast_progress(self, everyone: list) -> None:
        """Envía a cada cliente su progreso propio junto al de todos."""
        by_id = {entry["id"]: entry for entry in everyone}
        for worker_id, socket in self._sockets.items():
            me = by_id.get(worker_id, {"assigned": 0, "completed": 0})
            self._send(socket, protocol.build_progress(me, everyone))

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _send(self, socket: QWebSocket, message: dict) -> None:
        """Serializa y envía un mensaje a un socket concreto."""
        socket.sendTextMessage(protocol.encode(message))

    def _broadcast(self, message: dict) -> None:
        """Envía un mensaje a todos los colaboradores autenticados."""
        payload = protocol.encode(message)
        for socket in self._sockets.values():
            socket.sendTextMessage(payload)
