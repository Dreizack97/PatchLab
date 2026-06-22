"""Pruebas del clasificador opcional de parches (sin dependencias de Qt/torch).

El modelo de ``ultralytics`` se sustituye por un doble de prueba que imita la
forma del resultado real (``result.probs.top1`` / ``top1conf`` y ``result.names``),
de modo que se ejercita la lógica de mapeo y umbral sin cargar *deep learning*.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

import numpy as np

from patchlab.models.config import LabelerConfig
from patchlab.models.grid_session import GridSession
from patchlab.models.patch import Patch
from patchlab.services.classifier import PatchClassifier, create_classifier


class _FakeProbs:
    """Imita ``result.probs`` de ultralytics-classify."""

    def __init__(self, top1: int, top1conf: float) -> None:
        self.top1 = top1
        self.top1conf = top1conf


class _FakeResult:
    """Imita un resultado de inferencia con clasificación top-1."""

    def __init__(self, names: dict, top1: int, conf: float) -> None:
        self.names = names
        self.probs = _FakeProbs(top1, conf)


class _FakeModel:
    """Modelo invocable que devuelve un resultado predefinido por imagen."""

    def __init__(self, results: Sequence[_FakeResult]) -> None:
        self._results = list(results)

    def __call__(self, images, verbose=False):  # noqa: D401 — firma de ultralytics.
        assert len(images) == len(self._results)
        return self._results


def _patches(n: int) -> List[Patch]:
    """Crea ``n`` parches sintéticos sin etiqueta."""
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


def _classifier(model: _FakeModel, *, min_confidence: float = 0.0) -> PatchClassifier:
    """Construye un clasificador con el modelo falso ya inyectado."""
    clf = PatchClassifier(Path("dummy.pt"), ["OK", "NG"], min_confidence)
    clf._model = model  # Evita la carga perezosa real de ultralytics.
    return clf


def test_annotate_maps_canonical_label_case_insensitive() -> None:
    names = {0: "ok", 1: "ng"}
    model = _FakeModel([_FakeResult(names, 1, 0.91), _FakeResult(names, 0, 0.80)])
    patches = _patches(2)

    suggested = _classifier(model).annotate(patches)

    assert suggested == 2
    assert patches[0].suggested_label == "NG"  # «ng» → etiqueta canónica «NG»
    assert patches[0].suggested_confidence == 0.91
    assert patches[1].suggested_label == "OK"


def test_annotate_skips_below_min_confidence() -> None:
    names = {0: "OK", 1: "NG"}
    model = _FakeModel([_FakeResult(names, 0, 0.40)])
    patches = _patches(1)

    suggested = _classifier(model, min_confidence=0.5).annotate(patches)

    assert suggested == 0
    assert patches[0].suggested_label is None
    assert patches[0].suggested_confidence == 0.0


def test_annotate_ignores_classes_outside_session() -> None:
    names = {0: "perro"}  # No pertenece a las etiquetas de la sesión.
    model = _FakeModel([_FakeResult(names, 0, 0.99)])
    patches = _patches(1)

    assert _classifier(model).annotate(patches) == 0
    assert patches[0].suggested_label is None


def test_annotate_empty_list_returns_zero() -> None:
    # Lista vacía: ni siquiera debe intentar cargar/invocar el modelo.
    clf = PatchClassifier(Path("dummy.pt"), ["OK", "NG"])
    assert clf.annotate([]) == 0


def test_create_classifier_returns_none_without_model() -> None:
    config = LabelerConfig(input_dir=Path("."), output_dir=Path("."))
    assert config.use_classifier is False
    assert create_classifier(config) is None


def test_prefill_suggestions_sets_initial_labels_without_history() -> None:
    patches = _patches(3)
    patches[0].suggested_label = "OK"
    patches[1].suggested_label = "NG"
    # patches[2] no recibe sugerencia.
    session = GridSession(patches)

    prefilled = session.prefill_suggestions()

    assert prefilled == 2
    assert session.label_at(0) == "OK"
    assert session.label_at(1) == "NG"
    assert session.label_at(2) is None
    # Las sugerencias son el estado de partida, no una acción deshacible.
    assert session.can_undo is False


def test_prefill_does_not_override_existing_label() -> None:
    patches = _patches(2)
    patches[0].suggested_label = "NG"
    session = GridSession(patches)
    session.paint(0, "OK")  # Decisión previa del usuario.

    prefilled = session.prefill_suggestions()

    assert prefilled == 0
    assert session.label_at(0) == "OK"
