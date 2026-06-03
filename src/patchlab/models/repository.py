"""Persistencia del dataset etiquetado: archivos de imagen y ``metadata.csv``.

Encapsula todo el acceso a disco para que el controlador permanezca agnóstico
del almacenamiento. Las filas del CSV se acumulan por imagen y se confirman
(``commit_image``) cuando se termina la imagen actual, replicando la semántica
transaccional del script original y permitiendo deshacer de forma segura.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional, Tuple

import cv2

from patchlab.models.patch import SKIP, Patch

# Cabecera del archivo de metadatos.
_CSV_HEADER: Tuple[str, str, str] = ("file", "patch_idx", "label")


class DatasetRepository:
    """
    Gestiona el guardado de parches en carpetas por clase y el ``metadata.csv``.

    El repositorio abre el CSV en modo *append* si ya existe (continuando una
    sesión previa) o lo crea con su cabecera en caso contrario.
    """

    def __init__(self, output_dir: Path) -> None:
        """
        Args:
            output_dir: Directorio raíz del dataset de salida.
        """
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._csv_path = output_dir / "metadata.csv"
        write_header = not self._csv_path.exists()
        # ``newline=""`` evita líneas en blanco espurias en Windows.
        self._csv_file = self._csv_path.open(
            "a", newline="", encoding="utf-8"
        )
        self._writer = csv.writer(self._csv_file)
        if write_header:
            self._writer.writerow(_CSV_HEADER)
            self._csv_file.flush()

        # Filas pendientes de confirmar para la imagen en curso.
        self._pending_rows: List[List[object]] = []

    @property
    def output_dir(self) -> Path:
        """Directorio raíz del dataset de salida."""
        return self._output_dir

    def save_patch(self, patch: Patch, image_stem: str) -> Path:
        """
        Guarda el parche en ``output_dir/<label>/`` y registra su fila pendiente.

        Args:
            patch: Parche ya etiquetado con una clase real (no ``SKIP``).
            image_stem: Nombre base de la imagen de origen (sin extensión).

        Returns:
            Ruta del archivo de imagen escrito en disco.

        Raises:
            ValueError: Si el parche no tiene una etiqueta de clase válida.
        """
        if not patch.is_classified:
            raise ValueError("Solo se guardan parches con etiqueta de clase.")

        label_dir = self.prepare_label_dir(patch.label)  # type: ignore[arg-type]
        file_name = self.build_filename(patch, image_stem)
        out_path = label_dir / file_name
        cv2.imwrite(str(out_path), patch.display_image)

        patch.saved_path = out_path
        self._pending_rows.append([file_name, patch.index, patch.label])
        return out_path

    def prepare_label_dir(self, label: str) -> Path:
        """
        Crea (si hace falta) y devuelve la carpeta de la clase ``label``.

        Seguro de invocar desde un hilo trabajador durante un guardado por lotes.

        Args:
            label: Nombre de la clase.

        Returns:
            Ruta a ``output_dir/<label>/``.
        """
        label_dir = self._output_dir / label
        label_dir.mkdir(parents=True, exist_ok=True)
        return label_dir

    @staticmethod
    def build_filename(patch: Patch, image_stem: str) -> str:
        """
        Construye el nombre de archivo canónico de un parche.

        Args:
            patch: Parche de origen.
            image_stem: Nombre base de la imagen (sin extensión).

        Returns:
            Nombre de archivo ``<stem>_<tipo>_p<idx>.jpg``.
        """
        return f"{image_stem}_{patch.source_type}_p{patch.index}.jpg"

    def append_rows(self, rows: List[List[object]]) -> None:
        """
        Escribe y vuelca un lote de filas en el ``metadata.csv``.

        Pensado para el flujo por clic: el guardado de imágenes ocurre en un
        hilo aparte y esta confirmación de metadatos se realiza en el hilo
        principal tras completarse.

        Args:
            rows: Filas ``[file, patch_idx, label]`` a añadir.
        """
        if not rows:
            return
        self._writer.writerows(rows)
        self._csv_file.flush()

    def discard_patch(self, patch: Patch) -> None:
        """
        Revierte el guardado de un parche (operación *deshacer*).

        Elimina el archivo de disco si existe y descarta su fila pendiente.

        Args:
            patch: Parche cuyo guardado debe revertirse.
        """
        if patch.saved_path is not None and patch.saved_path.exists():
            patch.saved_path.unlink()
        if patch.is_classified and self._pending_rows:
            self._pending_rows.pop()
        patch.saved_path = None

    def commit_image(self) -> None:
        """Vuelca al CSV las filas acumuladas de la imagen actual."""
        if not self._pending_rows:
            return
        self._writer.writerows(self._pending_rows)
        self._csv_file.flush()
        self._pending_rows.clear()

    def close(self) -> None:
        """Confirma lo pendiente y cierra el archivo CSV de forma segura."""
        self.commit_image()
        if not self._csv_file.closed:
            self._csv_file.close()
