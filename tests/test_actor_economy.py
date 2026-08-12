from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.actor_economy import (
    ACTOR_CONTENT_KEY,
    actor_content_snapshot,
    actor_recruitment_offers,
    assign_actor_reinforcements,
    available_actor_research,
    install_actor_content,
    purchase_actor_reinforcements,
    purchase_actor_research,
    settle_actor_round_economy,
    validate_actor_content_runtime,
)
from gates_of_codex.faction_wiring_manifest import load_faction_manifest
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import (
    assign_province_actor,
    assign_strategic_formation_actor,
    ensure_strategic_actor_runtime,
)


class ActorEconomyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_bundled_scenario("legacy_goe_europe")
        ensure_strategic_formations(self.state)
        self.payload = _resolved_payload()
        install_actor_content(self.state, self.payload, selected_actor_id="fra")

    def test_installs_all_actor_content_and_records_grandfathered_units(self) -> None:
        runtime = self.state.map_metadata[ACTOR_CONTENT_KEY]
        self.assertEqual(runtime["actor_count"], 61)
        self.assertTrue(runtime["migration_exceptions"])
        self.assertTrue(all("grandfathered" in item["reason"] for item in runtime["migration_exceptions"]))
        validate_actor_content_runtime(self.state)

    def test_france_and_germany_share_nato_without_roster_leakage(self) -> None:
        force = _force_for_side(self.state, Faction.NATO)
        assign_strategic_formation_actor(self.state, force.strategic_formation_id, "fra")
        offers = actor_recruitment_offers(self.state, force.strategic_formation_id)
        names = {offer.unit_name for offer in offers}
        self.assertEqual(names, {"fixture_fra"})
        self.assertNotIn("fixture_deu", names)
        self.assertTrue(all(offer.tactical_side == "nato" for offer in offers))

    def test_north_korea_cannot_recruit_russian_unit(self) -> None:
        force = _force_for_side(self.state, Faction.RUSSIA)
        assign_strategic_formation_actor(self.state, force.strategic_formation_id, "dprk")
        names = {offer.unit_name for offer in actor_recruitment_offers(self.state, force.strategic_formation_id)}
        self.assertEqual(names, {"fixture_dprk"})
        self.assertNotIn("fixture_rus", names)

    def test_research_purchase_reinforcement_purchase_and_assignment(self) -> None:
        force = _single_battalion_force(self.state, Faction.NATO)
        assign_strategic_formation_actor(self.state, force.strategic_formation_id, "fra")
        research = available_actor_research(self.state, "fra")
        self.assertEqual([item.key for item in research], ["actor:fra:unit:fixture_fra"])
        purchase_actor_research(self.state, "fra", research[0].key)
        offer = next(item for item in actor_recruitment_offers(self.state, force.strategic_formation_id) if item.unit_name == "fixture_fra")
        self.assertTrue(offer.unlocked)
        purchase = purchase_actor_reinforcements(self.state, force.strategic_formation_id, "fixture_fra", 2)
        self.assertEqual(purchase.pool_quantity, 2)
        transfer = assign_actor_reinforcements(
            self.state,
            force.strategic_formation_id,
            "fixture_fra",
            2,
            battalion_id=force.battalion_ids[0],
        )
        self.assertEqual(transfer.expansion, 2)
        battalion = self.state.battalions[force.battalion_ids[0]]
        self.assertEqual(next(item.quantity for item in battalion.roster if item.unit_name == "fixture_fra"), 2)

    def test_round_income_is_actor_owned_not_tactical_side_shared(self) -> None:
        province = next(value for value in self.state.provinces.values() if value.owner == Faction.NATO)
        assign_province_actor(self.state, province.province_id, "fra")
        actors_before = ensure_strategic_actor_runtime(self.state)
        france_before = actors_before["fra"].resources
        germany_before = actors_before["deu"].resources
        reports = {item.actor_id: item for item in settle_actor_round_economy(self.state)}
        self.assertEqual(reports["fra"].income, province.resource_yield)
        self.assertEqual(reports["deu"].income, 0)
        actors_after = ensure_strategic_actor_runtime(self.state)
        self.assertGreaterEqual(actors_after["fra"].resources, 0)
        self.assertLessEqual(actors_after["fra"].resources, france_before + province.resource_yield)
        self.assertLessEqual(actors_after["deu"].resources, germany_before)

    def test_round_trip_preserves_actor_content(self) -> None:
        before = actor_content_snapshot(self.state)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(self.state, path)
            loaded = load_campaign(path)
        self.assertEqual(actor_content_snapshot(loaded), before)

    def test_warnings_are_rejected_by_default(self) -> None:
        state = load_bundled_scenario("legacy_goe_europe")
        ensure_strategic_formations(state)
        payload = _resolved_payload()
        payload["warning_count"] = 1
        with self.assertRaises(ValueError):
            install_actor_content(state, payload, selected_actor_id="fra")

    def test_cross_actor_research_key_is_rejected(self) -> None:
        state = load_bundled_scenario("legacy_goe_europe")
        ensure_strategic_formations(state)
        payload = _resolved_payload()
        france = next(item for item in payload["actors"] if item["actor_id"] == "fra")
        france["research_nodes"][1]["key"] = "actor:deu:unit:stolen"
        with self.assertRaises(ValueError):
            install_actor_content(state, payload, selected_actor_id="fra")


def _resolved_payload() -> dict:
    manifest = load_faction_manifest()
    actors = []
    for raw in manifest["actors"]:
        actor_id = raw["actor_id"]
        strategic_only = raw.get("roster_class") == "strategic_only" or not raw.get("components")
        if strategic_only:
            actors.append({
                "actor_id": actor_id,
                "display_name": raw["display_name"],
                "actor_type": raw["actor_type"],
                "coalition_id": raw["coalition_id"],
                "tactical_side": raw["tactical_side"],
                "playable": raw["playable"],
                "roster_class": raw["roster_class"],
                "components": list(raw["components"]),
                "unit_count": 0,
                "modern_unit_count": 0,
                "legacy_unit_count": 0,
                "virtual_unit_count": 0,
                "category_counts": {},
                "required_categories": [],
                "missing_categories": [],
                "units": [],
                "research_node_count": 0,
                "research_nodes": [],
                "notes": [],
            })
            continue
        unit_name = f"fixture_{actor_id}"
        root_key = f"actor:{actor_id}:root"
        unit_key = f"actor:{actor_id}:unit:{unit_name}"
        component_id = raw["components"][0]
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
                "component_id": component_id,
                "source_side": raw["tactical_side"],
                "tactical_side": raw["tactical_side"],
                "period": "2022s",
                "category": "infantry",
                "members": {"fixture_rifleman": 5},
                "vehicles": [],
                "actions": [],
                "materializable": True,
                "source_files": ["fixture.set"],
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
                    "source_file": "fixture.set",
                    "component_id": component_id,
                },
            ],
            "notes": [],
        })
    return {
        "schema": "gates-of-codex.resolved-factions",
        "schema_version": 1,
        "manifest_schema_version": 1,
        "stack_signature": "fixture-stack",
        "manifest_sha256": "fixture-manifest",
        "wiring_signature": "fixture-wiring",
        "source_policy": {"modern_authority": "Code:X", "legacy_authority": "West81"},
        "source_layers": [
            {"priority": 0, "name": "West81", "path": "fixture/West81"},
            {"priority": 1, "name": "Code:X", "path": "fixture/CodeX"},
        ],
        "actor_count": len(actors),
        "actors": actors,
        "problems": [],
        "error_count": 0,
        "warning_count": 0,
    }


def _force_for_side(state, faction: Faction):
    return next(value for value in state.strategic_formations.values() if value.faction == faction)


def _single_battalion_force(state, faction: Faction):
    return next(
        value
        for value in state.strategic_formations.values()
        if value.faction == faction and len([item for item in value.battalion_ids if item in state.battalions]) == 1
    )


if __name__ == "__main__":
    unittest.main()
