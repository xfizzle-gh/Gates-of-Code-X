from __future__ import annotations

import json
import unittest

from gates_of_codex import command_cycle_perf
from gates_of_codex.models import CampaignState, Faction, FactionState, Province


class RuntimeSerializationParityTests(unittest.TestCase):
    def _state(self, *, schema_version: int) -> CampaignState:
        return CampaignState(
            campaign_name="serialization-parity",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            factions={
                "nato": FactionState(
                    faction=Faction.NATO,
                    resources=1234,
                    researched_keys=["alpha"],
                    is_human_controlled=True,
                )
            },
            provinces={
                "p1": Province(
                    province_id="p1",
                    display_name="Province One",
                    owner=Faction.NATO,
                    metadata={
                        "nested": {
                            "rows": [
                                {"id": "a", "values": [1, 2, 3]},
                                {"id": "b", "enabled": True},
                            ]
                        }
                    },
                )
            },
            fog_of_war_enabled=True,
            knowledge_by_observer={},
            schema_version=schema_version,
        )

    @staticmethod
    def _baseline(state: CampaignState) -> str:
        return json.dumps(
            state.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def test_schema_11_direct_serialization_is_byte_equivalent_to_to_dict(self) -> None:
        state = self._state(schema_version=11)
        expected = self._baseline(state)
        actual = command_cycle_perf._runtime_state_json(state)
        self.assertEqual(expected, actual)
        self.assertEqual(json.loads(expected), json.loads(actual))

    def test_legacy_schema_retains_to_dict_field_pruning_contract(self) -> None:
        state = self._state(schema_version=4)
        expected = self._baseline(state)
        actual = command_cycle_perf._runtime_state_json(state)
        self.assertEqual(expected, actual)
        decoded = json.loads(actual)
        self.assertNotIn("fog_of_war_enabled", decoded)
        self.assertNotIn("knowledge_by_observer", decoded)

    def test_runtime_encoder_does_not_call_to_dict_for_schema_11(self) -> None:
        state = self._state(schema_version=11)

        def forbidden_to_dict():
            raise AssertionError("schema-11 runtime serialization must not materialize asdict")

        state.to_dict = forbidden_to_dict  # type: ignore[method-assign]
        payload = command_cycle_perf._runtime_state_json(state)
        self.assertEqual("serialization-parity", json.loads(payload)["campaign_name"])


if __name__ == "__main__":
    unittest.main()
