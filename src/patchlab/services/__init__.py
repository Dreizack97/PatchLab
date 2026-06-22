"""Capa de Servicios: lógica de negocio reutilizable y sin estado de UI."""

from patchlab.services.color import label_color_bgr, label_color_rgb
from patchlab.services.extractor import (
    GridPatchExtractor,
    PatchExtractor,
    YoloPatchExtractor,
    create_extractor,
)
from patchlab.services.image_loader import VALID_EXTENSIONS, find_images
from patchlab.services.shortcuts import KEY_CHARS, build_keymap, shortcut_for

__all__ = [
    "label_color_bgr",
    "label_color_rgb",
    "PatchExtractor",
    "GridPatchExtractor",
    "YoloPatchExtractor",
    "create_extractor",
    "VALID_EXTENSIONS",
    "find_images",
    "KEY_CHARS",
    "build_keymap",
    "shortcut_for",
]
