"""Diálogo de configuración inicial de la sesión de etiquetado."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from patchlab.models.config import LabelerConfig


class _PathSelector(QWidget):
    """Campo de texto con botón "Examinar…" para elegir rutas."""

    def __init__(
        self, placeholder: str, pick_dir: bool, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._pick_dir = pick_dir

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        browse = QPushButton("Examinar…")
        browse.clicked.connect(self._browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._edit, stretch=1)
        layout.addWidget(browse)

    def _browse(self) -> None:
        """Abre el selector de archivos o carpetas según la configuración."""
        if self._pick_dir:
            chosen = QFileDialog.getExistingDirectory(self, "Selecciona carpeta")
        else:
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Selecciona archivo", filter="Modelos YOLO (*.pt);;Todos (*)"
            )
        if chosen:
            self._edit.setText(chosen)

    def text(self) -> str:
        """Devuelve el texto actual del campo."""
        return self._edit.text().strip()


class StartDialog(QDialog):
    """Recoge los parámetros de la sesión y construye un :class:`LabelerConfig`."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PatchLab — Configurar sesión")
        self.setMinimumWidth(560)
        self._config: Optional[LabelerConfig] = None
        # ``True`` si el usuario eligió unirse a una sesión remota en vez de
        # iniciar una local (lo consulta ``main.py`` tras cerrar el diálogo).
        self._join_requested = False

        self._input = _PathSelector("Carpeta con imágenes a etiquetar", pick_dir=True)
        self._output = _PathSelector("Carpeta de salida del dataset", pick_dir=True)
        self._model = _PathSelector("Opcional: modelo YOLO (.pt)", pick_dir=False)
        self._classifier = _PathSelector(
            "Opcional: modelo de clasificación (.pt)", pick_dir=False
        )

        self._classifier_conf = QDoubleSpinBox()
        self._classifier_conf.setRange(0.0, 1.0)
        self._classifier_conf.setSingleStep(0.05)
        self._classifier_conf.setValue(0.0)
        self._classifier_conf.setToolTip(
            "Confianza mínima para aceptar una sugerencia del clasificador "
            "(0 = aceptar todas)."
        )

        self._labels = QLineEdit("OK, NG")
        self._labels.setPlaceholderText("Etiquetas separadas por comas")

        self._patch_size = QSpinBox()
        self._patch_size.setRange(8, 2048)
        self._patch_size.setValue(64)
        self._patch_size.setSuffix(" px")

        self._padding = QDoubleSpinBox()
        self._padding.setRange(0.0, 2.0)
        self._padding.setSingleStep(0.05)
        self._padding.setValue(0.0)
        self._padding.setToolTip("Contexto extra del recorte YOLO (0.1 = 10 %)")

        self._build_layout()

    def _build_layout(self) -> None:
        """Compone el formulario y los botones de acción."""
        form = QFormLayout()
        form.addRow("Directorio de entrada:", self._input)
        form.addRow("Directorio de salida:", self._output)
        form.addRow("Modelo YOLO:", self._model)
        form.addRow("Modelo de clasificación:", self._classifier)
        form.addRow("Confianza mínima:", self._classifier_conf)
        form.addRow("Etiquetas:", self._labels)
        form.addRow("Tamaño de parche:", self._patch_size)
        form.addRow("Padding YOLO:", self._padding)

        hint = QLabel(
            "Sin modelo YOLO se usa el modo Cuadrícula sobre toda la imagen. "
            "El modelo de clasificación es opcional y pre-sugiere la clase de "
            "cada parche para acelerar el etiquetado."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        form.addRow(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Iniciar")
        # Acción alternativa: conectarse como colaborador a una sesión existente.
        join_button = buttons.addButton(
            "Unirse a sesión…", QDialogButtonBox.ButtonRole.ActionRole
        )
        join_button.clicked.connect(self._on_join)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.setLayout(form)

    def _on_accept(self) -> None:
        """Valida la entrada y, si es correcta, acepta el diálogo."""
        labels = [
            token.strip()
            for token in self._labels.text().split(",")
            if token.strip()
        ]
        model_text = self._model.text()
        classifier_text = self._classifier.text()
        config = LabelerConfig(
            input_dir=Path(self._input.text()),
            output_dir=Path(self._output.text()),
            labels=labels,
            model_path=Path(model_text) if model_text else None,
            classifier_path=Path(classifier_text) if classifier_text else None,
            classifier_min_confidence=self._classifier_conf.value(),
            patch_size=self._patch_size.value(),
            padding_pct=self._padding.value(),
        )
        try:
            config.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Configuración inválida", str(exc))
            return

        self._config = config
        self.accept()

    def _on_join(self) -> None:
        """Marca que el usuario quiere unirse a una sesión y cierra el diálogo."""
        self._join_requested = True
        self.accept()

    def config(self) -> Optional[LabelerConfig]:
        """Devuelve la configuración construida tras aceptar el diálogo."""
        return self._config

    def join_requested(self) -> bool:
        """``True`` si el usuario eligió «Unirse a sesión» en vez de iniciar."""
        return self._join_requested
