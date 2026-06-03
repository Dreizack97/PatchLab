"""Extracción de parches a partir de una imagen.

Define dos estrategias intercambiables que comparten la interfaz
:class:`PatchExtractor`:

- :class:`GridPatchExtractor`: recorta una cuadrícula regular sobre toda la
  imagen (modo "ciego", sin modelo).
- :class:`YoloPatchExtractor`: recorta solo dentro de las regiones segmentadas
  por un modelo YOLO, aplicando la máscara a cada parche.

La importación de ``ultralytics``/``torch`` es perezosa: solo ocurre cuando se
instancia realmente el extractor YOLO, de modo que el modo cuadrícula no arrastra
dependencias pesadas de deep learning.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Protocol

import cv2
import numpy as np

from patchlab.models.config import LabelerConfig
from patchlab.models.patch import Patch
from patchlab.services.geometry import build_crop_and_mask

# Fracción mínima de píxeles de máscara para aceptar un parche YOLO.
_MIN_MASK_RATIO = 0.5


class PatchExtractor(Protocol):
    """Contrato común de todas las estrategias de extracción de parches."""

    mode_name: str

    def extract(self, image: np.ndarray) -> List[Patch]:
        """Devuelve los parches extraídos de una imagen BGR."""
        ...


class GridPatchExtractor:
    """Extrae parches cuadrados recorriendo la imagen en cuadrícula regular."""

    mode_name = "Cuadrícula"

    def __init__(self, patch_size: int) -> None:
        """
        Args:
            patch_size: Lado en píxeles de cada parche cuadrado.
        """
        self._patch_size = patch_size

    def extract(self, image: np.ndarray) -> List[Patch]:
        """
        Recorta una cuadrícula no solapada de parches sobre toda la imagen.

        Args:
            image: Imagen BGR de origen.

        Returns:
            Lista de parches en orden de lectura (izquierda→derecha, arriba→abajo).
        """
        height, width = image.shape[:2]
        size = self._patch_size
        patches: List[Patch] = []
        counter = 0

        for top in range(0, height - size + 1, size):
            for left in range(0, width - size + 1, size):
                crop = image[top:top + size, left:left + size]
                patches.append(
                    Patch(
                        index=counter,
                        source_type="grid",
                        x=left,
                        y=top,
                        w=size,
                        h=size,
                        original=crop.copy(),
                    )
                )
                counter += 1
        return patches


class YoloPatchExtractor:
    """Extrae parches restringidos a las máscaras de segmentación de YOLO."""

    mode_name = "Parches YOLO"

    def __init__(
        self, model_path: Path, patch_size: int, padding_pct: float
    ) -> None:
        """
        Args:
            model_path: Ruta al modelo YOLO de segmentación.
            patch_size: Lado en píxeles de cada parche cuadrado.
            padding_pct: Expansión fraccional del recorte (contexto extra).
        """
        self._model_path = model_path
        self._patch_size = patch_size
        self._padding_pct = padding_pct
        self._model = None  # Carga perezosa en el primer uso.

    def _ensure_model(self) -> None:
        """Carga el modelo YOLO bajo demanda (importación perezosa)."""
        if self._model is None:
            from ultralytics import YOLO  # Import diferido (pesado).

            self._model = YOLO(str(self._model_path))

    def extract(self, image: np.ndarray) -> List[Patch]:
        """
        Recorta parches enmascarados dentro de cada región segmentada.

        Args:
            image: Imagen BGR de origen.

        Returns:
            Lista de parches válidos (con suficiente cobertura de máscara).
        """
        self._ensure_model()
        results = self._model(image, verbose=False)  # type: ignore[misc]

        size = self._patch_size
        patches: List[Patch] = []
        counter = 0

        for result in results:
            if not result.masks:
                continue
            boxes = result.boxes.xyxy.cpu().numpy()

            for i, polygon in enumerate(result.masks.xy):
                poly_np = np.asarray(polygon)
                if poly_np.size == 0:
                    continue

                box = boxes[i] if len(boxes) > i else None
                crop_img, crop_mask, (x1, y1, _x2, _y2) = build_crop_and_mask(
                    image, poly_np, box, padding_pct=self._padding_pct
                )
                if crop_img is None or crop_mask is None:
                    continue

                counter = self._tile_region(
                    crop_img, crop_mask, x1, y1, size, counter, patches
                )
        return patches

    @staticmethod
    def _tile_region(
        crop_img: np.ndarray,
        crop_mask: np.ndarray,
        origin_x: int,
        origin_y: int,
        size: int,
        counter: int,
        patches: List[Patch],
    ) -> int:
        """
        Trocea una región recortada en parches y los añade a ``patches``.

        Returns:
            El contador de parches actualizado.
        """
        region_h, region_w = crop_mask.shape

        for top in range(0, region_h - size + 1, size):
            for left in range(0, region_w - size + 1, size):
                mask_tile = crop_mask[top:top + size, left:left + size]
                if np.count_nonzero(mask_tile) / (size * size) < _MIN_MASK_RATIO:
                    continue

                orig_tile = crop_img[top:top + size, left:left + size]
                masked_tile = cv2.bitwise_and(
                    orig_tile, orig_tile, mask=mask_tile
                )

                patches.append(
                    Patch(
                        index=counter,
                        source_type="yolo",
                        x=origin_x + left,
                        y=origin_y + top,
                        w=size,
                        h=size,
                        original=orig_tile.copy(),
                        masked=masked_tile,
                    )
                )
                counter += 1
        return counter


def create_extractor(config: LabelerConfig) -> PatchExtractor:
    """
    Fábrica que elige la estrategia de extracción según la configuración.

    Args:
        config: Configuración de la sesión.

    Returns:
        Un extractor YOLO si hay modelo válido; en caso contrario, de cuadrícula.
    """
    if config.use_yolo:
        assert config.model_path is not None  # Garantizado por ``use_yolo``.
        return YoloPatchExtractor(
            config.model_path, config.patch_size, config.padding_pct
        )
    return GridPatchExtractor(config.patch_size)
