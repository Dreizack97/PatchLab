"""Ventana del etiquetado por cuadrícula, con sesión colaborativa distribuida.

Vista "tonta": observa las señales del controlador (local del Host o remoto del
Colaborador, misma interfaz :class:`GridControllerLike`) y le reenvía las
intenciones del usuario. Añade la interfaz del **flujo distribuido**:

- *Lobby*: participantes conectados, tamaño del dataset y, solo para el Host, el
  botón «Comenzar Etiquetado».
- *Panel supervisor*: progreso por trabajador en tiempo real.
- El etiquetado permanece **bloqueado** hasta que el Host arranca la sesión.

Atajos de teclado (durante la fase de etiquetado): ``1..9``/letras fijan la clase
activa, ``Tab`` alterna, ``F`` rellena, ``Ctrl+Z``/``Ctrl+Y`` deshacen/rehacen,
``Enter`` confirma y pide la siguiente imagen, ``Esc``/``Q`` finaliza.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from patchlab.collab.coordinator import SessionCoordinator
from patchlab.collab.net_utils import DEFAULT_PORT, local_ip, make_token
from patchlab.collab.server import CollabServer
from patchlab.collab.session import SessionPhase
from patchlab.controllers.grid_controller import GridFrame
from patchlab.controllers.interfaces import GridControllerLike
from patchlab.models.config import LabelerConfig
from patchlab.services.color import label_color_rgb
from patchlab.services.shortcuts import build_keymap
from patchlab.views.grid_canvas import GridCanvas

_UNDO_KEYS = {Qt.Key.Key_Z}
_REDO_KEYS = {Qt.Key.Key_Y}
_QUIT_KEYS = {Qt.Key.Key_Q, Qt.Key.Key_Escape}
_NEXT_KEYS = {Qt.Key.Key_Return, Qt.Key.Key_Enter}

_PHASE_TEXT = {
    SessionPhase.LOBBY.value: "Lobby — esperando al Host",
    SessionPhase.LABELING.value: "Etiquetando",
    SessionPhase.FINISHED.value: "Sesión finalizada",
}


class GridWindow(QMainWindow):
    """Interfaz de etiquetado por cuadrícula con sesión colaborativa distribuida."""

    def __init__(
        self,
        controller: GridControllerLike,
        config: LabelerConfig,
        *,
        is_collaborator: bool = False,
        coordinator: Optional[SessionCoordinator] = None,
    ) -> None:
        """
        Args:
            controller: Controlador de etiquetado (``coordinator.local`` en el
                Host; ``RemoteGridController`` en el Colaborador).
            config: Configuración activa (clases y atajos).
            is_collaborator: ``True`` para la ventana de un colaborador.
            coordinator: Coordinador de la sesión (obligatorio en el Host).
        """
        super().__init__()
        self._controller = controller
        self._config = config
        self._is_collaborator = is_collaborator
        self._coordinator = coordinator
        # Objeto que expone las señales del flujo distribuido (fase/lobby/progreso).
        self._session = controller if is_collaborator else coordinator
        self._keymap: Dict[str, str] = build_keymap(config.labels)
        self._class_buttons: Dict[str, QPushButton] = {}
        self._server: Optional[CollabServer] = None

        title = "Colaborador" if is_collaborator else "Host (supervisor + trabajador)"
        self.setWindowTitle(f"PatchLab — {title}")
        self.resize(1180, 760)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self._connect_controller()
        self._sync_active_class(controller.active_class)
        # Arranca bloqueado: nadie etiqueta hasta que el Host inicia la sesión.
        self._apply_phase(SessionPhase.LOBBY.value)

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
        """Construye el panel lateral con clases, llenado, historial y colaboración."""
        sidebar = QWidget()
        sidebar.setFixedWidth(310)
        layout = QVBoxLayout(sidebar)

        self._class_box = self._build_class_group()
        self._fill_group = self._build_fill_group()
        self._history_group = self._build_history_group()
        layout.addWidget(self._class_box)
        layout.addWidget(self._fill_group)
        layout.addWidget(self._history_group)
        layout.addWidget(self._build_collab_group())
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
        """Indicadores de progreso (imagen actual y shard)."""
        box = QGroupBox("Progreso")
        layout = QVBoxLayout(box)

        self._info_label = QLabel("—")
        self._info_label.setWordWrap(True)
        self._image_progress = QProgressBar()
        self._image_progress.setFormat("Mi porción: %v / %m")

        layout.addWidget(self._info_label)
        layout.addWidget(self._image_progress)
        return box

    def _build_navigation_group(self) -> QWidget:
        """Botones de confirmar imagen y salir."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self._next_button = QPushButton("Confirmar y siguiente  [Enter]")
        self._next_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._next_button.clicked.connect(self._controller.confirm_and_next)

        quit_button = QPushButton("Salir  [Esc]")
        quit_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        quit_button.clicked.connect(self._on_quit_clicked)

        layout.addWidget(self._next_button)
        layout.addWidget(quit_button)
        return container

    # ------------------------------------------------------------------ #
    # Panel de sesión colaborativa (lobby + supervisión)
    # ------------------------------------------------------------------ #
    def _build_collab_group(self) -> QGroupBox:
        """Panel de colaboración: controles de Host o estado de Colaborador."""
        box = QGroupBox("Sesión colaborativa")
        layout = QVBoxLayout(box)

        self._phase_label = QLabel("—")
        self._phase_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._phase_label)

        if self._is_collaborator:
            self._build_collaborator_controls(layout)
        else:
            self._build_host_controls(layout)

        layout.addWidget(QLabel("Participantes:"))
        self._collab_list = QListWidget()
        self._collab_list.setMaximumHeight(80)
        self._collab_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._collab_list)

        layout.addWidget(QLabel("Progreso por trabajador:"))
        self._dashboard = QListWidget()
        self._dashboard.setMaximumHeight(110)
        self._dashboard.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._dashboard)
        return box

    def _build_host_controls(self, layout: QVBoxLayout) -> None:
        """Controles del Host: servidor + arranque de la distribución."""
        self._token_edit = QLineEdit(make_token())
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(DEFAULT_PORT)
        self._port_spin.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        creds = QHBoxLayout()
        creds.addWidget(QLabel("Token:"))
        creds.addWidget(self._token_edit, stretch=1)
        layout.addLayout(creds)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Puerto:"))
        port_row.addWidget(self._port_spin, stretch=1)
        layout.addLayout(port_row)

        self._start_server_button = QPushButton("Iniciar servidor")
        self._start_server_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._start_server_button.clicked.connect(self._on_start_server)
        self._stop_server_button = QPushButton("Detener sesión")
        self._stop_server_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stop_server_button.setEnabled(False)
        self._stop_server_button.clicked.connect(self._on_stop_server)
        layout.addWidget(self._start_server_button)
        layout.addWidget(self._stop_server_button)

        self._server_info = QLabel("Servidor detenido.")
        self._server_info.setWordWrap(True)
        self._server_info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._server_info)

        total = self._coordinator.total_images() if self._coordinator else 0
        layout.addWidget(QLabel(f"Dataset: {total} imágenes."))

        self._start_label_button = QPushButton("Comenzar Etiquetado")
        self._start_label_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._start_label_button.clicked.connect(self._on_start_labeling)
        layout.addWidget(self._start_label_button)

    def _build_collaborator_controls(self, layout: QVBoxLayout) -> None:
        """Indicadores del Colaborador: estado y progreso propio."""
        self._collab_status = QLabel("Conectando…")
        self._collab_status.setWordWrap(True)
        layout.addWidget(self._collab_status)

    # ------------------------------------------------------------------ #
    # Conexión con el controlador y la sesión
    # ------------------------------------------------------------------ #
    def _connect_controller(self) -> None:
        """Suscribe la vista a las señales del controlador y de la sesión."""
        self._controller.gridReady.connect(self._on_grid_ready)
        self._controller.overlayChanged.connect(self._canvas.refresh)
        self._controller.activeClassChanged.connect(self._sync_active_class)
        self._controller.historyChanged.connect(self._on_history_changed)
        self._controller.statusMessage.connect(self._status.showMessage)
        self._controller.busyChanged.connect(self._on_busy_changed)
        self._controller.finished.connect(self._on_finished)

        if self._is_collaborator:
            self._session.phaseChanged.connect(self._apply_phase)
            self._session.lobbyChanged.connect(self._update_participants)
            self._session.progressChanged.connect(self._update_dashboard)
            self._session.assignmentChanged.connect(self._on_assignment)
            self._session.myProgressChanged.connect(self._update_my_progress)
            self._session.shardCompleted.connect(self._on_shard_completed)
        elif self._coordinator is not None:
            self._coordinator.phaseChanged.connect(self._apply_phase)
            self._coordinator.lobbyChanged.connect(self._update_participants)
            self._coordinator.progressChanged.connect(self._update_dashboard)
            self._coordinator.finished.connect(self._on_finished)
            self._update_participants(self._coordinator.participants())

    # ------------------------------------------------------------------ #
    # Sesión colaborativa: Host — servidor y arranque
    # ------------------------------------------------------------------ #
    def _on_start_server(self) -> None:
        """Levanta el servidor colaborativo con el token y puerto indicados."""
        token = self._token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, "Token requerido", "Define una contraseña.")
            return
        assert self._coordinator is not None
        self._server = CollabServer(self._coordinator, self)
        self._server.serverStarted.connect(self._on_server_started)
        self._server.serverStopped.connect(self._on_server_stopped)
        self._server.errorOccurred.connect(self._on_server_error)
        self._server.start(token, self._port_spin.value())

    def _on_stop_server(self) -> None:
        """Detiene el servidor (el progreso ya está consolidado en el Host)."""
        if self._server is not None:
            self._server.stop()

    def _on_start_labeling(self) -> None:
        """Reparte el dataset y arranca la fase de etiquetado distribuido."""
        if self._coordinator is None:
            return
        self._coordinator.start_labeling()
        self._start_label_button.setEnabled(False)

    def _on_server_started(self, _address: str, port: int, token: str) -> None:
        """Muestra los datos de conexión y bloquea los campos de arranque."""
        self._server_info.setText(
            f"Servidor activo.\nIP: {local_ip()}\nPuerto: {port}\nToken: {token}"
        )
        self._start_server_button.setEnabled(False)
        self._stop_server_button.setEnabled(True)
        self._token_edit.setEnabled(False)
        self._port_spin.setEnabled(False)

    def _on_server_stopped(self) -> None:
        """Restablece los controles del Host al detener el servidor."""
        self._server_info.setText("Servidor detenido.")
        self._start_server_button.setEnabled(True)
        self._stop_server_button.setEnabled(False)
        self._token_edit.setEnabled(True)
        self._port_spin.setEnabled(True)
        self._server = None

    def _on_server_error(self, message: str) -> None:
        """Informa de un fallo del servidor y restablece los controles."""
        QMessageBox.critical(self, "Error del servidor", message)
        self._on_server_stopped()

    # ------------------------------------------------------------------ #
    # Sesión colaborativa: fases, presencia y progreso
    # ------------------------------------------------------------------ #
    def _apply_phase(self, phase: str) -> None:
        """Habilita o bloquea el etiquetado según la fase de la sesión."""
        self._phase_label.setText(_PHASE_TEXT.get(phase, phase))
        labeling = phase == SessionPhase.LABELING.value
        for widget in (
            self._class_box, self._fill_group, self._history_group, self._next_button
        ):
            widget.setEnabled(labeling)
        self._canvas.setEnabled(labeling)

        if not self._is_collaborator:
            self._start_label_button.setEnabled(phase == SessionPhase.LOBBY.value)
        elif not labeling and phase == SessionPhase.LOBBY.value:
            self._collab_status.setText("En el lobby. Esperando al Host…")

    def _update_participants(self, participants: List[dict]) -> None:
        """Refresca la lista de participantes conectados con su color."""
        self._collab_list.clear()
        for member in participants:
            self._collab_list.addItem(f"● {member.get('name', '?')}")
            row = self._collab_list.item(self._collab_list.count() - 1)
            row.setForeground(QColor(member.get("color", "#888888")))
        if self._is_collaborator:
            self._collab_status.setText(
                f"Conectado · {len(participants)} participante(s)."
            )

    def _update_dashboard(self, progress: List[dict]) -> None:
        """Refresca el panel supervisor con el progreso de cada trabajador."""
        self._dashboard.clear()
        for worker in progress:
            completed = worker.get("completed", 0)
            assigned = worker.get("assigned", 0)
            name = worker.get("name", "?")
            self._dashboard.addItem(f"{name}: {completed}/{assigned}")
            row = self._dashboard.item(self._dashboard.count() - 1)
            row.setForeground(QColor(worker.get("color", "#888888")))

    def _on_assignment(self, count: int, total: int) -> None:
        """Muestra el tamaño del shard asignado al colaborador."""
        self._image_progress.setMaximum(max(count, 1))
        self._collab_status.setText(f"Shard asignado: {count} de {total} imágenes.")

    def _update_my_progress(self, completed: int, assigned: int) -> None:
        """Actualiza la barra de progreso propia del colaborador."""
        self._image_progress.setMaximum(max(assigned, 1))
        self._image_progress.setValue(completed)

    def _on_shard_completed(self) -> None:
        """El colaborador terminó su porción: bloquea el lienzo y avisa."""
        self._canvas.setEnabled(False)
        self._next_button.setEnabled(False)
        self._collab_status.setText("¡Has completado tu porción! Esperando al Host…")

    # ------------------------------------------------------------------ #
    # Reacciones a las señales del controlador de etiquetado
    # ------------------------------------------------------------------ #
    def _on_grid_ready(self, frame: GridFrame) -> None:
        """Carga una nueva imagen en el lienzo y actualiza el progreso."""
        self._canvas.set_frame(frame.image, frame.session.patches)
        self._info_label.setText(
            f"Archivo: {frame.file_name}\n{frame.session.total} celdas"
        )
        self._image_progress.setMaximum(max(frame.image_total, 1))
        self._image_progress.setValue(frame.image_index)

    def _sync_active_class(self, label: str) -> None:
        """Refleja la clase activa en los botones, el combo y el lienzo."""
        button = self._class_buttons.get(label)
        if button is not None:
            button.setChecked(True)
        if label:
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
        question = (
            "¿Abandonar la sesión colaborativa?"
            if self._is_collaborator
            else "¿Finalizar la sesión para todos? El progreso consolidado se conserva."
        )
        reply = QMessageBox.question(
            self,
            "Salir",
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._controller.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — API Qt.
        """Garantiza el apagado ordenado del servidor y del coordinador/cliente."""
        if self._server is not None:
            self._server.stop()
        self._controller.shutdown()
        super().closeEvent(event)
