from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.models import BattalionRosterEntry, CampaignState, Faction
from gates_of_codex.operational_position import clear_operational_graph_cache
from gates_of_codex.operational_retreat import OperationalRetreatAuthorityUnavailable
from tests.test_operational_s9a_retreat import (
    OperationalS9AFinalizationTests,
    _state,
)


class OperationalS9AMalformedGraphAuthorityTests(unittest.TestCase):
    def _pending_node_battle(self, state: CampaignState) -> None:
        helper = OperationalS9AFinalizationTests()
        helper._node_battle(state)
        self.assertIsNotNone(state.pending_battle)

    def _replace_graph_with_readable_malformed_authority(
        self, state: CampaignState
    ) -> None:
        graph_path = Path(str(state.map_metadata["operational_graph"]))
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        del graph["edges"][0]["a"]
        graph_path.write_text(json.dumps(graph), encoding="utf-8")
        clear_operational_graph_cache()

        # This is valid JSON. The failure must come from graph structure rather
        # than the missing-file case covered by the primary S9A fixture.
        malformed = json.loads(graph_path.read_text(encoding="utf-8"))
        self.assertIsInstance(malformed, dict)
        self.assertNotIn("a", malformed["edges"][0])

    def test_internal_result_rejects_malformed_graph_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            self._pending_node_battle(state)
            engine = CampaignEngine(state, random_seed=0)
            self._replace_graph_with_readable_malformed_authority(state)
            before = json.dumps(state.to_dict(), sort_keys=True)

            with self.assertRaises(OperationalRetreatAuthorityUnavailable):
                engine.apply_battle_result(Faction.RUSSIA)

            self.assertEqual(before, json.dumps(state.to_dict(), sort_keys=True))
            self.assertIn("sf-nato", state.strategic_formations)
            self.assertIn("bn-nato", state.battalions)
            self.assertIsNotNone(state.pending_battle)

    def test_external_result_rejects_malformed_graph_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            self._pending_node_battle(state)
            engine = CampaignEngine(state, random_seed=0)
            self._replace_graph_with_readable_malformed_authority(state)
            before = json.dumps(state.to_dict(), sort_keys=True)
            replacement_survivors = {
                "bn-nato": [
                    BattalionRosterEntry("inf", 1, category="infantry")
                ]
            }

            with self.assertRaises(OperationalRetreatAuthorityUnavailable):
                engine.apply_external_battle_result(
                    Faction.RUSSIA,
                    replacement_survivors,
                )

            self.assertEqual(before, json.dumps(state.to_dict(), sort_keys=True))
            self.assertIn("sf-nato", state.strategic_formations)
            self.assertIn("bn-nato", state.battalions)
            self.assertIsNotNone(state.pending_battle)


if __name__ == "__main__":
    unittest.main()
