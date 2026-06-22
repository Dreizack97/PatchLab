"""Utilidades de red sin dependencia de Qt: IP local, token y puerto.

Funciones pequeñas y multiplataforma usadas por el Host para anunciar cómo
conectarse a la sesión. No abren puertos de escucha: solo descubren datos.
"""

from __future__ import annotations

import secrets
import socket

#: Puerto por defecto de la sesión colaborativa (configurable en la interfaz).
DEFAULT_PORT = 8765


def local_ip() -> str:
    """
    Descubre la IP de la interfaz de red usada para salir a la LAN.

    No envía tráfico real: abre un socket UDP "conectado" a una dirección
    externa para que el sistema operativo elija la interfaz de salida y revele
    su IP local. Funciona igual en Windows, macOS y Linux.

    Returns:
        La IP local (p. ej. ``192.168.1.42``) o ``127.0.0.1`` si no hay red.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # La dirección no necesita ser alcanzable; no se envían paquetes.
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def make_token(length: int = 6) -> str:
    """
    Genera un token de sesión corto, legible y razonablemente impredecible.

    Args:
        length: Número de caracteres del token.

    Returns:
        Cadena alfanumérica en mayúsculas (sin caracteres ambiguos).
    """
    # Alfabeto sin 0/O ni 1/I/L para que sea fácil de dictar y teclear.
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
