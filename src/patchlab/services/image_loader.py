"""Descubrimiento de imágenes de entrada en el sistema de archivos."""

from __future__ import annotations

from pathlib import Path
from typing import List

# Extensiones de imagen admitidas (en minúsculas, con punto inicial).
VALID_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp"})


def find_images(input_dir: Path) -> List[Path]:
    """
    Localiza recursivamente todas las imágenes válidas bajo un directorio.

    Args:
        input_dir: Directorio raíz donde buscar.

    Returns:
        Lista ordenada (determinista) de rutas a imágenes admitidas.
    """
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VALID_EXTENSIONS
    )
