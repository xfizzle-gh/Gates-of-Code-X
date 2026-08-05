from __future__ import annotations

import unittest

from gates_of_codex.europe import build_goe_europe_campaign, load_goe_europe_graph
from gates_of_codex.models import Faction
from gates_of_codex.state_io import campaign_from_dict


class EuropeFormationTests(unittest.TestCase):
    def test_goe_graph_preserves_all_provinces_and_reciprocal_edges(self) -> None:
        graph = load_goe_europe_graph()
        self.assertEqual(517, len(graph["provinces"]))
        self.assertEqual(63, graph["metadata"]["named_province_count"])
        self.assertTrue(graph["metadata"]["exact_adjacency_graph"])
        for province_id, province in graph["provinces"].items():
            for neighbor_id in province["neighbors"]:
                self.assertIn(province_id, graph["provinces"][neighbor_id]["neighbors"])

    def test_campaign_has_distinct_formations_and_central_asia_contingents(self) -> None:
        state = build_goe_europe_campaign()
        self.assertEqual(517, len(state.provinces))
        self.assertGreaterEqual(len(state.formations), 14)
        self.assertEqual(Faction.RUSSIA, state.formations["rusa-prk-expeditionary"].faction)
        self.assertEqual("PRK", state.formations["rusa-prk-expeditionary"].nation)
        self.assertTrue(state.formations["rusa-prk-expeditionary"].is_foreign_contingent)
        self.assertEqual("central_asia", state.formations["prc-western-combined-arms"].deployment_zone)
        self.assertEqual(len(state.formations), len(state.battalions))
        self.assertEqual(len(state.battalions), len({b.province_id for b in state.battalions.values()}))

    def test_schema_two_round_trip_retains_formations_and_metadata(self) -> None:
        from gates_of_codex.force_migration import ensure_strategic_formations

        original = build_goe_europe_campaign()
        ensure_strategic_formations(original)
        restored = campaign_from_dict(original.to_dict())
        self.assertEqual(original.map_id, restored.map_id)
        # Migration report timestamps/counters may refresh; core map metadata must remain.
        migration_keys = {"strategic_formation_migration", "operational_position_migration"}
        original_meta = {
            key: value
            for key, value in original.map_metadata.items()
            if key not in migration_keys
        }
        restored_meta = {
            key: value
            for key, value in restored.map_metadata.items()
            if key not in migration_keys
        }
        self.assertEqual(original_meta, restored_meta)
        self.assertEqual(original.formations["nato-pol-mechanized"], restored.formations["nato-pol-mechanized"])
        self.assertEqual(
            original.provinces["Warszawa"].metadata,
            restored.provinces["Warszawa"].metadata,
        )
        self.assertEqual(len(original.strategic_formations), len(restored.strategic_formations))

    def test_legacy_scenario_without_formations_remains_loadable(self) -> None:
        legacy = {
            "campaign_name": "Legacy",
            "factions": {"nato": {"faction": "nato"}},
            "provinces": {
                "a": {"province_id": "a", "display_name": "A", "owner": "nato", "neighbors": []}
            },
            "battalions": {
                "b": {"battalion_id": "b", "faction": "nato", "province_id": "a", "roster": []}
            },
        }
        state = campaign_from_dict(legacy)
        self.assertEqual({}, state.formations)
        self.assertEqual("", state.battalions["b"].formation_id)


if __name__ == "__main__":
    unittest.main()
