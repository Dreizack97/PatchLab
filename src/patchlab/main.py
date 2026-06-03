"""Punto de entrada de PatchLab (aplicación de escritorio de etiquetado).

El paquete es autocontenido y multiplataforma: usa exclusivamente PySide6 y
OpenCV/NumPy, sin dependencias nativas que requieran compilación específica del
sistema operativo. La dependencia de YOLO (``ultralytics``) es opcional y solo
se importa al usar ese modo.

Se arranca mediante el comando ``patchlab`` (instalado como *console script*) o
con ``python -m patchlab``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from patchlab.collab.client import CollabClient
from patchlab.collab.coordinator import SessionCoordinator
from patchlab.collab.remote_controller import RemoteGridController
from patchlab.controllers.controller import LabelingController
from patchlab.models.config import LabelerConfig, LabelingMode
from patchlab.services.image_loader import find_images
from patchlab.views.grid_window import GridWindow
from patchlab.views.join_dialog import JoinDialog
from patchlab.views.main_window import MainWindow
from patchlab.views.start_dialog import StartDialog
from patchlab.views.theme import apply_theme


def run() -> int:
    """
    Arranca la aplicación gráfica completa.

    Returns:
        Código de salida del bucle de eventos de Qt.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("PatchLab")
    apply_theme(app)

    dialog = StartDialog()
    if dialog.exec() != StartDialog.DialogCode.Accepted:
        return 0

    # Flujo del Colaborador: en vez de cargar imágenes locales, se conecta a un
    # Host y refleja su cuadrícula a través de la red.
    if dialog.join_requested():
        return _run_as_collaborator(app)

    config = dialog.config()
    assert config is not None  # Garantizado al aceptar el diálogo.

    images = find_images(config.input_dir)
    if not images:
        QMessageBox.critical(
            None,
            "Sin imágenes",
            f"No se encontraron imágenes válidas en:\n{config.input_dir}",
        )
        return 1

    # Selecciona la pareja Controlador/Vista según el modo de interacción.
    if config.mode == LabelingMode.GRID_CLICK:
        # El modo cuadrícula es siempre colaborativo distribuido: el Host actúa
        # como supervisor + trabajador. La sesión arranca en el lobby y no se
        # etiqueta hasta pulsar «Comenzar Etiquetado».
        coordinator = SessionCoordinator(config, images)
        window = GridWindow(coordinator.local, config, coordinator=coordinator)
        window.show()
    else:
        controller = LabelingController(config, images)
        window = MainWindow(controller, config)
        window.show()
        controller.start()

    return app.exec()


def _run_as_collaborator(app: QApplication) -> int:
    """
    Arranca PatchLab en modo Colaborador: pide los datos de conexión, se une a
    la sesión del Host y abre la ventana de cuadrícula gobernada por la red.

    Args:
        app: La aplicación Qt ya inicializada.

    Returns:
        Código de salida del bucle de eventos (o 0 si se cancela el diálogo).
    """
    join = JoinDialog()
    if join.exec() != JoinDialog.DialogCode.Accepted:
        return 0
    params = join.params()
    assert params is not None

    client = CollabClient(params.host, params.port, params.token, params.name)
    remote = RemoteGridController(client)
    # Referencias persistentes: la ventana se crea al recibir el «welcome».
    state: dict = {"window": None}

    def on_welcomed(_you: int, labels: list, _phase: str) -> None:
        # El Colaborador no posee dataset; las rutas son meros marcadores.
        config = LabelerConfig(
            input_dir=Path("."),
            output_dir=Path("."),
            labels=list(labels),
            mode=LabelingMode.GRID_CLICK,
        )
        window = GridWindow(remote, config, is_collaborator=True)
        state["window"] = window
        window.show()

    def on_failure(message: str) -> None:
        # Solo relevante si aún no hay ventana (errores tras conectar los
        # gestiona la propia ventana mediante la señal ``finished``).
        if state["window"] is None:
            QMessageBox.critical(None, "No se pudo unir a la sesión", message)
            app.quit()

    client.welcomed.connect(on_welcomed)
    client.denied.connect(on_failure)
    client.connectionClosed.connect(on_failure)

    remote.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
