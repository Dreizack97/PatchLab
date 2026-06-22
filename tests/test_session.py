"""Pruebas del reparto y estado de la sesión distribuida (capa pura)."""

from __future__ import annotations

import pytest

from patchlab.collab.session import SessionPhase, SessionState, ShardPlanner


# --------------------------------------------------------------------------- #
# ShardPlanner
# --------------------------------------------------------------------------- #
def test_plan_is_equitable_and_complete() -> None:
    shards = ShardPlanner.plan(list(range(10)), [1, 2, 3], seed=42)
    sizes = sorted(len(v) for v in shards.values())
    assert sizes == [3, 3, 4]  # difieren como mucho en 1
    flat = sorted(img for shard in shards.values() for img in shard)
    assert flat == list(range(10))  # disjuntos y completos


def test_plan_is_deterministic_with_seed() -> None:
    a = ShardPlanner.plan(list(range(20)), [1, 2], seed=7)
    b = ShardPlanner.plan(list(range(20)), [1, 2], seed=7)
    assert a == b


def test_plan_shuffles_order() -> None:
    # Con esta semilla el reparto no debe ser el orden natural 0,1,2…
    shards = ShardPlanner.plan(list(range(10)), [1], seed=123)
    assert shards[1] != list(range(10))
    assert sorted(shards[1]) == list(range(10))


def test_plan_requires_workers() -> None:
    with pytest.raises(ValueError):
        ShardPlanner.plan([0, 1, 2], [], seed=1)


# --------------------------------------------------------------------------- #
# SessionState — consumo de trabajo
# --------------------------------------------------------------------------- #
def test_next_and_complete_flow() -> None:
    state = SessionState()
    state.set_shards({1: [10, 11], 2: [20]})
    assert state.next_image(1) == 10
    assert state.in_flight_of(1) == 10
    assert not state.is_idle(1)
    assert state.complete(1, 10) is True
    assert state.is_idle(1)
    assert state.progress_of(1).completed == 1
    assert state.next_image(1) == 11
    assert state.next_image(2) == 20


def test_next_raises_if_already_in_flight() -> None:
    state = SessionState()
    state.set_shards({1: [10, 11]})
    state.next_image(1)
    with pytest.raises(ValueError):
        state.next_image(1)


def test_complete_rejects_wrong_image() -> None:
    state = SessionState()
    state.set_shards({1: [10, 11]})
    state.next_image(1)  # 10 en vuelo
    assert state.complete(1, 99) is False
    assert state.complete(1, 10) is True


def test_all_done_detects_finish() -> None:
    state = SessionState()
    state.set_shards({1: [10]})
    assert state.all_done() is False
    image = state.next_image(1)
    state.complete(1, image)
    assert state.all_done() is True


# --------------------------------------------------------------------------- #
# SessionState — desconexión y redistribución
# --------------------------------------------------------------------------- #
def test_remove_worker_returns_pending_including_in_flight() -> None:
    state = SessionState()
    state.set_shards({1: [10, 11, 12]})
    assert state.next_image(1) == 10  # en vuelo
    pending = state.remove_worker(1)
    assert pending == [10, 11, 12]
    assert 1 not in state.workers()


def test_redistribute_round_robin_grows_assignment() -> None:
    state = SessionState()
    state.set_shards({1: [10], 2: [20]})
    touched = state.redistribute([30, 31, 32], [1, 2])
    assert sorted(touched) == [1, 2]
    # 1 recibe 30 y 32; 2 recibe 31 → asignaciones crecen.
    assert state.progress_of(1).assigned == 3
    assert state.progress_of(2).assigned == 2


def test_disconnect_then_redistribute_keeps_work() -> None:
    state = SessionState()
    state.set_shards({1: [10, 11], 2: [20, 21]})
    # El trabajador 2 se desconecta con todo pendiente.
    pending = state.remove_worker(2)
    state.redistribute(pending, [1])
    assert state.progress_of(1).assigned == 4
    # El trabajador 1 puede consumir todo el trabajo redistribuido.
    seen = []
    while state.has_pending(1) or not state.is_idle(1):
        img = state.next_image(1)
        if img is None:
            break
        seen.append(img)
        state.complete(1, img)
    assert sorted(seen) == [10, 11, 20, 21]
    assert state.all_done() is True


def test_phase_enum_values() -> None:
    assert SessionPhase.LOBBY.value == "lobby"
    assert SessionPhase.LABELING.value == "labeling"
    assert SessionPhase.FINISHED.value == "finished"
