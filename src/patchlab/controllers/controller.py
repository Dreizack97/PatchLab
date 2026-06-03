"""Controlador principal del flujo de etiquetado.

Mantiene el estado de la sesión (imagen actual, parche actual, historial),
traduce las acciones del usuario en operaciones de persistencia y notifica a la
vista qué mostrar mediante señales. No contiene ningún widget: la vista observa
sus señales y le reenvía las intenciones del usuario.

Semántica de transacción (heredada del script original): los parches se guardan
en disco de inmediato, pero las filas del CSV se confirman al completar cada
imagen. Deshacer opera dentro de la imagen en curso.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from patchlab.controllers.worker import ExtractionWorker
from patchlab.models.config import LabelerConfig
from patchlab.models.patch import SKIP, Patch
from patchlab.models.repository import DatasetRepository
from patchlab.services.extractor import create_extractor
from patchlab.services.renderer import render_context


@dataclass
class FrameData:
    """Instantánea inmutable de lo que la vista debe pintar en un momento dado."""

    patch_image: np.ndarray   # Recorte BGR a mostrar (panel izquierdo).
    context_image: np.ndarray  # Imagen BGR anotada (panel derecho).
    file_name: str
    patch_index: int           # Índice del parche (base 0) en la imagen.
    patch_total: int           # Número de parches de la imagen actual.
    image_index: int           # Índice de la imagen (base 0).
    image_total: int           # Número total de imágenes.


class LabelingController(QObject):
    """Orquesta el etiquetado imagen por imagen y parche por parche."""

    #: Nuevo fotograma listo para mostrarse.
    frameReady = Signal(object)            # FrameData
    #: Mensaje breve de estado (carga, avisos, etc.).
    statusMessage = Signal(str)
    #: Toda la sesión finalizó; lleva un pequeño resumen como texto.
    finished = Signal(str)
    #: Solicitud interna de extracción dirigida al worker (índice de imagen).
    _requestExtraction = Signal(int)

    def __init__(
        self, config: LabelerConfig, images: List[Path]
    ) -> None:
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
        self._patches: List[Patch] = []
        self._patch_index = 0
        self._classified_count = 0

        self._configure_worker()

    # ------------------------------------------------------------------ #
    # Configuración del hilo de extracción
    # ------------------------------------------------------------------ #
    def _configure_worker(self) -> None:
        """Crea el worker y lo mueve a un ``QThread`` dedicado."""
        self._thread = QThread()
        self._worker = ExtractionWorker(
            self._images, create_extractor(self._config)
        )
        self._worker.moveToThread(self._thread)

        self._requestExtraction.connect(self._worker.extract)
        self._worker.patchesReady.connect(self._on_patches_ready)
        self._worker.imageSkipped.connect(self._on_image_skipped)
        self._worker.extractionFailed.connect(self._on_extraction_failed)

        self._thread.start()

    # ------------------------------------------------------------------ #
    # API pública: intenciones del usuario
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Inicia la sesión solicitando la extracción de la primera imagen."""
        self._advance_to_next_image()

    def apply_label(self, label: str) -> None:
        """
        Asigna una etiqueta de clase al parche actual y guarda el recorte.

        Args:
            label: Etiqueta de clase (debe pertenecer a la configuración).
        """
        if not self._patches:
            return
        patch = self._patches[self._patch_index]
        patch.label = label
        self._repository.save_patch(patch, self._image_path.stem)  # type: ignore[union-attr]
        self._classified_count += 1
        self._advance_patch()

    def skip(self) -> None:
        """Marca el parche actual como omitido (no se guarda en disco)."""
        if not self._patches:
            return
        self._patches[self._patch_index].label = SKIP
        self._advance_patch()

    def undo(self) -> None:
        """Retrocede al parche anterior, revirtiendo su guardado si lo hubo."""
        if self._patch_index == 0:
            self.statusMessage.emit(
                "No puedes deshacer más: estás en el primer parche."
            )
            return

        self._patch_index -= 1
        previous = self._patches[self._patch_index]
        if previous.is_classified:
            self._classified_count -= 1
        self._repository.discard_patch(previous)
        previous.label = None
        self._emit_current_frame()

    def quit(self) -> None:
        """Finaliza la sesión confirmando lo pendiente de la imagen actual."""
        self._repository.commit_image()
        self._finish()

    def shutdown(self) -> None:
        """Detiene el hilo de extracción de forma ordenada."""
        self._thread.quit()
        self._thread.wait()

    # ------------------------------------------------------------------ #
    # Avance de estado
    # ------------------------------------------------------------------ #
    def _advance_patch(self) -> None:
        """Pasa al siguiente parche o, si se agotaron, a la siguiente imagen."""
        self._patch_index += 1
        if self._patch_index >= len(self._patches):
            self._repository.commit_image()
            self._advance_to_next_image()
        else:
            self._emit_current_frame()

    def _advance_to_next_image(self) -> None:
        """Solicita al worker la extracción de la próxima imagen disponible."""
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

    def _finish(self) -> None:
        """Cierra el repositorio y notifica el fin de la sesión."""
        self._repository.close()
        self.finished.emit(
            f"Sesión finalizada. {self._classified_count} parches "
            f"guardados en:\n{self._repository.output_dir}"
        )

    # ------------------------------------------------------------------ #
    # Reacciones a las señales del worker
    # ------------------------------------------------------------------ #
    def _on_patches_ready(
        self,
        index: int,
        path: str,
        image: np.ndarray,
        patches: List[Patch],
    ) -> None:
        """Recibe los parches de una imagen y comienza a etiquetarla."""
        self._image = image
        self._image_path = Path(path)
        self._patches = patches
        self._patch_index = 0
        self._emit_current_frame()

    def _on_image_skipped(self, index: int, path: str) -> None:
        """Salta imágenes ilegibles o sin parches y continúa."""
        self.statusMessage.emit(f"Omitiendo {Path(path).name} (sin parches).")
        self._advance_to_next_image()

    def _on_extraction_failed(
        self, index: int, path: str, message: str
    ) -> None:
        """Informa de un fallo de extracción y continúa con la siguiente."""
        self.statusMessage.emit(
            f"Error procesando {Path(path).name}: {message}"
        )
        self._advance_to_next_image()

    # ------------------------------------------------------------------ #
    # Emisión de fotogramas hacia la vista
    # ------------------------------------------------------------------ #
    def _emit_current_frame(self) -> None:
        """Construye y emite el :class:`FrameData` del estado actual."""
        if self._image is None or not self._patches:
            return
        patch = self._patches[self._patch_index]
        context = render_context(self._image, self._patches, self._patch_index)
        self.frameReady.emit(
            FrameData(
                patch_image=patch.display_image,
                context_image=context,
                file_name=self._image_path.name,  # type: ignore[union-attr]
                patch_index=self._patch_index,
                patch_total=len(self._patches),
                image_index=self._image_index,
                image_total=len(self._images),
            )
        )
