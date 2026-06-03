"""Pruebas unitarias del Modelo de la cuadrícula (sin dependencias de Qt)."""

from __future__ import annotations

from typing import List

import numpy as np

from patchlab.models.grid_session import GridSession
from patchlab.models.patch import Patch


def _patches(n: int) -> List[Patch]:
    """Crea ``n`` parches sintéticos para las pruebas."""
    return [
        Patch(
            index=i,
            source_type="grid",
            x=i * 10,
            y=0,
            w=10,
            h=10,
            original=np.zeros((10, 10, 3), np.uint8),
        )
        for i in range(n)
    ]


def test_paint_is_idempotent() -> None:
    session = GridSession(_patches(3))
    assert session.paint(0, "OK") is True
    assert session.paint(0, "OK") is False  # sin cambio => sin historial
    assert session.label_at(0) == "OK"
    assert session.labeled_count == 1


def test_fill_remaining_only_touches_empty_cells() -> None:
    session = GridSession(_patches(4))
    session.paint(0, "OK")
    affected = session.fill_remaining("NG")
    assert affected == 3
    assert [p.label for p in session.patches] == ["OK", "NG", "NG", "NG"]
    assert session.remaining_count == 0


def test_undo_redo_roundtrip() -> None:
    session = GridSession(_patches(4))
    session.paint(0, "OK")
    session.fill_remaining("NG")
    assert session.labeled_count == 4

    assert session.undo() is True            # deshace el fill
    assert session.labeled_count == 1
    assert session.redo() is True            # rehace el fill
    assert session.labeled_count == 4


def test_new_action_discards_redo_stack() -> None:
    session = GridSession(_patches(3))
    session.paint(0, "OK")
    session.undo()
    assert session.can_redo is True
    session.paint(1, "NG")                   # nueva acción
    assert session.can_redo is False


def test_clear_and_classified_patches() -> None:
    session = GridSession(_patches(3))
    session.fill_remaining("OK")
    assert len(session.classified_patches()) == 3
    assert session.clear(0) is True
    assert session.label_at(0) is None
    assert len(session.classified_patches()) == 2
