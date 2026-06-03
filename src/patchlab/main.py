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

from PySide6.QtWidgets import QApplication, QMessageBox

from patchlab.controllers.controller import LabelingController
from patchlab.controllers.grid_controller import GridController
from patchlab.models.config import LabelingMode
from patchlab.services.image_loader import find_images
from patchlab.views.grid_window import GridWindow
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
        grid_controller = GridController(config, images)
        window = GridWindow(grid_controller, config)
        window.show()
        grid_controller.start()
    else:
        controller = LabelingController(config, images)
        window = MainWindow(controller, config)
        window.show()
        controller.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
