"""Clasificador opcional que pre-sugiere la clase de cada parche.

Cuando el usuario proporciona un modelo de clasificación (un ``.pt`` de
ultralytics entrenado con la tarea *classify*), este servicio infiere una clase
para cada parche y la deja anotada como *sugerencia* (no como decisión final).
Las sugerencias aceleran el etiquetado: en el modo cuadrícula aparecen
pre-pintadas y el usuario solo revisa o corrige; en el modo secuencial se
resaltan como atajo recomendado.

La importación de ``ultralytics`` es perezosa —igual que en el extractor YOLO—,
de modo que el modo sin clasificador no arrastra dependencias de *deep learning*.
Cualquier fallo de inferencia se considera no fatal: el etiquetado continúa sin
sugerencias en lugar de interrumpirse.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from patchlab.models.config import LabelerConfig
from patchlab.models.patch import Patch


class PatchClassifier:
    """Sugiere una clase por parche usando un modelo de clasificación ultralytics."""

    def __init__(
        self,
        model_path: Path,
        labels: List[str],
        min_confidence: float = 0.0,
    ) -> None:
        """
        Args:
            model_path: Ruta al modelo de clasificación (``.pt``).
            labels: Etiquetas válidas de la sesión; solo se sugieren clases que
                coincidan (sin distinguir mayúsculas) con alguna de ellas.
            min_confidence: Confianza mínima [0, 1] para aceptar una sugerencia.
        """
        self._model_path = model_path
        self._min_confidence = min_confidence
        self._model = None  # Carga perezosa en el primer uso.
        # Mapa nombre-en-minúsculas → etiqueta canónica de la sesión, para
        # tolerar diferencias de mayúsculas entre el modelo y la configuración.
        self._canonical: Dict[str, str] = {lbl.lower(): lbl for lbl in labels}

    def _ensure_model(self) -> None:
        """Carga el modelo de clasificación bajo demanda (importación perezosa)."""
        if self._model is None:
            from ultralytics import YOLO  # Import diferido (pesado).

            self._model = YOLO(str(self._model_path))

    def annotate(self, patches: List[Patch]) -> int:
        """
        Anota ``suggested_label``/``suggested_confidence`` en cada parche.

        Args:
            patches: Parches a clasificar (se modifican en el sitio).

        Returns:
            Número de parches que recibieron una sugerencia válida.
        """
        if not patches:
            return 0
        self._ensure_model()

        images = [patch.display_image for patch in patches]
        results = self._model(images, verbose=False)  # type: ignore[misc]

        suggested = 0
        for patch, result in zip(patches, results):
            label, confidence = self._read_prediction(result)
            if label is not None:
                patch.suggested_label = label
                patch.suggested_confidence = confidence
                suggested += 1
        return suggested

    def _read_prediction(self, result) -> tuple[Optional[str], float]:
        """
        Traduce un resultado de ultralytics a (etiqueta_canónica, confianza).

        Devuelve ``(None, 0.0)`` si no hay clasificación, si la confianza no
        alcanza el umbral o si la clase predicha no pertenece a la sesión.
        """
        probs = getattr(result, "probs", None)
        if probs is None:
            return None, 0.0

        index = int(probs.top1)
        confidence = float(probs.top1conf)
        if confidence < self._min_confidence:
            return None, 0.0

        names = getattr(result, "names", {})
        raw_name = names.get(index, str(index)) if isinstance(names, dict) else str(index)
        canonical = self._canonical.get(str(raw_name).lower())
        if canonical is None:
            return None, 0.0
        return canonical, confidence


def create_classifier(config: LabelerConfig) -> Optional[PatchClassifier]:
    """
    Fábrica del clasificador opcional según la configuración.

    Args:
        config: Configuración de la sesión.

    Returns:
        Un :class:`PatchClassifier` si hay un modelo válido; ``None`` si no.
    """
    if not config.use_classifier:
        return None
    assert config.classifier_path is not None  # Garantizado por ``use_classifier``.
    return PatchClassifier(
        config.classifier_path,
        config.labels,
        config.classifier_min_confidence,
    )
