"""Pruebas del registro de presencia (Roster)."""

from __future__ import annotations

from patchlab.collab.presence import PRESENCE_PALETTE, Roster


def test_roster_assigns_incremental_ids_and_colors() -> None:
    roster = Roster()
    a = roster.add("Ada")
    b = roster.add("Linus")
    assert (a.client_id, b.client_id) == (1, 2)
    assert a.color == PRESENCE_PALETTE[0]
    assert b.color == PRESENCE_PALETTE[1]
    assert len(roster) == 2


def test_roster_remove_and_color_fallback() -> None:
    roster = Roster()
    member = roster.add("Ada")
    roster.remove(member.client_id)
    assert roster.get(member.client_id) is None
    assert roster.color_of(member.client_id) == "#888888"
    assert roster.as_list() == []


def test_roster_as_list_is_sorted_and_serializable() -> None:
    roster = Roster()
    roster.add("Ada")
    roster.add("Linus")
    listed = roster.as_list()
    assert [m["id"] for m in listed] == [1, 2]
    assert listed[0]["name"] == "Ada"
    assert "color" in listed[0]
