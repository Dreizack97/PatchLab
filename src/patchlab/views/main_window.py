"""Ventana principal de etiquetado.

Es una vista "tonta": no contiene lógica de negocio. Observa las señales del
:class:`LabelingController` para pintar cada fotograma y reenvía las acciones
del usuario (teclado o botones) al controlador.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from patchlab.controllers.controller import FrameData, LabelingController
from patchlab.models.config import LabelerConfig
from patchlab.services.shortcuts import build_keymap
from patchlab.views.image_utils import bgr_to_qpixmap
from patchlab.views.widgets import ImagePanel

# Teclas no asociadas a clases: omitir, deshacer y salir.
_SKIP_KEYS = {Qt.Key.Key_S}
_UNDO_KEYS = {Qt.Key.Key_U, Qt.Key.Key_Backspace}
_QUIT_KEYS = {Qt.Key.Key_Q, Qt.Key.Key_Escape}


class MainWindow(QMainWindow):
    """Interfaz interactiva para etiquetar parches con atajos de teclado."""

    def __init__(
        self, controller: LabelingController, config: LabelerConfig
    ) -> None:
        """
        Args:
            controller: Controlador que orquesta la sesión.
            config: Configuración activa (para construir los atajos).
        """
        super().__init__()
        self._controller = controller
        self._config = config
        # Mapa carácter→etiqueta y su inverso para resolver pulsaciones.
        self._keymap: Dict[str, str] = build_keymap(config.labels)

        self.setWindowTitle("PatchLab — Etiquetado secuencial")
        self.resize(1180, 720)

        self._build_ui()
        self._connect_controller()

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """Ensambla la jerarquía de widgets de la ventana."""
        central = QWidget()
        root = QVBoxLayout(central)

        root.addLayout(self._build_progress_bar())
        root.addWidget(self._build_image_area(), stretch=1)
        root.addWidget(self._build_label_bar())

        self._status = self.statusBar()
        self._status.showMessage("Listo.")
        self.setCentralWidget(central)

    def _build_progress_bar(self) -> QVBoxLayout:
        """Crea las barras y rótulos de progreso (imagen y parche)."""
        layout = QVBoxLayout()

        self._info_label = QLabel("—")
        self._info_label.setStyleSheet("font-weight: 600;")

        self._image_progress = QProgressBar()
        self._image_progress.setFormat("Imágenes: %v / %m")
        self._patch_progress = QProgressBar()
        self._patch_progress.setFormat("Parches: %v / %m")

        layout.addWidget(self._info_label)
        layout.addWidget(self._image_progress)
        layout.addWidget(self._patch_progress)
        return layout

    def _build_image_area(self) -> QWidget:
        """Crea el área dividida: parche (izq.) y contexto (der.)."""
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._patch_panel = ImagePanel(
            transformation=Qt.TransformationMode.FastTransformation
        )
        self._context_panel = ImagePanel(
            transformation=Qt.TransformationMode.SmoothTransformation
        )

        patch_box = self._wrap_in_group("Parche actual", self._patch_panel)
        context_box = self._wrap_in_group(
            "Contexto original", self._context_panel
        )

        splitter.addWidget(patch_box)
        splitter.addWidget(context_box)
        splitter.setSizes([420, 760])
        return splitter

    @staticmethod
    def _wrap_in_group(title: str, panel: ImagePanel) -> QGroupBox:
        """Envuelve un panel de imagen en un recuadro con título."""
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.addWidget(panel)
        return box

    def _build_label_bar(self) -> QWidget:
        """Crea la barra inferior de botones de etiqueta y acciones."""
        container = QWidget()
        layout = QHBoxLayout(container)

        # Un botón por etiqueta, con su atajo visible.
        self._label_buttons: Dict[str, QPushButton] = {}
        for char, label in self._keymap.items():
            button = QPushButton(f"[{char.upper()}]  {label}")
            button.setToolTip(f"Asignar «{label}» (tecla {char.upper()})")
            button.clicked.connect(
                lambda _checked=False, lbl=label: self._controller.apply_label(lbl)
            )
            self._label_buttons[label] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self._add_action_button(layout, "[S]  Omitir", self._controller.skip)
        self._add_action_button(layout, "[U]  Deshacer", self._controller.undo)
        self._add_action_button(layout, "[Q]  Salir", self._on_quit_clicked)
        return container

    def _add_action_button(self, layout: QHBoxLayout, text: str, slot) -> None:
        """Añade un botón de acción (omitir/deshacer/salir) al layout."""
        button = QPushButton(text)
        button.clicked.connect(slot)
        layout.addWidget(button)

    # ------------------------------------------------------------------ #
    # Conexión con el controlador
    # ------------------------------------------------------------------ #
    def _connect_controller(self) -> None:
        """Suscribe la vista a las señales del controlador."""
        self._controller.frameReady.connect(self._on_frame_ready)
        self._controller.statusMessage.connect(self._status.showMessage)
        self._controller.finished.connect(self._on_finished)

    # ------------------------------------------------------------------ #
    # Reacciones a las señales del controlador
    # ------------------------------------------------------------------ #
    def _on_frame_ready(self, frame: FrameData) -> None:
        """Pinta el fotograma recibido y actualiza el progreso."""
        self._patch_panel.set_image(bgr_to_qpixmap(frame.patch_image))
        self._context_panel.set_image(bgr_to_qpixmap(frame.context_image))

        self._info_label.setText(
            f"Archivo: {frame.file_name}    "
            f"Parche {frame.patch_index + 1} de {frame.patch_total}"
        )
        self._image_progress.setMaximum(frame.image_total)
        self._image_progress.setValue(frame.image_index + 1)
        self._patch_progress.setMaximum(frame.patch_total)
        self._patch_progress.setValue(frame.patch_index + 1)

        self._highlight_suggestion(
            frame.suggested_label, frame.suggested_confidence
        )

    def _highlight_suggestion(
        self, label: Optional[str], confidence: float
    ) -> None:
        """Resalta el botón de la clase sugerida por el modelo (si la hay)."""
        for lbl, button in self._label_buttons.items():
            if lbl == label:
                button.setStyleSheet("font-weight: 700; border: 2px solid #3a9;")
                button.setText(
                    f"[{self._char_for(lbl)}]  {lbl}  ★ {confidence:.0%}"
                )
            else:
                button.setStyleSheet("")
                button.setText(f"[{self._char_for(lbl)}]  {lbl}")

    def _char_for(self, label: str) -> str:
        """Devuelve, en mayúscula, el atajo de teclado de una etiqueta."""
        for char, lbl in self._keymap.items():
            if lbl == label:
                return char.upper()
        return "?"

    def _on_finished(self, summary: str) -> None:
        """Muestra el resumen final y cierra la ventana."""
        QMessageBox.information(self, "Proceso finalizado", summary)
        self.close()

    # ------------------------------------------------------------------ #
    # Entrada de teclado
    # ------------------------------------------------------------------ #
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — API Qt.
        """Traduce las pulsaciones de teclado en acciones del controlador."""
        key = event.key()
        if key in _QUIT_KEYS:
            self._on_quit_clicked()
            return
        if key in _UNDO_KEYS:
            self._controller.undo()
            return
        if key in _SKIP_KEYS:
            self._controller.skip()
            return

        char = event.text().lower()
        if char in self._keymap:
            self._controller.apply_label(self._keymap[char])
            return

        super().keyPressEvent(event)

    def _on_quit_clicked(self) -> None:
        """Pide confirmación antes de finalizar la sesión."""
        reply = QMessageBox.question(
            self,
            "Salir",
            "¿Finalizar la sesión de etiquetado?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._controller.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — API Qt.
        """Garantiza el apagado ordenado del hilo de extracción."""
        self._controller.shutdown()
        super().closeEvent(event)
