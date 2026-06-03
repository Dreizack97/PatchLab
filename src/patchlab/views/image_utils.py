"""Conversión de imágenes OpenCV (BGR/NumPy) a objetos de Qt."""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap


def bgr_to_qpixmap(image: np.ndarray) -> QPixmap:
    """
    Convierte una imagen BGR de OpenCV en un ``QPixmap`` RGB.

    Args:
        image: Matriz BGR (``uint8``) de 3 canales.

    Returns:
        ``QPixmap`` independiente de la memoria NumPy de origen.
    """
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    height, width, channels = rgb.shape
    bytes_per_line = channels * width
    qimage = QImage(
        rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888
    )
    # ``copy`` desliga el QPixmap del búfer NumPy temporal (evita corrupción).
    return QPixmap.fromImage(qimage.copy())
