"""Renderizado de la vista de contexto.

Genera la imagen original atenuada con el historial de parches ya etiquetados
(cajas de color con su etiqueta) y el parche activo resaltado en rojo. Es lógica
de presentación pura sobre matrices NumPy, sin dependencias de la GUI, lo que la
mantiene testeable de forma aislada.
"""

from __future__ import annotations

from typing import List

import cv2
import numpy as np

from patchlab.models.patch import Patch
from patchlab.services.color import label_color_bgr

# Resaltado del parche activo (rojo intenso en BGR).
_ACTIVE_COLOR = (0, 0, 255)
_ACTIVE_THICKNESS = 4
_HISTORY_THICKNESS = 3


def render_context(
    image: np.ndarray, patches: List[Patch], current_index: int
) -> np.ndarray:
    """
    Dibuja el contexto global con historial y el parche activo.

    Args:
        image: Imagen BGR original.
        patches: Todos los parches de la imagen.
        current_index: Índice del parche actualmente bajo decisión.

    Returns:
        Copia BGR de la imagen anotada lista para mostrarse.
    """
    # Atenúa el fondo para que las anotaciones destaquen (60 % de brillo).
    context = cv2.addWeighted(image, 0.6, np.zeros_like(image), 0.4, 0)

    # Historial: parches anteriores ya clasificados (se omiten los SKIP).
    for patch in patches[:current_index]:
        if not patch.is_classified:
            continue
        _draw_history_box(context, patch)

    # Parche activo resaltado.
    if 0 <= current_index < len(patches):
        active = patches[current_index]
        cv2.rectangle(
            context,
            (active.x, active.y),
            (active.x + active.w, active.y + active.h),
            _ACTIVE_COLOR,
            _ACTIVE_THICKNESS,
        )
    return context


def _draw_history_box(context: np.ndarray, patch: Patch) -> None:
    """Dibuja la caja y el rótulo de un parche ya etiquetado."""
    color = label_color_bgr(patch.label)  # type: ignore[arg-type]
    x, y, w, h = patch.x, patch.y, patch.w, patch.h

    cv2.rectangle(context, (x, y), (x + w, y + h), color, _HISTORY_THICKNESS)
    # Fondo negro para el texto, encima de la caja.
    cv2.rectangle(context, (x, max(0, y - 20)), (x + w, y), (0, 0, 0), -1)
    cv2.putText(
        context,
        patch.label,  # type: ignore[arg-type]
        (x + 2, max(15, y - 5)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        color,
        1,
        cv2.LINE_AA,
    )
