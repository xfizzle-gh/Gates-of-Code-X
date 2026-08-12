from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import frontend_runtime_patch
from gates_of_codex.models import CampaignState, Faction, FactionState, Province


ROOT = Path(__file__).resolve().parents[1]


class RuntimeCacheHardeningTests(unittest.TestCase):
    def test_runtime_patch_projection_does_not_mutate_retained_campaign_state(self) -> None:
        state = CampaignState(
            campaign_name="runtime-patch-purity",
            current_faction=Faction.NATO,
            selected_faction=Faction.NATO,
            factions={
                Faction.NATO.value: FactionState(
                    faction=Faction.NATO,
                    is_human_controlled=True,
                )
            },
            provinces={
                "p": Province(
                    province_id="p",
                    display_name="P",
                    owner=Faction.NATO,
                )
            },
            schema_version=11,
        )
        before = copy.deepcopy(state.to_dict())
        graph = {"nodes": [], "edges": [], "sites": [], "rules": {}}
        stack_payload = {
            "battalions": {},
            "strategic_formations": {},
            "stacks": {},
        }

        with (
            patch(
                "gates_of_codex.operational_position.load_operational_graph_for_state",
                return_value=graph,
            ),
            patch(
                "gates_of_codex.operational_movement.get_operational_clock",
                return_value={"tick": 0},
            ),
            patch(
                "gates_of_codex.supply.reachable_supply_provinces",
                return_value={"p"},
            ),
            patch(
                "gates_of_codex.supply.supply_status_for_faction",
                return_value=None,
            ),
            patch(
                "gates_of_codex.frontend._faction_supply_payload",
                return_value={},
            ),
            patch(
                "gates_of_codex.earth3_bootstrap.is_earth3_p2_campaign",
                return_value=False,
            ),
            patch("gates_of_codex.play_context.list_front_options", return_value=[]),
            patch(
                "gates_of_codex.operational_order_options.list_operational_move_options",
                return_value=[],
            ),
            patch(
                "gates_of_codex.presentation.build_stack_presentations",
                return_value=stack_payload,
            ),
            patch("gates_of_codex.frontend._control_block", return_value={}),
            patch("gates_of_codex.frontend._pending_battle", return_value=None),
            patch(
                "gates_of_codex.frontend._apply_s11_frontend_filter",
                side_effect=lambda snapshot, _state: copy.deepcopy(snapshot),
            ),
        ):
            patch_payload = frontend_runtime_patch.build_frontend_runtime_patch(state)

        self.assertEqual(
            frontend_runtime_patch.RUNTIME_PATCH_SCHEMA,
            patch_payload["schema"],
        )
        self.assertEqual(before, state.to_dict())

    def test_backend_exception_discards_leased_state_before_propagating(self) -> None:
        source = (ROOT / "src/gates_of_codex/persistent_backend.py").read_text(
            encoding="utf-8"
        )
        lease_block = source.split(
            "perf._compact_save_campaign = capturing_save", 1
        )[1].split("if _cache_can_survive_report", 1)[0]
        self.assertIn("except Exception:", lease_block)
        exception_block = lease_block.split("except Exception:", 1)[1].split(
            "finally:", 1
        )[0]
        self.assertIn("cached_state = None", exception_block)
        self.assertIn("cached_fingerprint = None", exception_block)
        self.assertIn("raise", exception_block)
        finally_block = lease_block.split("finally:", 1)[1]
        self.assertIn("commands_module.load_campaign = original_loader", finally_block)
        self.assertIn(
            "perf._compact_save_campaign = original_compact_save",
            finally_block,
        )


if __name__ == "__main__":
    unittest.main()
