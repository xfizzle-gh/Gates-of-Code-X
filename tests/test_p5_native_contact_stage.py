from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from test_p2_earth3_campaign_bootstrap import _resolved_catalog

from gates_of_codex.earth3_operational import (
    ALLOWLIST_SHA256,
    DISABLED_CANDIDATE_IDS_SHA256,
    load_authenticated_p3_graph,
)
from gates_of_codex.models import Faction
from gates_of_codex.native_acceptance import (
    NATIVE_CONTACT_METADATA_KEY,
    NATIVE_CONTACT_PLAYER_FORMATION,
    stage_player_one_hop_from_rusa,
)
from gates_of_codex.operational_order_options import list_operational_move_options
from gates_of_codex.scenario import build_scenario


class P5NativeContactStageTests(unittest.TestCase):
    def test_fresh_native_test_can_be_staged_exactly_one_approved_hop_from_rusa(self) -> None:
        state = build_scenario("earth3_v1", resolved_catalog=_resolved_catalog())
        graph_before = load_authenticated_p3_graph()

        staged = stage_player_one_hop_from_rusa(state)

        player = state.strategic_formations[NATIVE_CONTACT_PLAYER_FORMATION]
        defender = state.strategic_formations[staged.target_formation_id]
        self.assertEqual(Faction.NATO, player.faction)
        self.assertEqual(Faction.RUSSIA, defender.faction)
        self.assertIsNotNone(player.position)
        self.assertEqual(staged.staging_node_id, player.position.node_id)
        self.assertEqual(staged.staging_province_id, player.province_id)
        self.assertEqual(staged.target_node_id, defender.position.node_id)
        self.assertIsNone(state.pending_battle)
        self.assertEqual(1, state.turn_number)

        for battalion_id in player.battalion_ids:
            self.assertEqual(
                staged.staging_province_id,
                state.battalions[battalion_id].province_id,
            )

        options = [
            row
            for row in list_operational_move_options(state, Faction.NATO)
            if row["formation_id"] == NATIVE_CONTACT_PLAYER_FORMATION
            and row["target_node_id"] == staged.target_node_id
        ]
        self.assertEqual(1, len(options))
        self.assertEqual(1, options[0]["hop_count"])
        self.assertEqual([staged.edge_id], options[0]["path_edge_ids"])
        self.assertEqual(
            staged.to_dict(),
            state.map_metadata[NATIVE_CONTACT_METADATA_KEY],
        )

        # The helper relocates campaign state only. Frozen P3 authority remains
        # the exact same authenticated graph and hashes.
        graph_after = load_authenticated_p3_graph()
        self.assertEqual(graph_before, graph_after)
        self.assertEqual(64, len(graph_after["nodes"]))
        self.assertEqual(65, len(graph_after["edges"]))
        self.assertEqual(
            "08901e371baa34688429afc9a6f06cc6361da13eac6eb9907901b47c9c233965",
            ALLOWLIST_SHA256,
        )
        self.assertEqual(
            "a7d52fbe2abd1d9b32349ad42e8e00876e3f4727411f58a5e640a3b8a75bbdcf",
            DISABLED_CANDIDATE_IDS_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
