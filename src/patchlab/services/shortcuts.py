"""Mapeo entre teclas del teclado y etiquetas de clase.

Replica el esquema del script original: cada etiqueta recibe, en orden, una
tecla de ``KEY_CHARS``. El comportamiento es idéntico en Windows, macOS y Linux
porque se basa en el carácter producido por la tecla, no en códigos nativos.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Conjunto de teclas asignables a etiquetas, en orden de prioridad.
KEY_CHARS = "1234567890qwertyuiopasdfghjklzxcvbnm"


def build_keymap(labels: List[str]) -> Dict[str, str]:
    """
    Asocia cada etiqueta a un carácter de atajo.

    Args:
        labels: Lista ordenada de etiquetas de clase.

    Returns:
        Diccionario ``{caracter: etiqueta}``.

    Raises:
        ValueError: Si hay más etiquetas que teclas disponibles.
    """
    if len(labels) > len(KEY_CHARS):
        raise ValueError(
            f"Demasiadas etiquetas ({len(labels)}); "
            f"el máximo admitido es {len(KEY_CHARS)}."
        )
    return {KEY_CHARS[i]: label for i, label in enumerate(labels)}


def shortcut_for(labels: List[str], label: str) -> Optional[str]:
    """
    Devuelve el carácter de atajo asignado a una etiqueta.

    Args:
        labels: Lista ordenada de etiquetas.
        label: Etiqueta cuyo atajo se busca.

    Returns:
        El carácter de atajo, o ``None`` si la etiqueta no está mapeada.
    """
    try:
        return KEY_CHARS[labels.index(label)]
    except (ValueError, IndexError):
        return None
