"""Utilidades de geometría para el recorte de regiones segmentadas.

Funciones puras sobre matrices NumPy/OpenCV empleadas por el extractor YOLO para
convertir polígonos de segmentación en recortes con su máscara binaria local.
"""

from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np


def clip_box(
    box: np.ndarray, width: int, height: int
) -> Tuple[int, int, int, int]:
    """
    Restringe una caja delimitadora a los límites de la imagen.

    Args:
        box: Arreglo con coordenadas ``[x1, y1, x2, y2]``.
        width: Ancho máximo de la imagen.
        height: Alto máximo de la imagen.

    Returns:
        Coordenadas enteras seguras ``(x1, y1, x2, y2)``.
    """
    x1, y1, x2, y2 = box[:4].astype(float)
    return (
        max(0, min(width - 1, int(np.floor(x1)))),
        max(0, min(height - 1, int(np.floor(y1)))),
        max(1, min(width, int(np.ceil(x2)))),
        max(1, min(height, int(np.ceil(y2)))),
    )


def build_crop_and_mask(
    image: np.ndarray,
    polygon: np.ndarray,
    box_xyxy: Optional[np.ndarray],
    padding_pct: float = 0.0,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Tuple[int, int, int, int]]:
    """
    Extrae un recorte de la imagen y genera su máscara binaria local.

    Permite expandir el recorte un porcentaje (``padding_pct``) para incluir más
    contexto visual alrededor de la región segmentada; la máscara se dilata en
    consecuencia para que ese contexto extra quede visible.

    Args:
        image: Fotograma de origen (BGR).
        polygon: Coordenadas del polígono segmentado.
        box_xyxy: Caja delimitadora ``[x1, y1, x2, y2]``, si está disponible.
        padding_pct: Expansión fraccional hacia fuera del recorte (0.1 = 10 %).

    Returns:
        Terna ``(recorte_bgr, máscara, (x1, y1, x2, y2))``. El recorte y la
        máscara son ``None`` si la región resultante es inválida o vacía.
    """
    h, w = image.shape[:2]

    if box_xyxy is not None:
        bx1, by1, bx2, by2 = box_xyxy[:4].astype(float)
    else:
        bx1, by1 = np.min(polygon[:, 0]), np.min(polygon[:, 1])
        bx2, by2 = np.max(polygon[:, 0]), np.max(polygon[:, 1])

    pad_x_int = 0
    pad_y_int = 0

    # 1. Expandir el cuadro delimitador para incluir contexto extra.
    if padding_pct > 0:
        bw = bx2 - bx1
        bh = by2 - by1
        pad_x = bw * padding_pct
        pad_y = bh * padding_pct

        pad_x_int = max(1, int(round(pad_x)))
        pad_y_int = max(1, int(round(pad_y)))

        bx1 -= pad_x
        by1 -= pad_y
        bx2 += pad_x
        by2 += pad_y

    x1, y1, x2, y2 = clip_box(np.array([bx1, by1, bx2, by2]), w, h)

    crop_img = image[y1:y2, x1:x2]
    if crop_img.size == 0:
        return None, None, (x1, y1, x2, y2)

    local_poly = np.round(polygon - [x1, y1]).astype(np.int32)
    crop_mask = np.zeros(crop_img.shape[:2], dtype=np.uint8)
    cv2.fillPoly(crop_mask, [local_poly], 255)

    # 2. Dilatar la máscara para que el contexto extra sea visible.
    if padding_pct > 0 and pad_x_int > 0 and pad_y_int > 0:
        k_size_x = pad_x_int * 2 + 1
        k_size_y = pad_y_int * 2 + 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (k_size_x, k_size_y)
        )
        crop_mask = cv2.dilate(crop_mask, kernel, iterations=1)

    if np.count_nonzero(crop_mask) == 0:
        return None, None, (x1, y1, x2, y2)

    return crop_img, crop_mask, (x1, y1, x2, y2)
