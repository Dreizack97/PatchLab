"""Worker de extracción que se ejecuta en un hilo secundario.

Aísla las operaciones costosas (lectura de imagen desde disco e inferencia de
YOLO) del hilo de la interfaz, manteniendo la GUI fluida. Se comunica con el
controlador exclusivamente mediante señales Qt, que son seguras entre hilos.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import cv2
from PySide6.QtCore import QObject, Signal, Slot

from patchlab.services.extractor import PatchExtractor


class ExtractionWorker(QObject):
    """Extrae parches de una imagen bajo demanda dentro de su propio hilo."""

    #: Emitida con (índice, ruta, imagen_bgr, lista[Patch]) al haber parches.
    patchesReady = Signal(int, str, object, object)
    #: Emitida con (índice, ruta) si la imagen es ilegible o no genera parches.
    imageSkipped = Signal(int, str)
    #: Emitida con (índice, ruta, mensaje) ante un error de extracción.
    extractionFailed = Signal(int, str, str)

    def __init__(
        self, images: List[Path], extractor: PatchExtractor
    ) -> None:
        """
        Args:
            images: Lista completa de rutas de imágenes de la sesión.
            extractor: Estrategia de extracción a aplicar.
        """
        super().__init__()
        self._images = images
        self._extractor = extractor

    @Slot(int)
    def extract(self, index: int) -> None:
        """
        Procesa la imagen ``index`` y emite el resultado correspondiente.

        Args:
            index: Posición de la imagen dentro de ``self._images``.
        """
        path = self._images[index]
        image = cv2.imread(str(path))
        if image is None:
            self.imageSkipped.emit(index, str(path))
            return

        try:
            patches = self._extractor.extract(image)
        except Exception as exc:  # noqa: BLE001 — se reporta a la UI.
            self.extractionFailed.emit(index, str(path), str(exc))
            return

        if not patches:
            self.imageSkipped.emit(index, str(path))
            return

        self.patchesReady.emit(index, str(path), image, patches)
