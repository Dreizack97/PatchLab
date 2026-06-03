"""Tema visual de la aplicación con soporte claro/oscuro automático.

Usa el estilo *Fusion* (idéntico en los tres sistemas operativos) y deriva la
paleta del esquema de color del sistema cuando PySide6 lo expone
(``Qt.ColorScheme``), con un respaldo a tema oscuro en versiones anteriores.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Acento corporativo (azul) reutilizado en botones y selección.
_ACCENT = QColor(56, 132, 255)


def _is_dark(app: QApplication) -> bool:
    """Determina si el sistema usa un esquema de color oscuro."""
    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if callable(scheme):
        try:
            return scheme() == Qt.ColorScheme.Dark
        except (AttributeError, TypeError):
            pass
    # Respaldo para PySide6 < 6.5: asumir oscuro.
    return True


def _build_palette(dark: bool) -> QPalette:
    """Construye la paleta de colores para el modo indicado."""
    palette = QPalette()
    if dark:
        window, base, text = QColor(30, 31, 34), QColor(43, 45, 49), QColor(230, 230, 230)
        alt = QColor(53, 55, 60)
    else:
        window, base, text = QColor(245, 246, 248), QColor(255, 255, 255), QColor(25, 25, 25)
        alt = QColor(235, 236, 239)

    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, alt)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Button, alt)
    palette.setColor(QPalette.ColorRole.ToolTipBase, base)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Highlight, _ACCENT)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    return palette


def apply_theme(app: QApplication) -> None:
    """
    Aplica el estilo y la paleta a toda la aplicación.

    Args:
        app: Instancia de ``QApplication`` en ejecución.
    """
    app.setStyle("Fusion")
    app.setPalette(_build_palette(_is_dark(app)))
    app.setStyleSheet(
        """
        QPushButton {
            padding: 8px 14px;
            border-radius: 8px;
            border: 1px solid rgba(128, 128, 128, 0.35);
        }
        QPushButton:hover { border-color: rgba(56, 132, 255, 0.9); }
        QPushButton:pressed { background-color: rgba(56, 132, 255, 0.35); }
        QProgressBar {
            border: 1px solid rgba(128, 128, 128, 0.35);
            border-radius: 6px;
            text-align: center;
            height: 16px;
        }
        QProgressBar::chunk {
            background-color: #3884ff;
            border-radius: 5px;
        }
        """
    )
