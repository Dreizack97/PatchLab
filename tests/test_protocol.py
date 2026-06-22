"""Pruebas del protocolo colaborativo distribuido (validación y serialización)."""

from __future__ import annotations

import pytest

from patchlab.collab import protocol

LABELS = ("OK", "NG")


def _parse(raw: str):
    """Atajo: valida un mensaje de cliente con el contexto de prueba."""
    return protocol.parse_client_message(raw, label_set=LABELS)


# --------------------------------------------------------------------------- #
# Round-trips válidos (Cliente → Host)
# --------------------------------------------------------------------------- #
def test_request_next_round_trip() -> None:
    raw = protocol.encode(protocol.build_request_next())
    assert _parse(raw) == {"t": protocol.T_REQUEST_NEXT}


def test_submit_round_trip() -> None:
    raw = protocol.encode(protocol.build_submit(5, ["OK", None, "NG"]))
    assert _parse(raw) == {
        "t": protocol.T_SUBMIT,
        "index": 5,
        "labels": ["OK", None, "NG"],
    }


def test_hello_defaults_missing_name() -> None:
    raw = protocol.encode({"t": protocol.T_HELLO, "token": "ABC123"})
    parsed = protocol.parse_hello(raw)
    assert parsed["token"] == "ABC123"
    assert parsed["name"] == "Colaborador"


# --------------------------------------------------------------------------- #
# Rechazos (sanitización)
# --------------------------------------------------------------------------- #
def test_rejects_malformed_json() -> None:
    with pytest.raises(protocol.ProtocolError):
        _parse("{no es json")


def test_rejects_non_object() -> None:
    with pytest.raises(protocol.ProtocolError):
        _parse("[1, 2, 3]")


def test_rejects_unknown_type() -> None:
    with pytest.raises(protocol.ProtocolError):
        _parse(protocol.encode({"t": "exec", "cmd": "rm -rf /"}))


def test_rejects_oversize_message() -> None:
    big = protocol.encode(protocol.build_submit(0, ["OK"] * 10))
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_client_message(big, label_set=LABELS, max_bytes=8)


def test_submit_rejects_undeclared_label() -> None:
    with pytest.raises(protocol.ProtocolError):
        _parse(protocol.encode(protocol.build_submit(1, ["OK", "MALWARE"])))


def test_submit_rejects_non_list_labels() -> None:
    with pytest.raises(protocol.ProtocolError):
        _parse(protocol.encode({"t": protocol.T_SUBMIT, "index": 1, "labels": "OK"}))


@pytest.mark.parametrize("index", [-1, "3", 1.5, True, None])
def test_submit_rejects_bad_index(index) -> None:
    with pytest.raises(protocol.ProtocolError):
        _parse(protocol.encode({"t": protocol.T_SUBMIT, "index": index, "labels": []}))


def test_submit_allows_null_cells() -> None:
    parsed = _parse(protocol.encode(protocol.build_submit(0, [None, None])))
    assert parsed["labels"] == [None, None]


def test_parse_hello_requires_hello_first() -> None:
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_hello(protocol.encode(protocol.build_request_next()))


# --------------------------------------------------------------------------- #
# Mensajes del Host (Host → Cliente)
# --------------------------------------------------------------------------- #
def test_lobby_message_round_trip() -> None:
    raw = protocol.encode(
        protocol.build_lobby([{"id": 0, "name": "Host"}], 42, "lobby")
    )
    parsed = protocol.parse_server_message(raw)
    assert parsed["t"] == protocol.T_LOBBY
    assert parsed["total_images"] == 42
    assert parsed["phase"] == "lobby"


def test_image_message_carries_geometry() -> None:
    raw = protocol.encode(
        protocol.build_image(
            index=3,
            file_name="a.jpg",
            width=64,
            height=64,
            jpeg_b64="",
            cells=[(0, 0, 32, 32)],
            position=1,
            shard_total=5,
        )
    )
    parsed = protocol.parse_server_message(raw)
    assert parsed["index"] == 3
    assert parsed["cells"] == [[0, 0, 32, 32]]
    assert parsed["shard_total"] == 5
    # Sin clasificador no se envía el vector de sugerencias.
    assert "suggestions" not in parsed


def test_image_message_carries_classifier_suggestions() -> None:
    raw = protocol.encode(
        protocol.build_image(
            index=0,
            file_name="a.jpg",
            width=64,
            height=64,
            jpeg_b64="",
            cells=[(0, 0, 32, 32), (32, 0, 32, 32)],
            position=1,
            shard_total=1,
            suggestions=["OK", None],
        )
    )
    parsed = protocol.parse_server_message(raw)
    assert parsed["suggestions"] == ["OK", None]


def test_server_message_rejects_unknown() -> None:
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_server_message(protocol.encode({"t": "submit", "index": 1}))
