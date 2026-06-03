"""Worker que persiste en disco los parches etiquetados de una imagen.

El guardado por lotes (potencialmente cientos o miles de archivos en una
cuadrícula grande) se ejecuta en un hilo secundario para que la interfaz no se
congele. Solo escribe los archivos de imagen; la confirmación ligera de los
metadatos (CSV) la realiza el controlador en el hilo principal.
"""

from __future__ import annotations

from typing import List

import cv2
from PySide6.QtCore import QObject, Signal, Slot

from patchlab.models.patch import Patch
from patchlab.models.repository import DatasetRepository


class GridSaveWorker(QObject):
    """Escribe en disco los recortes clasificados de una imagen."""

    #: Emitida con (nº guardados, filas_csv) al terminar el lote.
    saved = Signal(int, object)

    def __init__(self, repository: DatasetRepository) -> None:
        """
        Args:
            repository: Repositorio que conoce rutas y convención de nombres.
        """
        super().__init__()
        self._repository = repository

    @Slot(str, object)
    def save(self, image_stem: str, patches: List[Patch]) -> None:
        """
        Guarda cada parche en su carpeta de clase y reúne sus filas de metadatos.

        Args:
            image_stem: Nombre base de la imagen de origen (sin extensión).
            patches: Parches con etiqueta de clase a guardar.
        """
        rows: List[List[object]] = []
        for patch in patches:
            directory = self._repository.prepare_label_dir(patch.label)  # type: ignore[arg-type]
            file_name = self._repository.build_filename(patch, image_stem)
            out_path = directory / file_name
            cv2.imwrite(str(out_path), patch.display_image)
            patch.saved_path = out_path
            rows.append([file_name, patch.index, patch.label])

        self.saved.emit(len(rows), rows)
