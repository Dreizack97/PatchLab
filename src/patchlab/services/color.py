"""Generación determinista de colores por etiqueta.

El color de cada clase se deriva de forma estable del *hash* de su nombre, de
modo que una misma etiqueta siempre se dibuja con el mismo color entre sesiones.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Tuple

# Mínimo de brillo por canal para que ningún color quede demasiado oscuro.
_FLOOR = 55
_SPAN = 200


@lru_cache(maxsize=256)
def label_color_rgb(label: str) -> Tuple[int, int, int]:
    """
    Devuelve un color RGB constante (apto para Qt) a partir del nombre.

    Args:
        label: Nombre de la clase.

    Returns:
        Terna ``(r, g, b)`` con valores en el rango ``[55, 254]``.
    """
    digest = int(hashlib.md5(label.encode("utf-8")).hexdigest(), 16)
    r = (digest & 0xFF) % _SPAN + _FLOOR
    g = ((digest >> 8) & 0xFF) % _SPAN + _FLOOR
    b = ((digest >> 16) & 0xFF) % _SPAN + _FLOOR
    return (r, g, b)


def label_color_bgr(label: str) -> Tuple[int, int, int]:
    """
    Devuelve el mismo color en orden BGR (apto para OpenCV).

    Args:
        label: Nombre de la clase.

    Returns:
        Terna ``(b, g, r)``.
    """
    r, g, b = label_color_rgb(label)
    return (b, g, r)
