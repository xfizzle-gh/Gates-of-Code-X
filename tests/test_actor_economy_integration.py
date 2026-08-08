from __future__ import annotations

import unittest

from gates_of_codex.economy import run_ai_economy, settle_round_economy
from gates_of_codex.faction_wiring_manifest import load_faction_manifest
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.actor_economy import install_actor_content
from gates_of_codex.strategic_actors import (
    assign_province_actor,
    ensure_strategic_actor_runtime,
)


class ActorEconomyIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_bundled_scenario()
        ensure_strategic_formations(self.state)
        install_actor_content(self.state, _resolved_payload(), selected_actor_id="fra")

    def test_legacy_round_entrypoint_delegates_to_actor_economy(self) -> None:
        province = next(value for value in self.state.provinces.values() if value.owner == Faction.NATO)
        assign_province_actor(self.state, province.province_id, "fra")
        legacy_resources = self.state.factions[Faction.NATO.value].resources

        reports = settle_round_economy(self.state)

        by_actor = {report.actor_id: report for report in reports}
        self.assertEqual(by_actor["fra"].income, province.resource_yield)
        self.assertEqual(by_actor["deu"].income, 0)
        self.assertEqual(self.state.factions[Faction.NATO.value].resources, legacy_resources)
        self.assertIn("last_round_economy", self.state.map_metadata["actor_content_runtime"])

    def test_legacy_ai_entrypoint_delegates_without_shared_treasury(self) -> None:
        legacy_resources = self.state.factions[Faction.RUSSIA.value].resources
        actors_before = ensure_strategic_actor_runtime(self.state)
        dprk_before = actors_before["dprk"].resources
        rus_before = actors_before["rus"].resources

        actions = run_ai_economy(self.state, Faction.RUSSIA)

        self.assertTrue(actions)
        self.assertTrue(all(action["action"].startswith("actor_") for action in actions))
        actors_after = ensure_strategic_actor_runtime(self.state)
        self.assertLess(actors_after["dprk"].resources, dprk_before)
        self.assertLess(actors_after["rus"].resources, rus_before)
        self.assertEqual(self.state.factions[Faction.RUSSIA.value].resources, legacy_resources)


def _resolved_payload() -> dict:
    manifest = load_faction_manifest()
    actors = []
    for raw in manifest["actors"]:
        actor_id = raw["actor_id"]
        unit_name = f"integration_{actor_id}"
        root_key = f"actor:{actor_id}:root"
        unit_key = f"actor:{actor_id}:unit:{unit_name}"
        actors.append({
            "actor_id": actor_id,
            "display_name": raw["display_name"],
            "actor_type": raw["actor_type"],
            "coalition_id": raw["coalition_id"],
            "tactical_side": raw["tactical_side"],
            "playable": raw["playable"],
            "roster_class": raw["roster_class"],
            "components": list(raw["components"]),
            "unit_count": 1,
            "modern_unit_count": 1,
            "legacy_unit_count": 0,
            "virtual_unit_count": 0,
            "category_counts": {"infantry": 1},
            "required_categories": ["infantry"],
            "missing_categories": [],
            "units": [{
                "unit_name": unit_name,
                "actor_id": actor_id,
                "component_id": raw["components"][0],
                "source_side": raw["tactical_side"],
                "tactical_side": raw["tactical_side"],
                "period": "2022s",
                "category": "infantry",
                "members": {"integration_rifleman": 5},
                "vehicles": [],
                "actions": [],
                "materializable": True,
                "source_files": ["integration.set"],
                "source_layer": "Code:X",
                "source_priority": 1,
                "virtual": False,
                "tier": 1,
                "research_cost": 1,
            }],
            "research_node_count": 2,
            "research_nodes": [
                {
                    "key": root_key,
                    "actor_id": actor_id,
                    "node_type": "root",
                    "display_name": f"{raw['display_name']} Armed Forces",
                    "cost": 0,
                    "prerequisites": [],
                    "unlock_units": [],
                    "source_node": "",
                    "source_file": "",
                    "component_id": "",
                },
                {
                    "key": unit_key,
                    "actor_id": actor_id,
                    "node_type": "unit",
                    "display_name": unit_name,
                    "cost": 2,
                    "prerequisites": [root_key],
                    "unlock_units": [unit_name],
                    "source_node": unit_name,
                    "source_file": "integration.set",
                    "component_id": raw["components"][0],
                },
            ],
            "notes": [],
        })
    return {
        "schema": "gates-of-codex.resolved-factions",
        "schema_version": 1,
        "manifest_schema_version": 1,
        "stack_signature": "integration-stack",
        "manifest_sha256": "integration-manifest",
        "wiring_signature": "integration-wiring",
        "source_policy": {"modern_authority": "Code:X", "legacy_authority": "West81"},
        "source_layers": [
            {"priority": 0, "name": "West81", "path": "integration/West81"},
            {"priority": 1, "name": "Code:X", "path": "integration/CodeX"},
        ],
        "actor_count": len(actors),
        "actors": actors,
        "problems": [],
        "error_count": 0,
        "warning_count": 0,
    }


if __name__ == "__main__":
    unittest.main()
