"""Protocolo de mensajería del etiquetado colaborativo distribuido (sin Qt).

Define el "contrato de cable" entre el Host (coordinador) y los Colaboradores
(trabajadores) en el **flujo distribuido por shards**, junto con la validación
estricta de todo lo que entra por la red.

Flujo de mensajes (resumen):

- *Lobby*: el cliente se autentica con ``hello``; el Host responde ``welcome`` y
  difunde ``lobby`` (participantes + tamaño del dataset) hasta que arranca.
- *Distribución*: al comenzar, el Host envía a cada cliente su ``assignment``
  (tamaño del shard) y le sirve imágenes con ``image`` a medida que las pide con
  ``request_next``.
- *Etiquetado*: el cliente devuelve las etiquetas de cada imagen con ``submit``;
  el Host consolida y difunde ``progress``. Al agotar el shard envía
  ``shard_done``. Las transiciones de fase viajan en ``phase``.

Filosofía de seguridad (sanitización): el Host solo acepta tres comandos
acotados (``hello``/``request_next``/``submit``); cualquier otra cosa —tipo
desconocido, JSON malformado, frame demasiado grande, etiqueta no declarada— se
rechaza con :class:`ProtocolError`. Ningún mensaje transporta rutas ni código.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

# --------------------------------------------------------------------------- #
# Tipos de mensaje
# --------------------------------------------------------------------------- #
# Cliente → Host (los únicos comandos que el Host acepta).
T_HELLO = "hello"
T_REQUEST_NEXT = "request_next"
T_SUBMIT = "submit"
CLIENT_TYPES = frozenset({T_HELLO, T_REQUEST_NEXT, T_SUBMIT})

# Host → Cliente (coordinación y difusión de estado).
T_WELCOME = "welcome"
T_DENIED = "denied"
T_LOBBY = "lobby"
T_ASSIGNMENT = "assignment"
T_IMAGE = "image"
T_PROGRESS = "progress"
T_PHASE = "phase"
T_SHARD_DONE = "shard_done"
T_BYE = "bye"
SERVER_TYPES = frozenset(
    {
        T_WELCOME, T_DENIED, T_LOBBY, T_ASSIGNMENT, T_IMAGE,
        T_PROGRESS, T_PHASE, T_SHARD_DONE, T_BYE,
    }
)

# --------------------------------------------------------------------------- #
# Límites de saneamiento
# --------------------------------------------------------------------------- #
#: Tamaño máximo de un mensaje entrante en el Host. El mayor es ``submit`` (un
#: vector de etiquetas); 1 MiB cubre incluso cuadrículas muy densas.
MAX_CLIENT_MESSAGE_BYTES = 1 * 1024 * 1024
#: Número máximo de celdas admitido en un vector de etiquetas.
MAX_CELLS = 200_000
MAX_TOKEN_LEN = 128
MAX_NAME_LEN = 40
MAX_LABEL_LEN = 64


class ProtocolError(ValueError):
    """Mensaje entrante inválido o no permitido (debe rechazarse/cerrarse)."""


# --------------------------------------------------------------------------- #
# Codificación / decodificación
# --------------------------------------------------------------------------- #
def encode(message: Mapping[str, Any]) -> str:
    """Serializa un mensaje a una cadena JSON compacta lista para el socket."""
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)


def _decode_envelope(raw: str, *, max_bytes: Optional[int]) -> Dict[str, Any]:
    """Valida tamaño, parsea el JSON y comprueba la envoltura ``{"t": ...}``."""
    if max_bytes is not None and len(raw.encode("utf-8")) > max_bytes:
        raise ProtocolError("Mensaje demasiado grande.")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ProtocolError(f"JSON inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise ProtocolError("El mensaje debe ser un objeto JSON.")
    if not isinstance(data.get("t"), str):
        raise ProtocolError("Falta el tipo de mensaje «t».")
    return data


# --------------------------------------------------------------------------- #
# Validadores auxiliares
# --------------------------------------------------------------------------- #
def _as_int(value: Any, *, field: str, minimum: int = 0) -> int:
    """Comprueba que ``value`` es un entero (no ``bool``) ``>= minimum``."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"El campo «{field}» debe ser un entero.")
    if value < minimum:
        raise ProtocolError(f"El campo «{field}» no puede ser menor que {minimum}.")
    return value


def _as_text(value: Any, *, field: str, max_len: int) -> str:
    """Comprueba que ``value`` es texto de longitud acotada y lo recorta."""
    if not isinstance(value, str):
        raise ProtocolError(f"El campo «{field}» debe ser texto.")
    text = value.strip()
    if not text:
        raise ProtocolError(f"El campo «{field}» no puede estar vacío.")
    if len(text) > max_len:
        raise ProtocolError(f"El campo «{field}» excede {max_len} caracteres.")
    return text


def _as_label_vector(value: Any, label_set: Iterable[str]) -> list:
    """Valida un vector de etiquetas (cada celda: ``None`` o etiqueta válida)."""
    if not isinstance(value, list):
        raise ProtocolError("El campo «labels» debe ser una lista.")
    if len(value) > MAX_CELLS:
        raise ProtocolError("El vector de etiquetas es demasiado largo.")
    allowed = set(label_set)
    clean: list = []
    for item in value:
        if item is None:
            clean.append(None)
            continue
        if not isinstance(item, str):
            raise ProtocolError("Cada etiqueta debe ser texto o nula.")
        if len(item) > MAX_LABEL_LEN or item not in allowed:
            raise ProtocolError(f"Etiqueta no declarada: {item!r}.")
        clean.append(item)
    return clean


# --------------------------------------------------------------------------- #
# Parseo de mensajes del CLIENTE (ejecutado en el Host — superficie de ataque)
# --------------------------------------------------------------------------- #
def parse_client_message(
    raw: str,
    *,
    label_set: Iterable[str],
    max_bytes: int = MAX_CLIENT_MESSAGE_BYTES,
) -> Dict[str, Any]:
    """
    Valida y normaliza un comando recibido de un colaborador.

    Returns:
        Diccionario canónico y seguro según el tipo de comando.

    Raises:
        ProtocolError: Si el mensaje es desconocido, malformado o no permitido.
    """
    data = _decode_envelope(raw, max_bytes=max_bytes)
    msg_type = data["t"]
    if msg_type not in CLIENT_TYPES:
        raise ProtocolError(f"Tipo de comando no permitido: {msg_type!r}.")

    if msg_type == T_HELLO:
        return {
            "t": T_HELLO,
            "token": _as_text(
                data.get("token", ""), field="token", max_len=MAX_TOKEN_LEN
            ),
            "name": _as_text(
                data.get("name") or "Colaborador",
                field="name",
                max_len=MAX_NAME_LEN,
            ),
        }

    if msg_type == T_REQUEST_NEXT:
        return {"t": T_REQUEST_NEXT}

    # T_SUBMIT
    return {
        "t": T_SUBMIT,
        "index": _as_int(data.get("index"), field="index"),
        "labels": _as_label_vector(data.get("labels"), label_set),
    }


def parse_hello(raw: str, *, max_bytes: int = MAX_CLIENT_MESSAGE_BYTES) -> Dict[str, Any]:
    """Valida el *handshake* inicial; exige que el primer mensaje sea ``hello``."""
    data = parse_client_message(raw, label_set=(), max_bytes=max_bytes)
    if data["t"] != T_HELLO:
        raise ProtocolError("El primer mensaje debe ser «hello».")
    return data


# --------------------------------------------------------------------------- #
# Parseo de mensajes del HOST (ejecutado en el Cliente)
# --------------------------------------------------------------------------- #
def parse_server_message(raw: str) -> Dict[str, Any]:
    """Decodifica y valida superficialmente un mensaje difundido por el Host."""
    data = _decode_envelope(raw, max_bytes=None)
    if data["t"] not in SERVER_TYPES:
        raise ProtocolError(f"Tipo de mensaje del Host desconocido: {data['t']!r}.")
    return data


# --------------------------------------------------------------------------- #
# Constructores (Cliente → Host)
# --------------------------------------------------------------------------- #
def build_hello(token: str, name: str) -> Dict[str, Any]:
    """Mensaje de presentación con token de sesión y nombre visible."""
    return {"t": T_HELLO, "token": token, "name": name}


def build_request_next() -> Dict[str, Any]:
    """Solicitud de la siguiente imagen del shard asignado."""
    return {"t": T_REQUEST_NEXT}


def build_submit(index: int, labels: Sequence[Optional[str]]) -> Dict[str, Any]:
    """Envío del vector de etiquetas de la imagen ``index`` ya etiquetada."""
    return {"t": T_SUBMIT, "index": index, "labels": list(labels)}


# --------------------------------------------------------------------------- #
# Constructores (Host → Cliente)
# --------------------------------------------------------------------------- #
def build_welcome(client_id: int, labels: Sequence[str], phase: str) -> Dict[str, Any]:
    """Confirmación de acceso: identidad, etiquetas y fase actual."""
    return {"t": T_WELCOME, "you": client_id, "labels": list(labels), "phase": phase}


def build_denied(reason: str) -> Dict[str, Any]:
    """Rechazo de acceso (p. ej. token incorrecto). Tras enviarlo, se cierra."""
    return {"t": T_DENIED, "reason": reason}


def build_lobby(
    participants: Sequence[Mapping[str, Any]], total_images: int, phase: str
) -> Dict[str, Any]:
    """Estado del lobby: participantes conectados y tamaño del dataset."""
    return {
        "t": T_LOBBY,
        "participants": list(participants),
        "total_images": total_images,
        "phase": phase,
    }


def build_assignment(count: int, total_images: int) -> Dict[str, Any]:
    """Tamaño del shard asignado a este cliente y total del dataset."""
    return {"t": T_ASSIGNMENT, "count": count, "total_images": total_images}


def build_image(
    *,
    index: int,
    file_name: str,
    width: int,
    height: int,
    jpeg_b64: str,
    cells: Sequence[Sequence[int]],
    position: int,
    shard_total: int,
) -> Dict[str, Any]:
    """Una imagen del shard para etiquetar: píxeles (JPEG) + geometría."""
    return {
        "t": T_IMAGE,
        "index": index,
        "file_name": file_name,
        "w": width,
        "h": height,
        "jpeg_b64": jpeg_b64,
        "cells": [list(cell) for cell in cells],
        "position": position,
        "shard_total": shard_total,
    }


def build_progress(
    me: Mapping[str, Any], everyone: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Progreso propio del cliente y de todos (para el panel supervisor)."""
    return {"t": T_PROGRESS, "me": dict(me), "all": list(everyone)}


def build_phase(phase: str) -> Dict[str, Any]:
    """Notificación de transición de fase de la sesión."""
    return {"t": T_PHASE, "phase": phase}


def build_shard_done() -> Dict[str, Any]:
    """Aviso de que el cliente ha completado toda su porción."""
    return {"t": T_SHARD_DONE}


def build_bye(reason: str) -> Dict[str, Any]:
    """Aviso de cierre de la sesión por parte del Host."""
    return {"t": T_BYE, "reason": reason}
