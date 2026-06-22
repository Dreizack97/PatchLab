"""Coordinador de la sesión colaborativa distribuida (Host).

:class:`SessionCoordinator` es la **autoridad** y la **fuente de verdad** del
flujo distribuido. Concentra, en un único pipeline del hilo principal:

- la **máquina de fases** (lobby → etiquetado → finalizado),
- el **reparto** del dataset en shards (:mod:`patchlab.collab.session`),
- la **extracción** de parches y el **guardado** consolidado en disco (reutiliza
  los *workers* del modo monousuario en un hilo secundario),
- el **progreso** de cada trabajador y la **redistribución** de su trabajo
  pendiente si se desconecta.

Sirve por igual a los colaboradores remotos (a través de
:class:`~patchlab.collab.server.CollabServer`) y al **propio Host como
trabajador**, mediante :class:`LocalWorker`, una fachada que implementa
:class:`~patchlab.controllers.interfaces.GridControllerLike` y permite reutilizar
``GridWindow``/``GridCanvas`` sin cambios.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from patchlab.collab import protocol
from patchlab.collab.presence import Roster
from patchlab.collab.session import SessionPhase, SessionState, ShardPlanner
from patchlab.controllers.grid_controller import GridFrame
from patchlab.controllers.save_worker import GridSaveWorker
from patchlab.controllers.worker import ExtractionWorker
from patchlab.models.config import LabelerConfig
from patchlab.models.grid_session import GridSession
from patchlab.models.patch import Patch
from patchlab.models.repository import DatasetRepository
from patchlab.services.classifier import create_classifier
from patchlab.services.extractor import create_extractor

#: Identificador reservado del Host como trabajador local.
HOST_ID = 0
#: Nombre y color de presencia del Host en el panel supervisor.
HOST_NAME = "Host (tú)"
HOST_COLOR = "#dddddd"
#: Calidad JPEG del streaming de imágenes a los colaboradores.
_JPEG_QUALITY = 85


class SessionCoordinator(QObject):
    """Orquesta el reparto, el etiquetado distribuido y la consolidación."""

    #: La fase de la sesión cambió (valor de :class:`SessionPhase`).
    phaseChanged = Signal(str)
    #: Cambió el lobby (lista de participantes ``{id,name,color,connected}``).
    lobbyChanged = Signal(list)
    #: Cambió el progreso (lista ``{id,name,color,assigned,completed,connected}``).
    progressChanged = Signal(list)
    #: Mensaje unicast para un colaborador remoto: ``(worker_id, dict)``.
    messageForWorker = Signal(int, object)
    #: La sesión finalizó; lleva un resumen como texto.
    finished = Signal(str)

    def __init__(
        self, config: LabelerConfig, images: List[Path], parent: Optional[QObject] = None
    ) -> None:
        """
        Args:
            config: Configuración validada de la sesión (modo cuadrícula).
            images: Lista no vacía de imágenes del dataset completo.
        """
        super().__init__(parent)
        self._config = config
        self._images = images
        self._phase = SessionPhase.LOBBY
        self._state = SessionState()
        self._roster = Roster()  # asigna ids/colores a los remotos.

        # Metadatos por trabajador (incluye al Host).
        self._names: Dict[int, str] = {HOST_ID: HOST_NAME}
        self._colors: Dict[int, str] = {HOST_ID: HOST_COLOR}
        self._connected: Dict[int, bool] = {HOST_ID: True}

        # Consolidación: imagen → parches extraídos pendientes de guardar.
        self._cache: Dict[int, List[Patch]] = {}
        self._pending_extraction: Dict[int, int] = {}  # image_id → worker_id
        self._saved_total = 0
        # Cierre diferido: no se finaliza hasta drenar los guardados en vuelo.
        self._pending_saves = 0
        self._finish_requested = False
        self._repo_closed = False

        self._repository = DatasetRepository(config.output_dir)
        self._configure_workers()
        self.local = LocalWorker(self, config.labels)

    # ------------------------------------------------------------------ #
    # Hilo secundario (extracción + guardado), reutilizado del modo local
    # ------------------------------------------------------------------ #
    _requestExtraction = Signal(int)
    _requestSave = Signal(str, object)

    def _configure_workers(self) -> None:
        """Crea los workers de extracción y guardado en un hilo dedicado."""
        self._thread = QThread()
        # El modelo de clasificación (si lo hay) vive solo en el Host: clasifica
        # cada parche y sus sugerencias se propagan a la grilla local y a los
        # colaboradores remotos, que no necesitan cargar el modelo.
        self._extraction_worker = ExtractionWorker(
            self._images,
            create_extractor(self._config),
            create_classifier(self._config),
        )
        self._save_worker = GridSaveWorker(self._repository)
        self._extraction_worker.moveToThread(self._thread)
        self._save_worker.moveToThread(self._thread)

        self._requestExtraction.connect(self._extraction_worker.extract)
        self._requestSave.connect(self._save_worker.save)
        self._extraction_worker.patchesReady.connect(self._on_patches_ready)
        self._extraction_worker.imageSkipped.connect(self._on_image_unusable)
        self._extraction_worker.extractionFailed.connect(self._on_extraction_failed)
        self._save_worker.saved.connect(self._on_saved)
        self._thread.start()

    # ------------------------------------------------------------------ #
    # Estado expuesto (consumido por el servidor y la ventana)
    # ------------------------------------------------------------------ #
    @property
    def phase(self) -> SessionPhase:
        """Fase actual de la sesión."""
        return self._phase

    @property
    def labels(self) -> List[str]:
        """Etiquetas de clase declaradas para la sesión."""
        return self._config.labels

    def total_images(self) -> int:
        """Número total de imágenes del dataset."""
        return len(self._images)

    def participants(self) -> List[dict]:
        """Lista serializable de participantes (Host + remotos)."""
        return [
            {
                "id": worker_id,
                "name": self._names[worker_id],
                "color": self._colors[worker_id],
                "connected": self._connected[worker_id],
            }
            for worker_id in sorted(self._connected)
            if self._connected[worker_id]
        ]

    def progress_payload(self) -> List[dict]:
        """Progreso de cada trabajador para el panel supervisor."""
        payload: List[dict] = []
        for worker_id in sorted(self._connected):
            if not self._connected[worker_id]:
                continue
            prog = self._state.progress_of(worker_id, connected=True)
            payload.append(
                {
                    "id": worker_id,
                    "name": self._names[worker_id],
                    "color": self._colors[worker_id],
                    "assigned": prog.assigned,
                    "completed": prog.completed,
                    "connected": True,
                }
            )
        return payload

    # ------------------------------------------------------------------ #
    # Gestión de trabajadores remotos (llamado por el servidor)
    # ------------------------------------------------------------------ #
    def add_remote_worker(self, name: str) -> dict:
        """
        Registra un colaborador remoto y devuelve su identidad.

        Returns:
            Diccionario ``{id, name, color}`` del nuevo trabajador.
        """
        member = self._roster.add(name)
        worker_id = member.client_id
        self._names[worker_id] = name
        self._colors[worker_id] = member.color
        self._connected[worker_id] = True
        self._state.add_worker(worker_id)
        self._emit_lobby()
        self._emit_progress()
        return {"id": worker_id, "name": name, "color": member.color}

    def remove_remote_worker(self, worker_id: int) -> None:
        """Da de baja a un colaborador y redistribuye su trabajo si procede."""
        if not self._connected.get(worker_id, False):
            return
        self._connected[worker_id] = False

        if self._phase is SessionPhase.LABELING:
            pending = self._state.remove_worker(worker_id)
            active = [w for w in self._active_worker_ids() if w != worker_id]
            self._roster.remove(worker_id)
            if pending and active:
                self._redistribute(pending, active)
            self._emit_progress()
            if self._state.all_done():
                self._finish()
        else:
            self._roster.remove(worker_id)
            self._emit_lobby()
            self._emit_progress()

    def _redistribute(self, pending: List[int], active: List[int]) -> None:
        """Reparte el trabajo pendiente y reactiva a los trabajadores ociosos."""
        self._state.redistribute(pending, active)
        # Quien estaba ocioso (terminó su shard) retoma trabajo de inmediato.
        for worker_id in active:
            if self._state.is_idle(worker_id) and self._state.has_pending(worker_id):
                self._serve_next(worker_id)

    # ------------------------------------------------------------------ #
    # Transición de fase: arranque del etiquetado
    # ------------------------------------------------------------------ #
    def start_labeling(self, seed: Optional[int] = None) -> None:
        """
        Reparte el dataset entre los trabajadores activos y arranca la fase.

        Args:
            seed: Semilla del barajado; si es ``None`` se genera una aleatoria.
        """
        if self._phase is not SessionPhase.LOBBY:
            return
        worker_ids = self._active_worker_ids()
        if seed is None:
            seed = int.from_bytes(np.random.bytes(4), "little")

        image_ids = list(range(len(self._images)))
        shards = ShardPlanner.plan(image_ids, worker_ids, seed)
        self._state.set_shards(shards)
        self._phase = SessionPhase.LABELING
        self.phaseChanged.emit(self._phase.value)
        self._emit_progress()

        for worker_id in worker_ids:
            if worker_id == HOST_ID:
                continue
            count = self._state.progress_of(worker_id).assigned
            self.messageForWorker.emit(
                worker_id, protocol.build_assignment(count, len(self._images))
            )
        # Sirve la primera imagen a cada trabajador (incluido el Host).
        for worker_id in worker_ids:
            self._serve_next(worker_id)

    # ------------------------------------------------------------------ #
    # Servicio de imágenes y consolidación
    # ------------------------------------------------------------------ #
    def request_next(self, worker_id: int) -> None:
        """Atiende la petición de la siguiente imagen de un trabajador remoto."""
        if self._phase is SessionPhase.LABELING:
            self._serve_next(worker_id)

    def submit(
        self, worker_id: int, image_id: int, labels: Optional[List[Optional[str]]]
    ) -> None:
        """
        Consolida las etiquetas de una imagen y avanza al trabajador.

        Args:
            worker_id: Trabajador que confirma la imagen.
            image_id: Índice global de la imagen confirmada (debe estar en vuelo).
            labels: Vector de etiquetas recibido del remoto; ``None`` si el Host
                ya etiquetó los parches en memoria (trabajador local).
        """
        # Seguridad: un trabajador solo puede confirmar SU imagen en vuelo.
        if self._state.in_flight_of(worker_id) != image_id:
            return
        patches = self._cache.get(image_id)
        if patches is None:
            return  # Imagen desconocida o ya consolidada: se ignora.
        if labels is not None:
            for index, patch in enumerate(patches):
                patch.label = labels[index] if index < len(labels) else None

        classified = [patch for patch in patches if patch.is_classified]
        if classified:
            self._pending_saves += 1
            self._requestSave.emit(self._images[image_id].stem, classified)
        self._cache.pop(image_id, None)
        self._complete_and_advance(worker_id, image_id)

    def _serve_next(self, worker_id: int) -> None:
        """Toma la siguiente imagen del shard y lanza su extracción."""
        if not self._state.is_idle(worker_id):
            return  # Ya tiene una imagen en vuelo: ignora peticiones duplicadas.
        image_id = self._state.next_image(worker_id)
        if image_id is None:
            self._on_worker_drained(worker_id)
            return
        self._pending_extraction[image_id] = worker_id
        self._requestExtraction.emit(image_id)

    def _complete_and_advance(self, worker_id: int, image_id: int) -> None:
        """Contabiliza la imagen, difunde progreso y sirve la siguiente."""
        if not self._state.complete(worker_id, image_id):
            return
        self._emit_progress()
        if self._state.all_done():
            self._finish()
            return
        self._serve_next(worker_id)

    def _on_worker_drained(self, worker_id: int) -> None:
        """Un trabajador agotó su cola: queda a la espera de más trabajo."""
        if worker_id == HOST_ID:
            self.local.notify_shard_done()
        else:
            self.messageForWorker.emit(worker_id, protocol.build_shard_done())

    # ------------------------------------------------------------------ #
    # Reacciones del hilo de extracción/guardado
    # ------------------------------------------------------------------ #
    def _on_patches_ready(
        self, index: int, path: str, image: np.ndarray, patches: List[Patch]
    ) -> None:
        """Entrega la imagen extraída al trabajador que la solicitó."""
        worker_id = self._pending_extraction.pop(index, None)
        if worker_id is None:
            return
        self._cache[index] = patches
        prog = self._state.progress_of(worker_id)
        position = prog.completed + 1
        if worker_id == HOST_ID:
            self.local.present(image, patches, index, Path(path).name, position, prog.assigned)
        else:
            self.messageForWorker.emit(
                worker_id, self._image_message(image, patches, index, path, position, prog.assigned)
            )

    def _on_image_unusable(self, index: int, _path: str) -> None:
        """Imagen ilegible o sin parches: se cuenta como completada y se avanza."""
        worker_id = self._pending_extraction.pop(index, None)
        if worker_id is not None:
            self._complete_and_advance(worker_id, index)

    def _on_extraction_failed(self, index: int, _path: str, _message: str) -> None:
        """Fallo de extracción: se trata como imagen inutilizable."""
        self._on_image_unusable(index, _path)

    def _on_saved(self, count: int, rows: object) -> None:
        """Confirma en el CSV (hilo principal) las filas del último guardado."""
        self._pending_saves -= 1
        if not self._repo_closed:
            self._repository.append_rows(rows)  # type: ignore[arg-type]
            self._saved_total += count
        if self._finish_requested:
            self._maybe_finalize()

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def _finish(self) -> None:
        """Solicita finalizar; el cierre real se difiere hasta drenar guardados."""
        if self._finish_requested or self._phase is SessionPhase.FINISHED:
            return
        self._finish_requested = True
        self._maybe_finalize()

    def _maybe_finalize(self) -> None:
        """Finaliza de verdad solo cuando no quedan guardados en vuelo."""
        if self._pending_saves > 0 or self._phase is SessionPhase.FINISHED:
            return
        self._phase = SessionPhase.FINISHED
        self._repository.close()
        self._repo_closed = True
        self.phaseChanged.emit(self._phase.value)
        self.finished.emit(
            f"Sesión finalizada. {self._saved_total} parches consolidados en:\n"
            f"{self._repository.output_dir}"
        )

    def shutdown(self) -> None:
        """Detiene el hilo secundario y cierra el repositorio de forma ordenada."""
        if not self._repo_closed:
            self._repository.close()
            self._repo_closed = True
        self._thread.quit()
        self._thread.wait()

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _active_worker_ids(self) -> List[int]:
        """Identificadores de los trabajadores conectados (Host primero)."""
        return [w for w in sorted(self._connected) if self._connected[w]]

    def _emit_lobby(self) -> None:
        """Difunde el estado del lobby a la ventana y a los clientes."""
        self.lobbyChanged.emit(self.participants())

    def _emit_progress(self) -> None:
        """Difunde el progreso a la ventana y a los clientes."""
        self.progressChanged.emit(self.progress_payload())

    def _image_message(
        self,
        image: np.ndarray,
        patches: List[Patch],
        index: int,
        path: str,
        position: int,
        shard_total: int,
    ) -> dict:
        """Construye el mensaje ``image`` con la imagen codificada en JPEG."""
        ok, buffer = cv2.imencode(
            ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
        )
        jpeg_b64 = base64.b64encode(buffer).decode("ascii") if ok else ""
        height, width = image.shape[:2]
        cells = [(patch.x, patch.y, patch.w, patch.h) for patch in patches]
        # Sugerencias del clasificador como etiquetas iniciales del colaborador.
        # Se omiten si no hay ninguna, para no engordar el mensaje.
        suggestions = [patch.suggested_label for patch in patches]
        if not any(suggestions):
            suggestions = None
        return protocol.build_image(
            index=index,
            file_name=Path(path).name,
            width=width,
            height=height,
            jpeg_b64=jpeg_b64,
            cells=cells,
            position=position,
            shard_total=shard_total,
            suggestions=suggestions,
        )


class LocalWorker(QObject):
    """
    Fachada de trabajador para el **Host** (implementa ``GridControllerLike``).

    Permite que el Host etiquete su propio shard reutilizando ``GridWindow`` sin
    cambios: traduce los clics en operaciones sobre un :class:`GridSession` y, al
    confirmar, delega la consolidación en el :class:`SessionCoordinator`.
    """

    gridReady = Signal(object)
    overlayChanged = Signal()
    activeClassChanged = Signal(str)
    historyChanged = Signal(bool, bool)
    statusMessage = Signal(str)
    busyChanged = Signal(bool)
    finished = Signal(str)

    def __init__(self, coordinator: SessionCoordinator, labels: List[str]) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._labels = labels
        self._active_class = labels[0]
        self._session: Optional[GridSession] = None
        self._image_id: Optional[int] = None

    # -- API consumida por GridWindow ------------------------------------- #
    @property
    def active_class(self) -> str:
        """Clase activa local para pintar."""
        return self._active_class

    def set_active_class(self, label: str) -> None:
        """Fija la clase activa (selección "sticky")."""
        if label in self._labels and label != self._active_class:
            self._active_class = label
            self.activeClassChanged.emit(label)

    def cycle_active_class(self) -> None:
        """Alterna a la siguiente clase de la lista."""
        current = self._labels.index(self._active_class)
        self.set_active_class(self._labels[(current + 1) % len(self._labels)])

    def paint_cell(self, index: int) -> None:
        """Aplica la clase activa a una celda."""
        if self._session is not None and self._session.paint(index, self._active_class):
            self._after_edit()

    def clear_cell(self, index: int) -> None:
        """Limpia la etiqueta de una celda."""
        if self._session is not None and self._session.clear(index):
            self._after_edit()

    def fill_remaining(self, label: Optional[str] = None) -> None:
        """Etiqueta todas las celdas restantes con la clase indicada o activa."""
        if self._session is None:
            return
        target = label or self._active_class
        if self._session.fill_remaining(target):
            self.statusMessage.emit(f"Celdas restantes rellenadas con «{target}».")
            self._after_edit()

    def undo(self) -> None:
        """Deshace la última acción sobre la cuadrícula."""
        if self._session is not None and self._session.undo():
            self._after_edit()

    def redo(self) -> None:
        """Rehace la última acción deshecha."""
        if self._session is not None and self._session.redo():
            self._after_edit()

    def confirm_and_next(self) -> None:
        """Consolida la imagen actual del Host y solicita la siguiente."""
        if self._session is None or self._image_id is None:
            return
        image_id = self._image_id
        self._session = None
        self._image_id = None
        self.statusMessage.emit("Consolidando…")
        self._coordinator.submit(HOST_ID, image_id, None)

    def quit(self) -> None:
        """Finaliza la sesión completa desde el Host."""
        self._coordinator._finish()  # noqa: SLF001 — colaboración estrecha.

    def shutdown(self) -> None:
        """Detiene el coordinador al cerrar la ventana."""
        self._coordinator.shutdown()

    # -- Llamadas desde el coordinador ------------------------------------ #
    def present(
        self,
        image: np.ndarray,
        patches: List[Patch],
        image_id: int,
        file_name: str,
        position: int,
        shard_total: int,
    ) -> None:
        """Carga una nueva imagen del shard del Host en el lienzo."""
        self._session = GridSession(patches)
        self._image_id = image_id
        # Pre-pinta las celdas con las sugerencias del clasificador (si las hay);
        # son el estado de partida, así que «deshacer» no las elimina.
        prefilled = self._session.prefill_suggestions()
        self.gridReady.emit(
            GridFrame(
                image=image,
                session=self._session,
                file_name=file_name,
                image_index=position - 1,
                image_total=shard_total,
            )
        )
        self.historyChanged.emit(False, False)
        base = f"Imagen «{file_name}» ({position}/{shard_total})."
        if prefilled:
            base += f" {prefilled} celdas pre-etiquetadas; revisa y corrige."
        self.statusMessage.emit(base)

    def notify_shard_done(self) -> None:
        """El Host agotó su porción; queda a la espera de posibles reasignaciones."""
        self._session = None
        self._image_id = None
        self.statusMessage.emit("Has completado tu porción. Esperando…")

    # -- Internos --------------------------------------------------------- #
    def _after_edit(self) -> None:
        """Notifica a la vista tras un cambio en la cuadrícula."""
        self.overlayChanged.emit()
        if self._session is not None:
            self.historyChanged.emit(
                self._session.can_undo, self._session.can_redo
            )
