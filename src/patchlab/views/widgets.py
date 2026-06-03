"""Widgets reutilizables de la interfaz."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


class ImagePanel(QLabel):
    """
    Panel que muestra un ``QPixmap`` escalándolo al tamaño disponible.

    Conserva el pixmap original y lo reescala en cada redibujado para mantener
    la relación de aspecto sin degradar la fuente. El modo de transformación es
    configurable: ``FastTransformation`` (nítido, ideal para parches con zoom)
    o ``SmoothTransformation`` (suave, ideal para la vista de contexto).
    """

    def __init__(
        self,
        transformation: Qt.TransformationMode = Qt.TransformationMode.SmoothTransformation,
        parent: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self._source: Optional[QPixmap] = None
        self._transformation = transformation
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_image(self, pixmap: QPixmap) -> None:
        """Define el pixmap a mostrar y lo reescala de inmediato."""
        self._source = pixmap
        self._rescale()

    def clear_image(self) -> None:
        """Elimina la imagen mostrada."""
        self._source = None
        self.clear()

    def resizeEvent(self, event) -> None:  # noqa: N802 — API de Qt.
        """Reescala el pixmap cuando el panel cambia de tamaño."""
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        """Ajusta el pixmap original al tamaño actual conservando el aspecto."""
        if self._source is None:
            return
        scaled = self._source.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            self._transformation,
        )
        self.setPixmap(scaled)
