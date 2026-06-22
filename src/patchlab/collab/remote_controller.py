"""Controlador del Colaborador: adapta la red a la API de la vista.

:class:`RemoteGridController` implementa el mismo contrato que
:class:`~patchlab.controllers.grid_controller.GridController`
(:class:`~patchlab.controllers.interfaces.GridControllerLike`), pero su trabajo
proviene de un **shard** del dataset servido por el Host a través de un
:class:`~patchlab.collab.client.CollabClient`.

A diferencia del modo anterior (co-edición de una misma imagen), aquí el
colaborador etiqueta **sus propias imágenes** de forma local y completa
(pintar/limpiar/llenar/deshacer), y solo al confirmar envía el vector de
etiquetas al Host, que lo consolida. Reutiliza ``GridWindow``/``GridCanvas`` sin
cambios; añade señales para el lobby, las fases y el progreso.
"""

from __future__ import annotations

import base64
from typing import List, Optional

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal

from patchlab.collab.client import CollabClient
from patchlab.collab.session import SessionPhase
from patchlab.controllers.grid_controller import GridFrame
from patchlab.models.grid_session import GridSession
from patchlab.models.patch import Patch

# Placeholder de ``Patch.original``: el colaborador no guarda recortes (lo hace
# el Host), por lo que no necesita los píxeles del parche.
_PLACEHOLDER = np.zeros((1, 1, 3), dtype=np.uint8)


class RemoteGridController(QObject):
    """Controlador de cuadrícula alimentado por un shard remoto (Colaborador)."""

    # -- Señales del contrato GridControllerLike -------------------------- #
    gridReady = Signal(object)
    overlayChanged = Signal()
    activeClassChanged = Signal(str)
    historyChanged = Signal(bool, bool)
    statusMessage = Signal(str)
    busyChanged = Signal(bool)
    finished = Signal(str)

    # -- Señales del flujo distribuido ------------------------------------ #
    phaseChanged = Signal(str)
    lobbyChanged = Signal(list)
    progressChanged = Signal(list)
    assignmentChanged = Signal(int, int)        # (count, total_images)
    myProgressChanged = Signal(int, int)         # (completed, assigned)
    shardCompleted = Signal()

    def __init__(self, client: CollabClient, parent: Optional[QObject] = None) -> None:
        """
        Args:
            client: Cliente WebSocket ya configurado (sin abrir todavía).
        """
        super().__init__(parent)
        self._client = client
        self._labels: List[str] = []
        self._active_class = ""
        self._session: Optional[GridSession] = None
        self._image_id: Optional[int] = None
        self._phase = SessionPhase.LOBBY.value
        self._shard_total = 0

        client.welcomed.connect(self._on_welcomed)
        client.denied.connect(self._on_denied)
        client.lobbyReceived.connect(self._on_lobby)
        client.assignmentReceived.connect(self._on_assignment)
        client.imageReceived.connect(self._on_image)
        client.progressReceived.connect(self._on_progress)
        client.phaseReceived.connect(self._on_phase)
        client.shardDone.connect(self._on_shard_done)
        client.connectionClosed.connect(self._on_closed)

    # ------------------------------------------------------------------ #
    # Arranque
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Abre la conexión con el Host."""
        self.statusMessage.emit("Conectando con el Host…")
        self._client.open()

    @property
    def labels(self) -> List[str]:
        """Etiquetas anunciadas por el Host (tras el *welcome*)."""
        return self._labels

    @property
    def active_class(self) -> str:
        """Clase activa local (la que se aplicará al pintar)."""
        return self._active_class

    # ------------------------------------------------------------------ #
    # API de intenciones (consumida por la vista) — etiquetado LOCAL
    # ------------------------------------------------------------------ #
    def set_active_class(self, label: str) -> None:
        """Fija la clase activa local."""
        if label in self._labels and label != self._active_class:
            self._active_class = label
            self.activeClassChanged.emit(label)

    def cycle_active_class(self) -> None:
        """Alterna a la siguiente clase de la lista."""
        if not self._labels:
            return
        current = self._labels.index(self._active_class)
        self.set_active_class(self._labels[(current + 1) % len(self._labels)])

    def paint_cell(self, index: int) -> None:
        """Pinta una celda en la sesión local."""
        if self._session is not None and self._session.paint(index, self._active_class):
            self._after_edit()

    def clear_cell(self, index: int) -> None:
        """Limpia una celda en la sesión local."""
        if self._session is not None and self._session.clear(index):
            self._after_edit()

    def fill_remaining(self, label: Optional[str] = None) -> None:
        """Etiqueta las celdas restantes con la clase indicada o la activa."""
        if self._session is None:
            return
        target = label or self._active_class
        if self._session.fill_remaining(target):
            self.statusMessage.emit(f"Celdas restantes rellenadas con «{target}».")
            self._after_edit()

    def undo(self) -> None:
        """Deshace la última acción local."""
        if self._session is not None and self._session.undo():
            self._after_edit()

    def redo(self) -> None:
        """Rehace la última acción deshecha local."""
        if self._session is not None and self._session.redo():
            self._after_edit()

    def confirm_and_next(self) -> None:
        """Envía las etiquetas de la imagen actual y pide la siguiente."""
        if self._session is None or self._image_id is None:
            return
        labels = [patch.label for patch in self._session.patches]
        self._client.submit(self._image_id, labels)
        self._client.request_next()
        self._session = None
        self._image_id = None
        self.statusMessage.emit("Imagen enviada. Cargando la siguiente…")

    def quit(self) -> None:
        """Abandona la sesión colaborativa."""
        self._client.close()
        self.finished.emit("Has salido de la sesión colaborativa.")

    def shutdown(self) -> None:
        """Cierra la conexión al destruir la ventana."""
        self._client.close()

    # ------------------------------------------------------------------ #
    # Reacciones a los mensajes del Host
    # ------------------------------------------------------------------ #
    def _on_welcomed(self, _you: int, labels: list, phase: str) -> None:
        """Guarda las etiquetas y, si la sesión ya arrancó, pide trabajo."""
        self._labels = list(labels)
        if self._labels:
            self._active_class = self._labels[0]
            self.activeClassChanged.emit(self._active_class)
        self._phase = phase
        self.phaseChanged.emit(phase)
        if phase == SessionPhase.LABELING.value:
            self._client.request_next()  # Unión tardía: reclama trabajo.

    def _on_denied(self, reason: str) -> None:
        """El Host rechazó el acceso: termina la sesión."""
        self.finished.emit(f"Acceso denegado: {reason}")

    def _on_lobby(self, participants: list, total_images: int, phase: str) -> None:
        """Actualiza el estado del lobby (participantes y tamaño del dataset)."""
        self._phase = phase
        self.lobbyChanged.emit(participants)
        self.phaseChanged.emit(phase)
        if phase == SessionPhase.LOBBY.value:
            self.statusMessage.emit(
                f"En el lobby · {len(participants)} participante(s) · "
                f"{total_images} imágenes. Esperando al Host…"
            )

    def _on_assignment(self, count: int, total_images: int) -> None:
        """Recibe el tamaño del shard asignado."""
        self._shard_total = count
        self.assignmentChanged.emit(count, total_images)
        self.statusMessage.emit(
            f"Se te han asignado {count} de {total_images} imágenes."
        )

    def _on_image(self, msg: dict) -> None:
        """Reconstruye una imagen del shard y la presenta para etiquetar."""
        image = self._decode_jpeg(msg["jpeg_b64"])
        if image is None:
            self.statusMessage.emit("No se pudo decodificar la imagen del Host.")
            return
        # Sugerencias del clasificador del Host (si las envió), alineadas con las
        # celdas; el Host es de confianza, así que se aceptan tal cual.
        suggestions = msg.get("suggestions") or []
        patches = [
            Patch(
                index=i,
                source_type="grid",
                x=x,
                y=y,
                w=w,
                h=h,
                original=_PLACEHOLDER,
                suggested_label=suggestions[i] if i < len(suggestions) else None,
            )
            for i, (x, y, w, h) in enumerate(msg["cells"])
        ]
        self._session = GridSession(patches)
        self._image_id = msg["index"]
        # Pre-pinta las celdas sugeridas (estado de partida, sin historial) para
        # que el colaborador solo revise y corrija.
        prefilled = self._session.prefill_suggestions()
        shard_total = msg.get("shard_total", self._shard_total)
        position = msg.get("position", 1)
        self.gridReady.emit(
            GridFrame(
                image=image,
                session=self._session,
                file_name=msg.get("file_name", ""),
                image_index=position - 1,
                image_total=shard_total,
            )
        )
        self.historyChanged.emit(False, False)
        base = f"Imagen «{msg.get('file_name', '')}» ({position}/{shard_total})."
        if prefilled:
            base += f" {prefilled} celdas pre-etiquetadas; revisa y corrige."
        self.statusMessage.emit(base)

    def _on_progress(self, me: dict, everyone: list) -> None:
        """Difunde el progreso para el panel y los indicadores propios."""
        self.progressChanged.emit(everyone)
        self.myProgressChanged.emit(
            int(me.get("completed", 0)), int(me.get("assigned", 0))
        )

    def _on_phase(self, phase: str) -> None:
        """Reacciona a una transición de fase de la sesión."""
        self._phase = phase
        self.phaseChanged.emit(phase)
        if phase == SessionPhase.FINISHED.value:
            self.finished.emit("La sesión ha finalizado. ¡Gracias por colaborar!")

    def _on_shard_done(self) -> None:
        """El colaborador completó toda su porción asignada."""
        self._session = None
        self._image_id = None
        self.shardCompleted.emit()
        self.statusMessage.emit("Has completado tu porción. ¡Gracias!")

    def _on_closed(self, reason: str) -> None:
        """La conexión terminó: cierra la sesión del Colaborador."""
        self.finished.emit(f"Conexión finalizada: {reason}")

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _after_edit(self) -> None:
        """Notifica a la vista tras un cambio en la cuadrícula local."""
        self.overlayChanged.emit()
        if self._session is not None:
            self.historyChanged.emit(self._session.can_undo, self._session.can_redo)

    @staticmethod
    def _decode_jpeg(jpeg_b64: str) -> Optional[np.ndarray]:
        """Decodifica un JPEG en base64 a una imagen BGR de OpenCV."""
        try:
            raw = base64.b64decode(jpeg_b64)
        except (ValueError, TypeError):
            return None
        buffer = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(buffer, cv2.IMREAD_COLOR)
