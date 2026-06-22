"""Diálogo para unirse a una sesión colaborativa como Colaborador."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from patchlab.collab.net_utils import DEFAULT_PORT


@dataclass(frozen=True)
class JoinParams:
    """Datos de conexión introducidos por el colaborador."""

    host: str
    port: int
    token: str
    name: str


class JoinDialog(QDialog):
    """Recoge IP, puerto, contraseña y nombre para conectarse a un Host."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PatchLab — Unirse a sesión")
        self.setMinimumWidth(420)
        self._params: Optional[JoinParams] = None

        self._host = QLineEdit()
        self._host.setPlaceholderText("IP del Host (p. ej. 192.168.1.42)")

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(DEFAULT_PORT)

        self._token = QLineEdit()
        self._token.setPlaceholderText("Contraseña de sesión")

        self._name = QLineEdit()
        self._name.setPlaceholderText("Tu nombre visible")

        self._build_layout()

    def _build_layout(self) -> None:
        """Compone el formulario y los botones."""
        form = QFormLayout(self)
        form.addRow("IP del Host:", self._host)
        form.addRow("Puerto:", self._port)
        form.addRow("Contraseña:", self._token)
        form.addRow("Nombre:", self._name)

        hint = QLabel(
            "Pide al Host su IP, puerto y contraseña (visibles en su panel "
            "«Sesión colaborativa»)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        form.addRow(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Conectar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_accept(self) -> None:
        """Valida los campos mínimos y acepta el diálogo."""
        host = self._host.text().strip()
        token = self._token.text().strip()
        name = self._name.text().strip() or "Colaborador"
        if not host:
            QMessageBox.warning(self, "Datos incompletos", "Indica la IP del Host.")
            return
        if not token:
            QMessageBox.warning(
                self, "Datos incompletos", "Indica la contraseña de sesión."
            )
            return
        self._params = JoinParams(
            host=host, port=self._port.value(), token=token, name=name
        )
        self.accept()

    def params(self) -> Optional[JoinParams]:
        """Devuelve los datos de conexión tras aceptar el diálogo."""
        return self._params
