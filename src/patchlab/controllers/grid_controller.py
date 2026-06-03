"""Controlador del flujo de etiquetado por clic (cuadrícula interactiva).

Mantiene el estado de la sesión (imagen e historial activos, clase "fija"),
traduce las intenciones del usuario en operaciones del :class:`GridSession`
(Modelo) y notifica a la vista mediante señales. El trabajo pesado —lectura de
imágenes, inferencia de YOLO y guardado por lotes— se delega a workers que
viven en un hilo secundario, de modo que la interfaz permanece fluida.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from patchlab.controllers.save_worker import GridSaveWorker
from patchlab.controllers.worker import ExtractionWorker
from patchlab.models.config import LabelerConfig
from patchlab.models.grid_session import GridSession
from patchlab.models.repository import DatasetRepository
from patchlab.services.extractor import create_extractor


@dataclass
class GridFrame:
    """Datos de una imagen recién cargada para que la vista la pinte."""

    image: np.ndarray       # Imagen BGR original (fondo de la cuadrícula).
    session: GridSession    # Estado editable de las celdas.
    file_name: str
    image_index: int        # Índice de la imagen (base 0).
    image_total: int        # Número total de imágenes.


class GridController(QObject):
    """Orquesta el etiquetado por clic imagen a imagen."""

    #: Nueva imagen lista para etiquetar.
    gridReady = Signal(object)              # GridFrame
    #: El estado de las celdas cambió; la vista debe repintar el overlay.
    overlayChanged = Signal()
    #: Cambió la clase activa ("fija").
    activeClassChanged = Signal(str)
    #: Cambió la disponibilidad de deshacer/rehacer (can_undo, can_redo).
    historyChanged = Signal(bool, bool)
    #: Mensaje breve de estado.
    statusMessage = Signal(str)
    #: La app está ocupada guardando (para bloquear la interacción).
    busyChanged = Signal(bool)
    #: La sesión finalizó; lleva un resumen como texto.
    finished = Signal(str)

    #: Señales internas hacia los workers del hilo secundario.
    _requestExtraction = Signal(int)
    _requestSave = Signal(str, object)

    def __init__(self, config: LabelerConfig, images: List[Path]) -> None:
        """
        Args:
            config: Configuración validada de la sesión.
            images: Lista no vacía de imágenes a procesar.
        """
        super().__init__()
        self._config = config
        self._images = images
        self._repository = DatasetRepository(config.output_dir)

        # Estado de la sesión.
        self._image_index = -1
        self._image: Optional[np.ndarray] = None
        self._image_path: Optional[Path] = None
        self._session: Optional[GridSession] = None
        self._active_class = config.labels[0]
        self._saved_total = 0

        self._configure_workers()

    # ------------------------------------------------------------------ #
    # Configuración del hilo secundario
    # ------------------------------------------------------------------ #
    def _configure_workers(self) -> None:
        """Crea los workers de extracción y guardado en un hilo dedicado."""
        self._thread = QThread()
        self._extraction_worker = ExtractionWorker(
            self._images, create_extractor(self._config)
        )
        self._save_worker = GridSaveWorker(self._repository)
        self._extraction_worker.moveToThread(self._thread)
        self._save_worker.moveToThread(self._thread)

        self._requestExtraction.connect(self._extraction_worker.extract)
        self._requestSave.connect(self._save_worker.save)
        self._extraction_worker.patchesReady.connect(self._on_patches_ready)
        self._extraction_worker.imageSkipped.connect(self._on_image_skipped)
        self._extraction_worker.extractionFailed.connect(self._on_extraction_failed)
        self._save_worker.saved.connect(self._on_saved)

        self._thread.start()

    # ------------------------------------------------------------------ #
    # Estado expuesto
    # ------------------------------------------------------------------ #
    @property
    def active_class(self) -> str:
        """Clase actualmente "fija" para el modo pintar."""
        return self._active_class

    # ------------------------------------------------------------------ #
    # API pública: intenciones del usuario
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Inicia la sesión cargando la primera imagen."""
        self._advance_to_next_image()

    def set_active_class(self, label: str) -> None:
        """Fija la clase activa (selección "sticky" para pintar)."""
        if label in self._config.labels and label != self._active_class:
            self._active_class = label
            self.activeClassChanged.emit(label)

    def cycle_active_class(self) -> None:
        """Alterna a la siguiente clase de la lista (atajo de teclado)."""
        labels = self._config.labels
        current = labels.index(self._active_class)
        self.set_active_class(labels[(current + 1) % len(labels)])

    def paint_cell(self, index: int) -> None:
        """Aplica la clase activa a la celda ``index`` (clic izquierdo)."""
        if self._session is not None and self._session.paint(index, self._active_class):
            self._after_edit()

    def clear_cell(self, index: int) -> None:
        """Limpia la etiqueta de la celda ``index`` (clic derecho)."""
        if self._session is not None and self._session.clear(index):
            self._after_edit()

    def fill_remaining(self, label: Optional[str] = None) -> None:
        """
        Etiqueta todas las celdas restantes con ``label`` (o la clase activa).

        Args:
            label: Clase a aplicar; si es ``None`` se usa la clase activa.
        """
        if self._session is None:
            return
        target = label or self._active_class
        affected = self._session.fill_remaining(target)
        if affected:
            self.statusMessage.emit(
                f"{affected} celdas rellenadas con «{target}»."
            )
            self._after_edit()
        else:
            self.statusMessage.emit("No quedan celdas por rellenar.")

    def undo(self) -> None:
        """Deshace la última acción sobre la cuadrícula."""
        if self._session is not None and self._session.undo():
            self._after_edit()

    def redo(self) -> None:
        """Rehace la última acción deshecha."""
        if self._session is not None and self._session.redo():
            self._after_edit()

    def confirm_and_next(self) -> None:
        """Guarda las celdas etiquetadas y avanza a la siguiente imagen."""
        if self._session is None:
            return
        classified = self._session.classified_patches()
        if not classified:
            self._advance_to_next_image()
            return
        self.busyChanged.emit(True)
        self.statusMessage.emit("Guardando…")
        self._requestSave.emit(self._image_path.stem, classified)  # type: ignore[union-attr]

    def quit(self) -> None:
        """Finaliza la sesión sin guardar la imagen en curso."""
        self._finish()

    def shutdown(self) -> None:
        """Detiene el hilo secundario de forma ordenada."""
        self._thread.quit()
        self._thread.wait()

    # ------------------------------------------------------------------ #
    # Reacciones a los workers
    # ------------------------------------------------------------------ #
    def _on_patches_ready(
        self,
        index: int,
        path: str,
        image: np.ndarray,
        patches: List,
    ) -> None:
        """Construye una sesión de cuadrícula para la imagen recibida."""
        self._image = image
        self._image_path = Path(path)
        self._session = GridSession(patches)
        self.gridReady.emit(
            GridFrame(
                image=image,
                session=self._session,
                file_name=self._image_path.name,
                image_index=self._image_index,
                image_total=len(self._images),
            )
        )
        self.historyChanged.emit(False, False)
        self._emit_status_counts()

    def _on_image_skipped(self, index: int, path: str) -> None:
        """Salta imágenes ilegibles o sin parches."""
        self.statusMessage.emit(f"Omitiendo {Path(path).name} (sin parches).")
        self._advance_to_next_image()

    def _on_extraction_failed(self, index: int, path: str, message: str) -> None:
        """Informa de un fallo de extracción y continúa."""
        self.statusMessage.emit(
            f"Error procesando {Path(path).name}: {message}"
        )
        self._advance_to_next_image()

    def _on_saved(self, count: int, rows: object) -> None:
        """Confirma los metadatos en el hilo principal y avanza."""
        self._repository.append_rows(rows)  # type: ignore[arg-type]
        self._saved_total += count
        self.busyChanged.emit(False)
        self._advance_to_next_image()

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #
    def _advance_to_next_image(self) -> None:
        """Solicita la extracción de la próxima imagen disponible."""
        self._image_index += 1
        if self._image_index >= len(self._images):
            self._finish()
            return
        next_path = self._images[self._image_index]
        self.statusMessage.emit(
            f"Cargando {next_path.name} "
            f"({self._image_index + 1}/{len(self._images)})…"
        )
        self._requestExtraction.emit(self._image_index)

    def _after_edit(self) -> None:
        """Notifica a la vista tras cualquier cambio en la cuadrícula."""
        self.overlayChanged.emit()
        self.historyChanged.emit(self._session.can_undo, self._session.can_redo)  # type: ignore[union-attr]
        self._emit_status_counts()

    def _emit_status_counts(self) -> None:
        """Emite un mensaje con el progreso de celdas de la imagen actual."""
        if self._session is None:
            return
        self.statusMessage.emit(
            f"Etiquetadas {self._session.labeled_count} de "
            f"{self._session.total} celdas "
            f"({self._session.remaining_count} restantes)."
        )

    def _finish(self) -> None:
        """Cierra el repositorio y notifica el fin de la sesión."""
        self._repository.close()
        self.finished.emit(
            f"Sesión finalizada. {self._saved_total} parches "
            f"guardados en:\n{self._repository.output_dir}"
        )
