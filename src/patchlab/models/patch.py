"""Entidad de dominio que representa un parche individual a etiquetar."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

# Etiquetas internas reservadas que no representan una clase real del dataset.
SKIP = "SKIP"


@dataclass
class Patch:
    """
    Recorte concreto extraído de una imagen, pendiente o ya etiquetado.

    Las coordenadas ``x``, ``y``, ``w`` y ``h`` están expresadas respecto al
    lienzo de la imagen original (no respecto al recorte), de modo que pueden
    dibujarse directamente sobre la vista de contexto.

    Attributes:
        index: Índice ordinal del parche dentro de su imagen (base 0).
        source_type: Origen del parche, ``"grid"`` o ``"yolo"``.
        x, y, w, h: Caja del parche en coordenadas de la imagen original.
        original: Recorte BGR sin enmascarar (tal como sale de OpenCV).
        masked: Recorte BGR enmascarado por YOLO; ``None`` en modo cuadrícula.
        label: Etiqueta asignada, ``SKIP`` u ``None`` si aún no se decide.
        saved_path: Ruta en disco del archivo guardado, si se guardó.
        suggested_label: Clase propuesta por el modelo de clasificación opcional
            (``None`` si no hay modelo o no superó el umbral de confianza).
        suggested_confidence: Confianza [0, 1] de ``suggested_label``.
    """

    index: int
    source_type: str
    x: int
    y: int
    w: int
    h: int
    original: np.ndarray
    masked: Optional[np.ndarray] = None
    label: Optional[str] = None
    saved_path: Optional[Path] = None
    suggested_label: Optional[str] = None
    suggested_confidence: float = 0.0

    @property
    def display_image(self) -> np.ndarray:
        """Imagen BGR a mostrar: la enmascarada si existe, si no la original."""
        return self.masked if self.masked is not None else self.original

    @property
    def is_decided(self) -> bool:
        """``True`` si el parche ya recibió una etiqueta (incluido ``SKIP``)."""
        return self.label is not None

    @property
    def is_classified(self) -> bool:
        """``True`` solo si tiene una etiqueta de clase real (no ``SKIP``)."""
        return self.label is not None and self.label != SKIP
