"""Estado de una sesión colaborativa distribuida (capa pura, sin Qt).

Modela el **flujo de trabajo distribuido equitativamente**: el dataset se baraja
y se reparte en *shards* (porciones) disjuntos, uno por trabajador, y cada
trabajador consume su porción de forma independiente. Concentra tres piezas de
lógica deterministas y testeables de forma aislada:

- :class:`SessionPhase`: la máquina de estados de la sesión.
- :class:`ShardPlanner`: el reparto aleatorio y equitativo del dataset.
- :class:`SessionState`: las colas de trabajo por trabajador, el progreso y la
  **redistribución** de las imágenes pendientes cuando alguien se desconecta.

No depende de Qt, de la red ni del disco: opera sobre identificadores enteros de
imagen (índices en el dataset) y de trabajador.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class SessionPhase(str, Enum):
    """Fases del ciclo de vida de una sesión colaborativa."""

    #: El Host espera conexiones; nadie etiqueta todavía.
    LOBBY = "lobby"
    #: El dataset está repartido y los trabajadores etiquetan en paralelo.
    LABELING = "labeling"
    #: Todo el dataset se ha etiquetado y consolidado.
    FINISHED = "finished"


@dataclass(frozen=True)
class WorkerProgress:
    """Instantánea del progreso de un trabajador para el panel supervisor."""

    worker_id: int
    assigned: int
    completed: int
    connected: bool

    @property
    def is_done(self) -> bool:
        """``True`` si el trabajador completó toda su porción asignada."""
        return self.connected and self.completed >= self.assigned


class ShardPlanner:
    """Reparte un dataset en porciones aleatorias y lo más equitativas posible."""

    @staticmethod
    def plan(
        image_ids: List[int], worker_ids: List[int], seed: int
    ) -> Dict[int, List[int]]:
        """
        Baraja ``image_ids`` con ``seed`` y los reparte entre ``worker_ids``.

        El reparto es *round-robin* sobre la lista barajada, de modo que los
        tamaños de los shards difieren como mucho en una imagen.

        Args:
            image_ids: Identificadores de imagen del dataset completo.
            worker_ids: Identificadores de los trabajadores activos (no vacío).
            seed: Semilla del barajado (consistencia/reproducibilidad).

        Returns:
            Diccionario ``{worker_id: [image_id, ...]}`` con shards disjuntos.

        Raises:
            ValueError: Si no hay trabajadores a los que repartir.
        """
        if not worker_ids:
            raise ValueError("No hay trabajadores para repartir el dataset.")

        shuffled = list(image_ids)
        random.Random(seed).shuffle(shuffled)

        shards: Dict[int, List[int]] = {worker_id: [] for worker_id in worker_ids}
        for position, image_id in enumerate(shuffled):
            shards[worker_ids[position % len(worker_ids)]].append(image_id)
        return shards


class SessionState:
    """
    Colas de trabajo, progreso y redistribución de una sesión en etiquetado.

    Cada trabajador tiene una **cola** de imágenes pendientes y, como mucho, una
    imagen *en vuelo* (servida y todavía sin confirmar). El total asignado puede
    crecer si se le redistribuye trabajo de un compañero desconectado.
    """

    def __init__(self) -> None:
        self._queues: Dict[int, deque[int]] = {}
        self._in_flight: Dict[int, Optional[int]] = {}
        self._assigned: Dict[int, int] = {}
        self._completed: Dict[int, int] = {}

    # ------------------------------------------------------------------ #
    # Configuración inicial
    # ------------------------------------------------------------------ #
    def set_shards(self, shards: Dict[int, List[int]]) -> None:
        """Inicializa las colas y contadores a partir del reparto inicial."""
        self._queues = {worker: deque(images) for worker, images in shards.items()}
        self._in_flight = {worker: None for worker in shards}
        self._assigned = {worker: len(images) for worker, images in shards.items()}
        self._completed = {worker: 0 for worker in shards}

    def add_worker(self, worker_id: int) -> None:
        """Registra un trabajador sin trabajo asignado (p. ej. en el lobby)."""
        self._queues.setdefault(worker_id, deque())
        self._in_flight.setdefault(worker_id, None)
        self._assigned.setdefault(worker_id, 0)
        self._completed.setdefault(worker_id, 0)

    # ------------------------------------------------------------------ #
    # Consumo de trabajo
    # ------------------------------------------------------------------ #
    def next_image(self, worker_id: int) -> Optional[int]:
        """
        Entrega la siguiente imagen de la cola del trabajador y la pone en vuelo.

        Returns:
            El ``image_id`` a etiquetar, o ``None`` si la cola está vacía.

        Raises:
            ValueError: Si el trabajador ya tiene una imagen en vuelo.
        """
        if self._in_flight.get(worker_id) is not None:
            raise ValueError(
                f"El trabajador {worker_id} ya tiene una imagen en vuelo."
            )
        queue = self._queues.get(worker_id)
        if not queue:
            return None
        image_id = queue.popleft()
        self._in_flight[worker_id] = image_id
        return image_id

    def complete(self, worker_id: int, image_id: int) -> bool:
        """
        Marca como completada la imagen en vuelo del trabajador.

        Args:
            worker_id: Trabajador que confirma.
            image_id: Imagen que debía estar en vuelo (validación de coherencia).

        Returns:
            ``True`` si la imagen estaba en vuelo y se contabilizó.
        """
        if self._in_flight.get(worker_id) != image_id:
            return False
        self._in_flight[worker_id] = None
        self._completed[worker_id] += 1
        return True

    # ------------------------------------------------------------------ #
    # Desconexión y redistribución
    # ------------------------------------------------------------------ #
    def remove_worker(self, worker_id: int) -> List[int]:
        """
        Elimina a un trabajador y devuelve sus imágenes pendientes.

        Las pendientes son las de su cola más la que tuviera en vuelo (no
        confirmada). El llamador decide a quién redistribuirlas.

        Returns:
            Lista de ``image_id`` pendientes que deben reasignarse.
        """
        pending: List[int] = []
        in_flight = self._in_flight.get(worker_id)
        if in_flight is not None:
            pending.append(in_flight)
        pending.extend(self._queues.get(worker_id, deque()))

        self._queues.pop(worker_id, None)
        self._in_flight.pop(worker_id, None)
        self._assigned.pop(worker_id, None)
        self._completed.pop(worker_id, None)
        return pending

    def redistribute(self, image_ids: List[int], worker_ids: List[int]) -> List[int]:
        """
        Reparte ``image_ids`` (round-robin) entre los trabajadores activos.

        Aumenta el total asignado de cada receptor, de modo que el panel de
        progreso refleje su nueva carga.

        Args:
            image_ids: Imágenes a redistribuir (p. ej. de un desconectado).
            worker_ids: Trabajadores activos que recibirán el trabajo.

        Returns:
            Los ``worker_ids`` que recibieron al menos una imagen.
        """
        if not worker_ids or not image_ids:
            return []
        touched: List[int] = []
        for position, image_id in enumerate(image_ids):
            worker_id = worker_ids[position % len(worker_ids)]
            self._queues[worker_id].append(image_id)
            self._assigned[worker_id] += 1
            if worker_id not in touched:
                touched.append(worker_id)
        return touched

    # ------------------------------------------------------------------ #
    # Consultas de progreso
    # ------------------------------------------------------------------ #
    def workers(self) -> List[int]:
        """Identificadores de los trabajadores actualmente en la sesión."""
        return list(self._queues)

    def has_pending(self, worker_id: int) -> bool:
        """``True`` si al trabajador le quedan imágenes en cola."""
        return bool(self._queues.get(worker_id))

    def is_idle(self, worker_id: int) -> bool:
        """``True`` si el trabajador no tiene imagen en vuelo."""
        return self._in_flight.get(worker_id) is None

    def in_flight_of(self, worker_id: int) -> Optional[int]:
        """Imagen que el trabajador tiene servida sin confirmar, o ``None``."""
        return self._in_flight.get(worker_id)

    def progress_of(self, worker_id: int, *, connected: bool = True) -> WorkerProgress:
        """Devuelve el progreso de un trabajador concreto."""
        return WorkerProgress(
            worker_id=worker_id,
            assigned=self._assigned.get(worker_id, 0),
            completed=self._completed.get(worker_id, 0),
            connected=connected,
        )

    def all_done(self) -> bool:
        """``True`` si ningún trabajador tiene cola ni imagen en vuelo."""
        return all(
            not queue and self._in_flight.get(worker_id) is None
            for worker_id, queue in self._queues.items()
        )

    @property
    def total_completed(self) -> int:
        """Número total de imágenes completadas por todos los trabajadores."""
        return sum(self._completed.values())
