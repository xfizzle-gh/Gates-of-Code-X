from __future__ import annotations

import unittest

from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Province,
)
from gates_of_codex.state_io import campaign_from_dict


def _state() -> CampaignState:
    state = CampaignState(
        campaign_name="S8 test",
        factions={"nato": FactionState(Faction.NATO)},
        provinces={"p1": Province("p1", "P1", Faction.NATO)},
        battalions={
            "nato-1": Battalion(
                battalion_id="nato-1",
                faction=Faction.NATO,
                province_id="p1",
                roster=[
                    BattalionRosterEntry(
                        "rifle", quantity=3, category="infantry"
                    )
                ],
            )
        },
    )
    ensure_strategic_formations(state)
    return state


def _only_force(state: CampaignState):
    return next(iter(state.strategic_formations.values()))


class OperationalS8SupplyTests(unittest.TestCase):
    def test_s8_fields_round_trip_strictly(self) -> None:
        state = _state()
        state.schema_version = 8
        force = _only_force(state)
        force.supplied = False
        force.cut_off = True
        force.source_hub_id = None
        force.route_cost = None
        force.grace_ticks_remaining = 0
        force.last_supply_refresh_tick = 12
        force.last_supply_refresh_turn = 3
        force.last_grace_consuming_tick = 12

        loaded = campaign_from_dict(state.to_dict())
        restored = _only_force(loaded)

        self.assertFalse(restored.supplied)
        self.assertTrue(restored.cut_off)
        self.assertIsNone(restored.source_hub_id)
        self.assertIsNone(restored.route_cost)
        self.assertEqual(0, restored.grace_ticks_remaining)
        self.assertEqual(12, restored.last_supply_refresh_tick)
        self.assertEqual(3, restored.last_supply_refresh_turn)
        self.assertEqual(12, restored.last_grace_consuming_tick)

    def test_schema7_no_graph_payload_omits_s8_fields(self) -> None:
        state = _state()
        state.schema_version = 7

        row = next(iter(state.to_dict()["strategic_formations"].values()))

        self.assertNotIn("supplied", row)
        self.assertNotIn("cut_off", row)
        self.assertNotIn("source_hub_id", row)
        self.assertNotIn("route_cost", row)
        self.assertNotIn("grace_ticks_remaining", row)
        self.assertNotIn("last_supply_refresh_tick", row)
        self.assertNotIn("last_supply_refresh_turn", row)
        self.assertNotIn("last_grace_consuming_tick", row)

    def test_s8_optional_int_rejects_bool_string_and_float(self) -> None:
        for bad in (True, "1", 1.0):
            with self.subTest(bad=bad):
                state = _state()
                state.schema_version = 8
                payload = state.to_dict()
                row = next(iter(payload["strategic_formations"].values()))
                row["route_cost"] = bad

                with self.assertRaisesRegex(ValueError, "route_cost"):
                    campaign_from_dict(payload)


if __name__ == "__main__":
    unittest.main()
