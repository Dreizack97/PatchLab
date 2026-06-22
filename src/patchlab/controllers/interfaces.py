"""Contrato estructural de un controlador de cuadrícula (DIP).

Define la superficie pública que :class:`~patchlab.views.grid_window.GridWindow`
necesita, de modo que la vista dependa de una **abstracción** y no de una clase
concreta. Así, tanto el controlador local del Host
(:class:`~patchlab.controllers.grid_controller.GridController`) como el
controlador del Colaborador
(:class:`~patchlab.collab.remote_controller.RemoteGridController`) son
intercambiables sin que la ventana cambie.

Las señales se declaran como atributos de tipo ``Signal``; en una instancia Qt
se materializan como ``SignalInstance`` con ``connect``/``emit``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PySide6.QtCore import Signal


@runtime_checkable
class GridControllerLike(Protocol):
    """API mínima que la vista de cuadrícula consume del controlador."""

    # -- Señales hacia la vista ------------------------------------------- #
    gridReady: Signal          # (GridFrame) nueva imagen lista para pintar.
    overlayChanged: Signal     # () las celdas cambiaron; repintar overlay.
    activeClassChanged: Signal  # (str) cambió la clase activa.
    historyChanged: Signal     # (bool, bool) disponibilidad deshacer/rehacer.
    statusMessage: Signal      # (str) mensaje breve de estado.
    busyChanged: Signal        # (bool) ocupado (bloquear interacción).
    finished: Signal           # (str) sesión finalizada, con resumen.

    # -- Intenciones del usuario ------------------------------------------ #
    @property
    def active_class(self) -> str: ...

    def set_active_class(self, label: str) -> None: ...

    def cycle_active_class(self) -> None: ...

    def paint_cell(self, index: int) -> None: ...

    def clear_cell(self, index: int) -> None: ...

    def fill_remaining(self, label: str | None = None) -> None: ...

    def undo(self) -> None: ...

    def redo(self) -> None: ...

    def confirm_and_next(self) -> None: ...

    def quit(self) -> None: ...

    def shutdown(self) -> None: ...
