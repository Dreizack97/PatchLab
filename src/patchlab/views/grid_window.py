"""Ventana del modo de etiquetado por clic (cuadrícula interactiva).

Vista "tonta": observa las señales del :class:`GridController` y le reenvía las
intenciones del usuario (clic en celdas, selección de clase activa, llenado,
deshacer/rehacer, avanzar). Toda la lógica vive en el controlador y el modelo.

Atajos de teclado:
- ``1``..``9`` / letras : fijar la clase activa (selección "sticky").
- ``Tab``               : alternar a la siguiente clase activa.
- ``F``                 : etiquetar las celdas restantes con la clase activa.
- ``Ctrl+Z`` / ``Ctrl+Y`` (o ``Ctrl+Shift+Z``) : deshacer / rehacer.
- ``Enter``             : guardar y pasar a la siguiente imagen.
- ``Esc`` / ``Q``       : finalizar la sesión.
"""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from patchlab.controllers.grid_controller import GridController, GridFrame
from patchlab.models.config import LabelerConfig
from patchlab.services.color import label_color_rgb
from patchlab.services.shortcuts import build_keymap
from patchlab.views.grid_canvas import GridCanvas

_UNDO_KEYS = {Qt.Key.Key_Z}
_REDO_KEYS = {Qt.Key.Key_Y}
_QUIT_KEYS = {Qt.Key.Key_Q, Qt.Key.Key_Escape}
_NEXT_KEYS = {Qt.Key.Key_Return, Qt.Key.Key_Enter}


class GridWindow(QMainWindow):
    """Interfaz de etiquetado por clic con clase fija y llenado automático."""

    def __init__(
        self, controller: GridController, config: LabelerConfig
    ) -> None:
        """
        Args:
            controller: Controlador que orquesta la sesión por cuadrícula.
            config: Configuración activa (para construir clases y atajos).
        """
        super().__init__()
        self._controller = controller
        self._config = config
        self._keymap: Dict[str, str] = build_keymap(config.labels)
        self._class_buttons: Dict[str, QPushButton] = {}

        self.setWindowTitle("PatchLab — Etiquetado por cuadrícula")
        self.resize(1180, 760)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self._connect_controller()
        self._sync_active_class(controller.active_class)

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """Ensambla el lienzo y el panel lateral de controles."""
        central = QWidget()
        layout = QHBoxLayout(central)

        self._canvas = GridCanvas(color_fn=label_color_rgb)
        self._canvas.cellPainted.connect(self._controller.paint_cell)
        self._canvas.cellCleared.connect(self._controller.clear_cell)
        layout.addWidget(self._canvas, stretch=1)
        layout.addWidget(self._build_sidebar())

        self._status = self.statusBar()
        self._status.showMessage("Listo.")
        self.setCentralWidget(central)

    def _build_sidebar(self) -> QWidget:
        """Construye el panel lateral con clases, llenado, historial y avance."""
        sidebar = QWidget()
        sidebar.setFixedWidth(280)
        layout = QVBoxLayout(sidebar)

        layout.addWidget(self._build_class_group())
        layout.addWidget(self._build_fill_group())
        layout.addWidget(self._build_history_group())
        layout.addStretch(1)
        layout.addWidget(self._build_progress_group())
        layout.addWidget(self._build_navigation_group())
        return sidebar

    def _build_class_group(self) -> QGroupBox:
        """Lista de clases; la activa queda marcada (modo "pintar")."""
        box = QGroupBox("Clase activa (Pintar)")
        layout = QVBoxLayout(box)
        self._class_group = QButtonGroup(self)
        self._class_group.setExclusive(True)

        for char, label in self._keymap.items():
            button = QPushButton(f"[{char.upper()}]  {label}")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(
                lambda _checked=False, lbl=label: self._controller.set_active_class(lbl)
            )
            self._class_group.addButton(button)
            self._class_buttons[label] = button
            layout.addWidget(button)
        return box

    def _build_fill_group(self) -> QGroupBox:
        """Desplegable + botón para etiquetar las celdas restantes."""
        box = QGroupBox("Llenado automático")
        layout = QVBoxLayout(box)

        self._fill_combo = QComboBox()
        self._fill_combo.addItems(self._config.labels)
        self._fill_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        fill_button = QPushButton("Etiquetar resto de la grilla  [F]")
        fill_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fill_button.clicked.connect(
            lambda: self._controller.fill_remaining(self._fill_combo.currentText())
        )

        layout.addWidget(self._fill_combo)
        layout.addWidget(fill_button)
        return box

    def _build_history_group(self) -> QGroupBox:
        """Botones de deshacer y rehacer."""
        box = QGroupBox("Historial")
        layout = QHBoxLayout(box)

        self._undo_button = QPushButton("↶ Deshacer")
        self._redo_button = QPushButton("↷ Rehacer")
        for button, slot in (
            (self._undo_button, self._controller.undo),
            (self._redo_button, self._controller.redo),
        ):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setEnabled(False)
            button.clicked.connect(slot)
            layout.addWidget(button)
        return box

    def _build_progress_group(self) -> QGroupBox:
        """Indicadores de progreso (imagen actual y celdas)."""
        box = QGroupBox("Progreso")
        layout = QVBoxLayout(box)

        self._info_label = QLabel("—")
        self._info_label.setWordWrap(True)
        self._image_progress = QProgressBar()
        self._image_progress.setFormat("Imágenes: %v / %m")

        layout.addWidget(self._info_label)
        layout.addWidget(self._image_progress)
        return box

    def _build_navigation_group(self) -> QWidget:
        """Botones de avanzar de imagen y salir."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        next_button = QPushButton("Guardar y siguiente  [Enter]")
        next_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        next_button.clicked.connect(self._controller.confirm_and_next)

        quit_button = QPushButton("Salir  [Esc]")
        quit_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        quit_button.clicked.connect(self._on_quit_clicked)

        layout.addWidget(next_button)
        layout.addWidget(quit_button)
        return container

    # ------------------------------------------------------------------ #
    # Conexión con el controlador
    # ------------------------------------------------------------------ #
    def _connect_controller(self) -> None:
        """Suscribe la vista a las señales del controlador."""
        self._controller.gridReady.connect(self._on_grid_ready)
        self._controller.overlayChanged.connect(self._canvas.refresh)
        self._controller.activeClassChanged.connect(self._sync_active_class)
        self._controller.historyChanged.connect(self._on_history_changed)
        self._controller.statusMessage.connect(self._status.showMessage)
        self._controller.busyChanged.connect(self._on_busy_changed)
        self._controller.finished.connect(self._on_finished)

    # ------------------------------------------------------------------ #
    # Reacciones a las señales del controlador
    # ------------------------------------------------------------------ #
    def _on_grid_ready(self, frame: GridFrame) -> None:
        """Carga una nueva imagen en el lienzo y actualiza el progreso."""
        self._canvas.set_frame(frame.image, frame.session.patches)
        self._info_label.setText(
            f"Archivo: {frame.file_name}\n{frame.session.total} celdas"
        )
        self._image_progress.setMaximum(frame.image_total)
        self._image_progress.setValue(frame.image_index + 1)

    def _sync_active_class(self, label: str) -> None:
        """Refleja la clase activa en los botones, el combo y el lienzo."""
        button = self._class_buttons.get(label)
        if button is not None:
            button.setChecked(True)
        self._fill_combo.setCurrentText(label)
        self._canvas.set_active_class(label)

    def _on_history_changed(self, can_undo: bool, can_redo: bool) -> None:
        """Habilita o deshabilita los botones de deshacer/rehacer."""
        self._undo_button.setEnabled(can_undo)
        self._redo_button.setEnabled(can_redo)

    def _on_busy_changed(self, busy: bool) -> None:
        """Bloquea la interacción mientras se guarda en segundo plano."""
        self.centralWidget().setEnabled(not busy)

    def _on_finished(self, summary: str) -> None:
        """Muestra el resumen final y cierra la ventana."""
        QMessageBox.information(self, "Proceso finalizado", summary)
        self.close()

    # ------------------------------------------------------------------ #
    # Entrada de teclado
    # ------------------------------------------------------------------ #
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — API Qt.
        """Traduce las pulsaciones en intenciones del controlador."""
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if ctrl and key in _UNDO_KEYS and not shift:
            self._controller.undo()
            return
        if ctrl and (key in _REDO_KEYS or (key in _UNDO_KEYS and shift)):
            self._controller.redo()
            return
        if key == Qt.Key.Key_Tab:
            self._controller.cycle_active_class()
            return
        if key == Qt.Key.Key_F:
            self._controller.fill_remaining()
            return
        if key in _NEXT_KEYS:
            self._controller.confirm_and_next()
            return
        if key in _QUIT_KEYS:
            self._on_quit_clicked()
            return

        char = event.text().lower()
        if char in self._keymap:
            self._controller.set_active_class(self._keymap[char])
            return

        super().keyPressEvent(event)

    def _on_quit_clicked(self) -> None:
        """Pide confirmación antes de finalizar la sesión."""
        reply = QMessageBox.question(
            self,
            "Salir",
            "¿Finalizar la sesión? La imagen actual no se guardará.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._controller.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — API Qt.
        """Garantiza el apagado ordenado del hilo secundario."""
        self._controller.shutdown()
        super().closeEvent(event)
