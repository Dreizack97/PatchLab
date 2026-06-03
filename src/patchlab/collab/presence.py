"""Registro de presencia de los participantes (capa pura, sin Qt).

:class:`Roster` lleva la cuenta de quién está conectado, asignando a cada uno un
identificador estable y un color de presencia para distinguirlo en el panel
supervisor. Es determinista y no depende de Qt, por lo que se prueba de forma
headless.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

#: Paleta de colores de presencia (hex), elegida para contrastar entre sí y con
#: los rellenos de etiqueta translúcidos del lienzo.
PRESENCE_PALETTE: List[str] = [
    "#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
]


@dataclass
class Collaborator:
    """Un colaborador conectado y su color de presencia asignado."""

    client_id: int
    name: str
    color: str

    def as_dict(self) -> Dict[str, object]:
        """Representación serializable para el roster del protocolo."""
        return {"id": self.client_id, "name": self.name, "color": self.color}


class Roster:
    """Registro de colaboradores conectados con identidad y color estables."""

    def __init__(self) -> None:
        self._members: Dict[int, Collaborator] = {}
        self._next_id = 1

    def add(self, name: str) -> Collaborator:
        """Registra un colaborador, le asigna id y color, y lo devuelve."""
        client_id = self._next_id
        self._next_id += 1
        color = PRESENCE_PALETTE[(client_id - 1) % len(PRESENCE_PALETTE)]
        member = Collaborator(client_id=client_id, name=name, color=color)
        self._members[client_id] = member
        return member

    def remove(self, client_id: int) -> None:
        """Elimina a un colaborador del roster (idempotente)."""
        self._members.pop(client_id, None)

    def get(self, client_id: int) -> Optional[Collaborator]:
        """Devuelve el colaborador con ese id, o ``None`` si no existe."""
        return self._members.get(client_id)

    def color_of(self, client_id: int) -> str:
        """Color de presencia de un colaborador (gris si ya no está)."""
        member = self._members.get(client_id)
        return member.color if member is not None else "#888888"

    def as_list(self) -> List[Dict[str, object]]:
        """Lista serializable de colaboradores, ordenada por id."""
        return [
            self._members[cid].as_dict() for cid in sorted(self._members)
        ]

    def __len__(self) -> int:
        return len(self._members)
