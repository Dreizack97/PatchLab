"""Estado editable de la cuadrícula de una imagen (lógica del Modelo).

Concentra toda la lógica de negocio del **etiquetado por clic**: aplicar una
clase a una celda, limpiarla, rellenar las celdas restantes y deshacer/rehacer
cualquiera de esas acciones. No depende de PySide6, por lo que es completamente
testeable de forma aislada.

El historial se implementa con el patrón *Command*: cada acción produce un
:class:`GridCommand` (lote atómico de cambios) que sabe aplicarse y revertirse,
de modo que deshacer y rehacer son simétricos y robustos incluso para
operaciones masivas como el llenado automático.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from patchlab.models.patch import Patch


@dataclass(frozen=True)
class _CellEdit:
    """Cambio reversible de la etiqueta de una celda concreta."""

    patch_index: int
    before: Optional[str]
    after: Optional[str]


@dataclass(frozen=True)
class GridCommand:
    """Lote atómico de cambios de etiqueta: una acción deshacible."""

    edits: Tuple[_CellEdit, ...]
    description: str = ""


class GridSession:
    """
    Cuadrícula de parches de una imagen, con historial de deshacer/rehacer.

    Una celda sin etiquetar tiene ``label is None``; "celdas restantes" son
    justamente esas. Pintar o limpiar una celda registra una acción en el
    historial; aplicar una acción nueva descarta la pila de *rehacer*.
    """

    def __init__(self, patches: List[Patch]) -> None:
        """
        Args:
            patches: Parches de la imagen, en orden de cuadrícula.
        """
        self._patches = patches
        self._undo_stack: List[GridCommand] = []
        self._redo_stack: List[GridCommand] = []

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #
    @property
    def patches(self) -> List[Patch]:
        """Lista de parches gestionados (referencia viva)."""
        return self._patches

    @property
    def total(self) -> int:
        """Número total de celdas."""
        return len(self._patches)

    @property
    def labeled_count(self) -> int:
        """Número de celdas con alguna etiqueta asignada."""
        return sum(1 for patch in self._patches if patch.label is not None)

    @property
    def remaining_count(self) -> int:
        """Número de celdas todavía sin etiquetar."""
        return self.total - self.labeled_count

    @property
    def can_undo(self) -> bool:
        """``True`` si hay acciones que deshacer."""
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        """``True`` si hay acciones que rehacer."""
        return bool(self._redo_stack)

    def label_at(self, index: int) -> Optional[str]:
        """Devuelve la etiqueta actual de la celda ``index``."""
        return self._patches[index].label

    def classified_patches(self) -> List[Patch]:
        """Parches con una etiqueta de clase real (los que deben guardarse)."""
        return [patch for patch in self._patches if patch.is_classified]

    def prefill_suggestions(self) -> int:
        """
        Aplica las sugerencias del clasificador como etiquetas iniciales.

        Solo afecta a celdas aún sin decidir y que tengan ``suggested_label``.
        No genera historial: las sugerencias son el *estado de partida*, no una
        acción del usuario, de modo que «deshacer» no las elimina.

        Returns:
            Número de celdas pre-etiquetadas a partir de una sugerencia.
        """
        prefilled = 0
        for patch in self._patches:
            if patch.label is None and patch.suggested_label is not None:
                patch.label = patch.suggested_label
                prefilled += 1
        return prefilled

    # ------------------------------------------------------------------ #
    # Acciones de edición
    # ------------------------------------------------------------------ #
    def paint(self, index: int, label: str) -> bool:
        """
        Asigna ``label`` a la celda ``index`` (modo "pintar").

        Args:
            index: Índice de la celda.
            label: Etiqueta de clase activa a aplicar.

        Returns:
            ``True`` si la etiqueta cambió (y, por tanto, generó historial).
        """
        return self._apply_single(index, label, "pintar")

    def clear(self, index: int) -> bool:
        """
        Elimina la etiqueta de la celda ``index`` (la deja como restante).

        Args:
            index: Índice de la celda.

        Returns:
            ``True`` si la celda tenía etiqueta y se limpió.
        """
        return self._apply_single(index, None, "limpiar")

    def fill_remaining(self, label: str) -> int:
        """
        Asigna ``label`` a todas las celdas sin etiquetar, en una sola acción.

        Args:
            label: Etiqueta de clase a aplicar a las celdas restantes.

        Returns:
            Número de celdas afectadas (0 si no quedaban restantes).
        """
        edits = tuple(
            _CellEdit(index, None, label)
            for index, patch in enumerate(self._patches)
            if patch.label is None
        )
        if not edits:
            return 0
        self._commit(GridCommand(edits, "rellenar restantes"))
        return len(edits)

    # ------------------------------------------------------------------ #
    # Historial
    # ------------------------------------------------------------------ #
    def undo(self) -> bool:
        """Revierte la última acción. Devuelve ``True`` si hizo algo."""
        if not self._undo_stack:
            return False
        command = self._undo_stack.pop()
        for edit in command.edits:
            self._patches[edit.patch_index].label = edit.before
        self._redo_stack.append(command)
        return True

    def redo(self) -> bool:
        """Reaplica la última acción deshecha. Devuelve ``True`` si hizo algo."""
        if not self._redo_stack:
            return False
        command = self._redo_stack.pop()
        for edit in command.edits:
            self._patches[edit.patch_index].label = edit.after
        self._undo_stack.append(command)
        return True

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #
    def _apply_single(
        self, index: int, label: Optional[str], description: str
    ) -> bool:
        """Aplica un cambio de una celda si realmente altera su etiqueta."""
        patch = self._patches[index]
        if patch.label == label:
            return False
        command = GridCommand((_CellEdit(index, patch.label, label),), description)
        self._commit(command)
        return True

    def _commit(self, command: GridCommand) -> None:
        """Ejecuta un comando, lo apila para deshacer y limpia el *rehacer*."""
        for edit in command.edits:
            self._patches[edit.patch_index].label = edit.after
        self._undo_stack.append(command)
        self._redo_stack.clear()
