"""Configuración inmutable de una sesión de etiquetado."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class LabelingMode(str, Enum):
    """Modo de interacción de la sesión de etiquetado."""

    #: Flujo clásico: un parche cada vez, se confirma con teclado o botones.
    SEQUENTIAL = "sequential"
    #: Flujo por clic: toda la cuadrícula visible, se "pinta" la clase activa.
    GRID_CLICK = "grid_click"


@dataclass
class LabelerConfig:
    """
    Parámetros que definen una sesión completa de etiquetado.

    Attributes:
        input_dir: Directorio raíz con las imágenes a etiquetar.
        output_dir: Directorio destino del dataset organizado por clases.
        labels: Lista de etiquetas de clase disponibles (orden = atajo).
        model_path: Ruta opcional a un modelo YOLO de segmentación.
        patch_size: Lado en píxeles de los parches cuadrados.
        padding_pct: Expansión fraccional del recorte YOLO (0.1 = 10 %).
        mode: Modo de interacción (secuencial o por clic en la cuadrícula).
    """

    input_dir: Path
    output_dir: Path
    labels: List[str] = field(default_factory=lambda: ["OK", "NG"])
    model_path: Optional[Path] = None
    patch_size: int = 64
    padding_pct: float = 0.0
    mode: LabelingMode = LabelingMode.SEQUENTIAL

    @property
    def use_yolo(self) -> bool:
        """Indica si la sesión debe operar en modo YOLO (modelo válido)."""
        return self.model_path is not None and self.model_path.is_file()

    def validate(self) -> None:
        """
        Comprueba la coherencia de la configuración.

        Raises:
            ValueError: Si algún parámetro es inválido o incompatible.
        """
        if not self.input_dir.is_dir():
            raise ValueError(
                f"El directorio de entrada no existe: {self.input_dir}"
            )
        if not self.labels:
            raise ValueError("Debes proporcionar al menos una etiqueta.")
        if len(self.labels) != len(set(self.labels)):
            raise ValueError("Las etiquetas no pueden repetirse.")
        if self.patch_size <= 0:
            raise ValueError("El tamaño de parche debe ser mayor que cero.")
        if self.padding_pct < 0:
            raise ValueError("El padding no puede ser negativo.")
        if self.model_path is not None and not self.model_path.is_file():
            raise ValueError(
                f"No se encontró el modelo YOLO: {self.model_path}"
            )
