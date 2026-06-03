"""Lienzo interactivo de la cuadrícula etiquetable.

Dibuja la imagen actual y, encima, una rejilla de celdas (una por parche). Cada
celda etiquetada se rellena con el color de su clase (translúcido) y un borde
sólido, dando *feedback* visual instantáneo. Al pulsar el ratón se traduce la
coordenada del widget a coordenadas de imagen para localizar la celda y emitir
la señal correspondiente; la decisión de qué etiqueta aplicar es del controlador.

Gestión de eventos:
- ``paintEvent``  : redibuja imagen + overlay (sin regenerar mapas de bits, de
                    modo que repintar miles de celdas sea barato).
- ``mousePressEvent`` : clic izquierdo → ``cellPainted``; derecho → ``cellCleared``.
- El mapeo widget↔imagen se centraliza en :meth:`_geometry` (escalado con
  *letterbox* que conserva la relación de aspecto).
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from patchlab.models.patch import Patch
from patchlab.views.image_utils import bgr_to_qpixmap

# Tipo de la función que asigna un color RGB a una etiqueta.
ColorFn = Callable[[str], Tuple[int, int, int]]

# Apariencia del overlay.
_FILL_ALPHA = 90              # Transparencia del relleno de una celda etiquetada.
_LABELED_BORDER = 2           # Grosor del borde de una celda etiquetada.
_GRID_PEN = QColor(255, 255, 255, 45)   # Rejilla tenue para celdas vacías.
_MIN_LABEL_PX = 30            # Tamaño mínimo en pantalla para rotular la celda.


class GridCanvas(QWidget):
    """Widget que muestra la cuadrícula y captura los clics sobre las celdas."""

    #: Emitida con el índice de celda al hacer clic izquierdo (pintar).
    cellPainted = Signal(int)
    #: Emitida con el índice de celda al hacer clic derecho (limpiar).
    cellCleared = Signal(int)

    def __init__(
        self, color_fn: ColorFn, parent: Optional[QWidget] = None
    ) -> None:
        """
        Args:
            color_fn: Función que devuelve el color RGB de una etiqueta.
            parent: Widget padre, si lo hay.
        """
        super().__init__(parent)
        self._color_fn = color_fn
        self._pixmap: Optional[QPixmap] = None
        self._patches: List[Patch] = []
        self._image_w = 0
        self._image_h = 0
        self._active_class = ""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMinimumSize(480, 480)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def set_frame(self, image: np.ndarray, patches: List[Patch]) -> None:
        """Carga una nueva imagen con sus celdas y redibuja."""
        self._pixmap = bgr_to_qpixmap(image)
        self._patches = patches
        self._image_h, self._image_w = image.shape[:2]
        self.update()

    def set_active_class(self, label: str) -> None:
        """Registra la clase activa (para rotular el cursor/celdas si procede)."""
        self._active_class = label
        self.update()

    def refresh(self) -> None:
        """Solicita un repintado del overlay tras un cambio del modelo."""
        self.update()

    # ------------------------------------------------------------------ #
    # Dibujo
    # ------------------------------------------------------------------ #
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — API Qt.
        """Pinta la imagen de fondo y el overlay de celdas."""
        painter = QPainter(self)
        if self._pixmap is None:
            return

        scale, off_x, off_y = self._geometry()
        painter.drawPixmap(
            QRectF(off_x, off_y, self._image_w * scale, self._image_h * scale),
            self._pixmap,
            QRectF(self._pixmap.rect()),
        )

        for patch in self._patches:
            rect = QRectF(
                off_x + patch.x * scale,
                off_y + patch.y * scale,
                patch.w * scale,
                patch.h * scale,
            )
            if patch.label is None:
                painter.setPen(QPen(_GRID_PEN, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)
            else:
                self._draw_labeled_cell(painter, rect, patch.label)

    def _draw_labeled_cell(
        self, painter: QPainter, rect: QRectF, label: str
    ) -> None:
        """Dibuja el relleno, el borde y (si cabe) el rótulo de una celda."""
        r, g, b = self._color_fn(label)
        painter.fillRect(rect, QColor(r, g, b, _FILL_ALPHA))
        painter.setPen(QPen(QColor(r, g, b), _LABELED_BORDER))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        if rect.width() >= _MIN_LABEL_PX and rect.height() >= _MIN_LABEL_PX:
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    # ------------------------------------------------------------------ #
    # Eventos de ratón
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — API Qt.
        """Traduce el clic a una celda y emite la señal correspondiente."""
        index = self._cell_at(event.position())
        if index is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.cellPainted.emit(index)
        elif event.button() == Qt.MouseButton.RightButton:
            self.cellCleared.emit(index)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — API Qt.
        """Permite "pintar arrastrando" con el botón izquierdo presionado."""
        if event.buttons() & Qt.MouseButton.LeftButton:
            index = self._cell_at(event.position())
            if index is not None:
                self.cellPainted.emit(index)

    # ------------------------------------------------------------------ #
    # Geometría (mapeo widget ↔ imagen)
    # ------------------------------------------------------------------ #
    def _geometry(self) -> Tuple[float, float, float]:
        """
        Calcula el escalado y desplazamiento para encajar la imagen (letterbox).

        Returns:
            Terna ``(escala, offset_x, offset_y)`` en píxeles de widget.
        """
        if self._image_w == 0 or self._image_h == 0:
            return 1.0, 0.0, 0.0
        scale = min(self.width() / self._image_w, self.height() / self._image_h)
        off_x = (self.width() - self._image_w * scale) / 2
        off_y = (self.height() - self._image_h * scale) / 2
        return scale, off_x, off_y

    def _cell_at(self, pos: QPointF) -> Optional[int]:
        """
        Devuelve el índice de la celda situada bajo un punto del widget.

        Args:
            pos: Posición del cursor en coordenadas del widget.

        Returns:
            Índice del parche, o ``None`` si el punto cae fuera de toda celda.
        """
        scale, off_x, off_y = self._geometry()
        if scale <= 0:
            return None
        img_x = (pos.x() - off_x) / scale
        img_y = (pos.y() - off_y) / scale
        if not (0 <= img_x < self._image_w and 0 <= img_y < self._image_h):
            return None

        for index, patch in enumerate(self._patches):
            if (
                patch.x <= img_x < patch.x + patch.w
                and patch.y <= img_y < patch.y + patch.h
            ):
                return index
        return None
