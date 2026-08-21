from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.actor_economy import ACTOR_CONTENT_KEY
from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.cli import main as cli_main
from gates_of_codex.diplomacy import are_allied
from gates_of_codex.earth3_bootstrap import (
    BOOTSTRAP_METADATA_KEY,
    Earth3BootstrapError,
    build_earth3_v1_campaign,
    load_earth3_bootstrap,
    validate_earth3_bootstrap_provenance,
)
from gates_of_codex.faction_wiring_manifest import (
    _canonical_sha256 as manifest_sha256,
    load_faction_manifest,
)
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import Faction
from gates_of_codex.play_context import list_front_options
from gates_of_codex.scenario import build_scenario
from gates_of_codex.state_io import campaign_from_dict
from gates_of_codex.strategic import build_infrastructure, construction_options
from gates_of_codex.strategic_ai import StrategicAI
from gates_of_codex.strategic_actors import ACTOR_RUNTIME_KEY


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "src" / "gates_of_codex" / "data" / "earth3_v1"
EXPECTED_FOOTPRINT = {
    "e3_0442",
    "e3_0504",
    "e3_0513",
    "e3_0592",
    "e3_1208",
    "e3_1749",
    "e3_1937",
    "e3_1962",
    "e3_2793",
    "e3_2794",
    "e3_3380",
}
EXPECTED_MAPPING = {
    "Berlin": (592, "e3_0592"),
    "Tallinn": (513, "e3_0513"),
    "Riga": (504, "e3_0504"),
    "Vilnius": (442, "e3_0442"),
    "Kyiv": (3757, "e3_1937"),
    "Odesa": (3241, "e3_1749"),
    "Kherson": (1271, "e3_1208"),
    "Zaporizhzhia": (3782, "e3_1962"),
    "Rostov-on-Don": (10868, "e3_2793"),
    "Luhansk": (10869, "e3_2794"),
    "Donetsk": (12175, "e3_3380"),
}


def _resolved_catalog(*, source_prefix: str = "fixture") -> dict:
    manifest = load_faction_manifest()
    actors = []
    for raw in manifest["actors"]:
        actor_id = raw["actor_id"]
        root_key = f"actor:{actor_id}:root"
        units = []
        nodes = [
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
            }
        ]
        strategic_only = raw.get("roster_class") == "strategic_only" or not raw.get("components")
        if not strategic_only:
            component_id = raw["components"][0]
            for category in ("infantry", "tank", "artillery"):
                unit_name = f"{source_prefix}_{actor_id}_{category}"
                unit_key = f"actor:{actor_id}:unit:{unit_name}"
                units.append(
                    {
                        "unit_name": unit_name,
                        "actor_id": actor_id,
                        "component_id": component_id,
                        "source_side": raw["tactical_side"],
                        "tactical_side": raw["tactical_side"],
                        "period": "2022s",
                        "category": category,
                        "members": {"fixture_crew": 5} if category == "infantry" else {},
                        "vehicles": [] if category == "infantry" else [f"fixture_{category}"],
                        "actions": [],
                        "materializable": True,
                        "source_files": [f"{source_prefix}/{actor_id}/{category}.set"],
                        "source_layer": "gates_codex",
                        "source_priority": 4,
                        "virtual": False,
                        "tier": 1,
                        "research_cost": 1,
                    }
                )
                nodes.append(
                    {
                        "key": unit_key,
                        "actor_id": actor_id,
                        "node_type": "unit",
                        "display_name": unit_name,
                        "cost": 2,
                        "prerequisites": [root_key],
                        "unlock_units": [unit_name],
                        "source_node": unit_name,
                        "source_file": f"{source_prefix}/{actor_id}/{category}.set",
                        "component_id": component_id,
                    }
                )
        actors.append(
            {
                "actor_id": actor_id,
                "display_name": raw["display_name"],
                "actor_type": raw["actor_type"],
                "coalition_id": raw["coalition_id"],
                "tactical_side": raw["tactical_side"],
                "playable": raw["playable"],
                "roster_class": raw["roster_class"],
                "components": list(raw["components"]),
                "unit_count": len(units),
                "modern_unit_count": len(units),
                "legacy_unit_count": 0,
                "virtual_unit_count": 0,
                "category_counts": (
                    {}
                    if strategic_only
                    else {category: 1 for category in ("infantry", "tank", "artillery")}
                ),
                "required_categories": list(raw["required_categories"]),
                "missing_categories": [],
                "units": units,
                "research_node_count": len(nodes),
                "research_nodes": nodes if not strategic_only else [],
                "notes": [],
            }
        )
    return {
        "schema": "gates-of-codex.resolved-factions",
        "schema_version": 1,
        "manifest_schema_version": 1,
        "stack_signature": "path-dependent-fixture-signature",
        "manifest_sha256": manifest_sha256(manifest),
        "wiring_signature": "path-dependent-fixture-wiring",
        "source_policy": copy.deepcopy(manifest["source_policy"]),
        "source_layers": [
            {"priority": 0, "name": "vanilla", "path": "C:/first/location/vanilla"},
            {"priority": 4, "name": "gates_codex", "path": "C:/first/location/gates"},
        ],
        "actor_count": len(actors),
        "actors": actors,
        "problems": [],
        "error_count": 0,
        "warning_count": 0,
    }


def _campaign():
    return build_earth3_v1_campaign(resolved_catalog=_resolved_catalog())


def _raw_sha_map(root: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.glob("*.json"))
    }


@contextmanager
def _mutable_bundle():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "earth3_v1"
        shutil.copytree(DATA_ROOT, root)
        with patch("gates_of_codex.earth3_bootstrap._bootstrap_data_root", return_value=root):
            yield root


@contextmanager
def _repin_bundle(root: Path):
    with patch(
        "gates_of_codex.earth3_bootstrap._APPROVED_RAW_FILE_SHA256",
        _raw_sha_map(root),
    ):
        yield


class Earth3P2ScenarioSelectionTests(unittest.TestCase):
    def test_earth3_remains_default_and_applies_p2_bootstrap(self) -> None:
        state = build_scenario("earth3_v1", resolved_catalog=_resolved_catalog())
        self.assertEqual("earth3_v1", state.map_metadata["scenario_id"])
        self.assertEqual("earth3_v1_campaign_bootstrap", state.map_metadata[BOOTSTRAP_METADATA_KEY]["bootstrap_id"])

    def test_default_does_not_invoke_either_legacy_builder(self) -> None:
        with patch("gates_of_codex.scenario._build_legacy_goe_europe") as europe, patch(
            "gates_of_codex.scenario._build_legacy_goe_europe_mediterranean"
        ) as mediterranean:
            build_scenario(resolved_catalog=_resolved_catalog())
        europe.assert_not_called()
        mediterranean.assert_not_called()

    def test_legacy_scenarios_reject_p2_builder_options_and_keep_map_identity(self) -> None:
        with self.assertRaises(TypeError):
            build_scenario("legacy_goe_europe", resolved_catalog=_resolved_catalog())
        legacy = build_scenario("legacy_goe_europe")
        mediterranean = build_scenario("legacy_goe_europe_mediterranean")
        self.assertEqual("goe_europe_alpha_graph_v1", legacy.map_id)
        self.assertEqual("europe_mediterranean_from_goe", mediterranean.map_id)


class Earth3P2MappingAndBundleTests(unittest.TestCase):
    def test_all_city_mappings_join_committed_location_and_dataset_authority(self) -> None:
        bundle = load_earth3_bootstrap()
        actual = {
            row["display_name"]: (row["source_province_id"], row["province_id"])
            for row in bundle.documents["province_mappings.json"]["mappings"]
        }
        self.assertEqual(EXPECTED_MAPPING, actual)
        self.assertEqual(EXPECTED_FOOTPRINT, set(bundle.footprint))

    def test_unproven_source_id_is_rejected_after_exact_byte_gate(self) -> None:
        with _mutable_bundle() as root:
            path = root / "province_mappings.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["mappings"][0]["source_province_id"] = 999999
            path.write_bytes((json.dumps(payload, indent=2) + "\n").encode())
            with _repin_bundle(root), self.assertRaisesRegex(Earth3BootstrapError, "committed location authority"):
                load_earth3_bootstrap()

    def test_dataset_stable_id_substitution_is_rejected(self) -> None:
        with _mutable_bundle() as root:
            path = root / "province_mappings.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["mappings"][0]["province_id"] = "e3_0001"
            path.write_bytes((json.dumps(payload, indent=2) + "\n").encode())
            with _repin_bundle(root), self.assertRaisesRegex(Earth3BootstrapError, "production dataset"):
                load_earth3_bootstrap()

    def test_crlf_conversion_changes_raw_identity(self) -> None:
        with _mutable_bundle() as root:
            path = root / "factions.json"
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            with self.assertRaisesRegex(Earth3BootstrapError, "raw SHA-256"):
                load_earth3_bootstrap()

    def test_trailing_byte_changes_raw_identity(self) -> None:
        with _mutable_bundle() as root:
            path = root / "objectives.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(Earth3BootstrapError, "raw SHA-256"):
                load_earth3_bootstrap()

    def test_missing_terminal_lf_changes_raw_identity(self) -> None:
        with _mutable_bundle() as root:
            path = root / "sites.json"
            path.write_bytes(path.read_bytes().removesuffix(b"\n"))
            with self.assertRaisesRegex(Earth3BootstrapError, "raw SHA-256"):
                load_earth3_bootstrap()

    def test_duplicate_json_key_is_rejected_even_when_repinned(self) -> None:
        with _mutable_bundle() as root:
            path = root / "bootstrap.json"
            path.write_bytes(b'{"bootstrap_id":"x","bootstrap_id":"y"}\n')
            with _repin_bundle(root), self.assertRaisesRegex(Earth3BootstrapError, "duplicate JSON key"):
                load_earth3_bootstrap()

    def test_symlinked_fixed_file_is_rejected(self) -> None:
        with _mutable_bundle() as root:
            source = root / "ownership.json"
            target = root.parent / "ownership.real.json"
            target.write_bytes(source.read_bytes())
            source.unlink()
            try:
                source.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaisesRegex(Earth3BootstrapError, "symlink|reparse"):
                load_earth3_bootstrap()

    def test_symlinked_intermediate_data_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "real" / "earth3_v1"
            shutil.copytree(DATA_ROOT, real)
            link_parent = base / "linked"
            try:
                link_parent.symlink_to(base / "real", target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink creation unavailable: {exc}")
            with patch(
                "gates_of_codex.earth3_bootstrap._bootstrap_data_root",
                return_value=link_parent / "earth3_v1",
            ), self.assertRaisesRegex(Earth3BootstrapError, "symlink|reparse|canonical"):
                load_earth3_bootstrap()

    def test_geometry_route_adjacency_and_node_fields_are_forbidden_at_any_depth(self) -> None:
        for forbidden in ("vertices", "triangles", "neighbors", "routes", "edges", "operational_nodes"):
            with self.subTest(forbidden=forbidden), _mutable_bundle() as root:
                path = root / "bootstrap.json"
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["forbidden_probe"] = {forbidden: []}
                path.write_bytes((json.dumps(payload, indent=2) + "\n").encode())
                with _repin_bundle(root), self.assertRaisesRegex(Earth3BootstrapError, forbidden):
                    load_earth3_bootstrap()

    def test_unknown_file_and_unknown_field_are_rejected(self) -> None:
        with _mutable_bundle() as root:
            (root / "surprise.json").write_bytes(b"{}\n")
            with self.assertRaisesRegex(Earth3BootstrapError, "unexpected bootstrap file"):
                load_earth3_bootstrap()

    def test_duplicate_dangling_unnamed_and_outside_references_fail_closed(self) -> None:
        mutations = (
            ("formations.json", lambda payload: payload["formations"].append(copy.deepcopy(payload["formations"][0])), "unique"),
            ("formations.json", lambda payload: payload["formations"][0].update({"commander_id": "missing"}), "commander mismatch"),
            ("province_mappings.json", lambda payload: payload["mappings"][0].update({"display_name": ""}), "non-empty"),
            ("sites.json", lambda payload: payload["sites"][0].update({"province_id": "e3_0001"}), "outside"),
            ("deployment_zones.json", lambda payload: payload["deployment_zones"][0]["province_ids"].append("e3_0001"), "outside"),
            ("objectives.json", lambda payload: payload["objectives"][0]["targets"].append("e3_0001"), "outside"),
        )
        for filename, mutate, error in mutations:
            with self.subTest(filename=filename, error=error), _mutable_bundle() as root:
                path = root / filename
                payload = json.loads(path.read_text(encoding="utf-8"))
                mutate(payload)
                path.write_bytes((json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode())
                with _repin_bundle(root), self.assertRaisesRegex(Earth3BootstrapError, error):
                    load_earth3_bootstrap()


class Earth3P2OpeningStateTests(unittest.TestCase):
    def test_opening_factions_alliance_and_human_actor_are_exact(self) -> None:
        state = _campaign()
        runtime = state.map_metadata[ACTOR_RUNTIME_KEY]
        self.assertEqual("usa", runtime["selected_actor_id"])
        self.assertEqual(["usa"], sorted(key for key, row in runtime["actors"].items() if row["is_human_controlled"]))
        self.assertEqual({Faction.NATO, Faction.UKRAINE}, set(state.alliances["western_coalition"].factions))
        self.assertTrue(are_allied(state, Faction.NATO, Faction.UKRAINE))
        self.assertFalse(are_allied(state, Faction.NATO, Faction.RUSSIA))
        self.assertEqual(Faction.NATO, state.current_faction)
        self.assertEqual(Faction.NATO, state.selected_faction)

    def test_formation_ownership_is_canonical_actor_scoped(self) -> None:
        state = _campaign()
        active = {force.actor_id for force in state.strategic_formations.values()}
        self.assertEqual({"usa", "deu", "pol", "ukr", "rus"}, active)
        for force in state.strategic_formations.values():
            for battalion_id in force.battalion_ids:
                self.assertEqual(force.faction, state.battalions[battalion_id].faction)

    def test_german_and_polish_units_are_not_in_usa_formations(self) -> None:
        state = _campaign()
        for force in state.strategic_formations.values():
            roster_names = [entry.unit_name for bid in force.battalion_ids for entry in state.battalions[bid].roster]
            self.assertTrue(all(name.startswith(f"fixture_{force.actor_id}_") for name in roster_names))

    def test_every_formation_has_nonempty_materializable_starter_roster_and_commander(self) -> None:
        state = _campaign()
        for force in state.strategic_formations.values():
            self.assertTrue(force.battalion_ids)
            self.assertIsNotNone(force.commander_id)
            self.assertEqual("scenario_authored_fictional_role", state.commanders[force.commander_id].source)
            for battalion_id in force.battalion_ids:
                self.assertGreater(state.battalions[battalion_id].unit_count, 0)

    def test_active_actor_resources_research_and_recruitment_are_actor_scoped(self) -> None:
        state = _campaign()
        actor_rows = state.map_metadata[ACTOR_RUNTIME_KEY]["actors"]
        content = state.map_metadata[ACTOR_CONTENT_KEY]
        for actor_id in ("usa", "deu", "pol", "ukr", "rus"):
            self.assertGreater(actor_rows[actor_id]["resources"], 0)
            self.assertTrue(actor_rows[actor_id]["researched_keys"])
            self.assertIn(actor_id, content["actors"])

    def test_prc_is_dormant_inherited_compatibility_state(self) -> None:
        state = _campaign()
        prc = state.map_metadata[ACTOR_RUNTIME_KEY]["actors"]["prc"]
        self.assertEqual(0, prc["resources"])
        self.assertTrue(prc["is_eliminated"])
        self.assertTrue(state.factions["prc"].is_eliminated)
        self.assertFalse(any(force.actor_id == "prc" for force in state.strategic_formations.values()))
        self.assertFalse(any(province.metadata.get("owner_actor_id") == "prc" for province in state.provinces.values()))
        self.assertNotIn("prc", state.map_metadata[BOOTSTRAP_METADATA_KEY]["active_actor_ids"])

    def test_ownership_names_sites_deployment_objectives_and_tactical_maps_stay_in_footprint(self) -> None:
        state = _campaign()
        footprint = set(state.map_metadata[BOOTSTRAP_METADATA_KEY]["footprint"])
        self.assertEqual(EXPECTED_FOOTPRINT, footprint)
        for province_id in footprint:
            self.assertNotEqual(province_id, state.provinces[province_id].display_name)
        authored = state.map_metadata[BOOTSTRAP_METADATA_KEY]["scenario_references"]
        for key in ("sites", "deployment_zones", "objective_targets", "capital_provinces", "tactical_map_provinces"):
            self.assertLessEqual(set(authored[key]), footprint)
        self.assertEqual(3, len(state.map_metadata["earth3_p2_capitals"]))

    def test_opening_objectives_and_campaign_outcome_are_incomplete(self) -> None:
        state = _campaign()
        self.assertEqual("active", state.map_metadata["campaign_outcome"]["status"])
        self.assertIsNone(state.pending_battle)
        self.assertTrue(state.map_metadata["operational_objectives"])
        self.assertTrue(all(not row["completed"] for row in state.map_metadata["operational_objectives"]))

    def test_starting_ownership_and_formations_are_selectable_land_only(self) -> None:
        state = _campaign()
        for province in state.provinces.values():
            if province.owner != Faction.NEUTRAL:
                self.assertTrue(province.metadata["selectable"])
                self.assertFalse(province.metadata["is_water"])
        for force in state.strategic_formations.values():
            province = state.provinces[force.province_id]
            self.assertTrue(province.metadata["selectable"])
            self.assertFalse(province.metadata["is_water"])

    def test_sites_and_supply_hub_intents_exist_without_connectivity_claims(self) -> None:
        state = _campaign()
        sites = state.map_metadata["earth3_p2_site_intents"]
        self.assertTrue(sites)
        self.assertTrue(any(row["supply_hub_intent"] for row in sites))
        self.assertEqual("none_until_p3", state.map_metadata[BOOTSTRAP_METADATA_KEY]["supply_connectivity_authority"])

    def test_cross_faction_battalion_membership_fails_closed(self) -> None:
        state = _campaign()
        battalion = next(iter(state.battalions.values()))
        battalion.faction = Faction.RUSSIA
        with self.assertRaisesRegex(ValueError, "faction does not match formation"):
            state.validate()

    def test_no_operational_graph_routes_nodes_or_adjacency_authority_is_added(self) -> None:
        state = _campaign()
        self.assertIsNone(state.map_metadata.get("operational_graph"))
        self.assertFalse(state.map_metadata.get("operational_maneuver_enabled"))
        provenance = state.map_metadata[BOOTSTRAP_METADATA_KEY]
        self.assertEqual([], provenance["route_ids"])
        self.assertEqual([], provenance["operational_node_ids"])

    def test_frontend_snapshot_succeeds_and_preserves_production_fallback_none(self) -> None:
        snapshot = build_frontend_snapshot(_campaign())
        self.assertEqual("none", snapshot["strategic_map"]["fallback"])
        self.assertEqual("production", snapshot["strategic_map"]["status"])


class Earth3P2FootprintAndMovementTests(unittest.TestCase):
    def test_structural_polygon_neighbors_do_not_become_legal_moves(self) -> None:
        state = _campaign()
        self.assertEqual([], list_front_options(state))
        force = next(iter(state.strategic_formations.values()))
        battalion = state.battalions[force.battalion_ids[0]]
        neighbor = state.provinces[battalion.province_id].neighbors[0]
        with self.assertRaisesRegex(ValueError, "unavailable until P3"):
            CampaignEngine(state).move_or_attack(battalion.battalion_id, neighbor)

    def test_ai_does_not_fall_back_to_polygon_neighbor_movement(self) -> None:
        state = _campaign()
        actions = StrategicAI(state, random_seed=0).take_turn(Faction.RUSSIA)
        self.assertFalse(any(row.action in {"move", "capture", "attack"} for row in actions))

    def test_outside_footprint_construction_is_unavailable_and_rejected(self) -> None:
        state = _campaign()
        outside = next(province_id for province_id in state.provinces if province_id not in EXPECTED_FOOTPRINT)
        options = construction_options(state, Faction.NATO, outside)
        self.assertTrue(all("outside_scenario_footprint" in row["blocked_reasons"] for row in options))
        with self.assertRaisesRegex(ValueError, "outside Earth3 P2 footprint"):
            build_infrastructure(state, Faction.NATO, outside, "fortification")

    def test_production_selectability_is_not_rewritten_by_scenario_actionability(self) -> None:
        state = _campaign()
        outside_land = next(
            province for province in state.provinces.values()
            if province.province_id not in EXPECTED_FOOTPRINT and province.metadata["selectable"]
        )
        self.assertTrue(outside_land.metadata["selectable"])
        self.assertFalse(outside_land.metadata["scenario_actionable"])

    def test_scenario_validation_rejects_outside_mutable_references(self) -> None:
        state = _campaign()
        outside = next(province_id for province_id in state.provinces if province_id not in EXPECTED_FOOTPRINT)
        state.map_metadata["operational_objectives"][0]["targets"].append(outside)
        with self.assertRaisesRegex(Earth3BootstrapError, "objective.*outside"):
            state.validate()


class Earth3P2CliConstructionTests(unittest.TestCase):
    def test_cli_threads_only_the_explicit_stack_config_into_default_builder(self) -> None:
        state = _campaign()
        with tempfile.TemporaryDirectory() as temporary, patch(
            "gates_of_codex.cli.build_scenario", return_value=state
        ) as build, patch("gates_of_codex.cli.save_campaign") as save:
            output = Path(temporary) / "campaign.json"
            result = cli_main(
                [
                    "new",
                    str(output),
                    "--stack-config",
                    "config/validated-stack.json",
                ]
            )
        self.assertEqual(0, result)
        build.assert_called_once_with(
            "ww3_2028_core", stack_config="config/validated-stack.json"
        )
        save.assert_called_once()

    def test_cli_stack_or_bootstrap_failure_never_publishes_a_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "gates_of_codex.cli.build_scenario",
            side_effect=Earth3BootstrapError("active stack missing"),
        ), patch("gates_of_codex.cli.save_campaign") as save:
            output = Path(temporary) / "campaign.json"
            with self.assertRaisesRegex(Earth3BootstrapError, "active stack missing"):
                cli_main(["new", str(output), "--stack-config", "missing.json"])
            self.assertFalse(output.exists())
        save.assert_not_called()

    def test_cli_rejects_non_nato_tactical_selection_for_fixed_usa_seat(self) -> None:
        with patch("gates_of_codex.cli.build_scenario", return_value=_campaign()), patch(
            "gates_of_codex.cli.save_campaign"
        ) as save, self.assertRaisesRegex(ValueError, "fixed to the usa actor"):
            cli_main(
                [
                    "new",
                    "campaign.json",
                    "--scenario",
                    "earth3_v1",
                    "--stack-config",
                    "stack.json",
                    "--faction",
                    "ukr",
                ]
            )
        save.assert_not_called()


class Earth3P2PersistenceAndDeterminismTests(unittest.TestCase):
    def test_round_trip_preserves_immutable_bootstrap_provenance(self) -> None:
        state = _campaign()
        loaded = campaign_from_dict(state.to_dict())
        self.assertEqual(state.map_metadata[BOOTSTRAP_METADATA_KEY], loaded.map_metadata[BOOTSTRAP_METADATA_KEY])
        validate_earth3_bootstrap_provenance(loaded)

    def test_removed_or_substituted_bootstrap_identity_fails_closed(self) -> None:
        for mutation in ("remove", "substitute"):
            with self.subTest(mutation=mutation):
                state = _campaign()
                if mutation == "remove":
                    state.map_metadata.pop(BOOTSTRAP_METADATA_KEY)
                else:
                    state.map_metadata[BOOTSTRAP_METADATA_KEY]["bootstrap_id"] = "substituted"
                with self.assertRaisesRegex(Earth3BootstrapError, "provenance is missing|identity mismatch"):
                    state.validate()

    def test_load_does_not_reapply_opening_state_to_evolved_campaign(self) -> None:
        state = _campaign()
        province = state.provinces["e3_1937"]
        province.resource_yield += 7
        force = next(iter(state.strategic_formations.values()))
        battalion = state.battalions[force.battalion_ids[0]]
        battalion.condition = 61
        state.map_metadata[ACTOR_RUNTIME_KEY]["actors"]["usa"]["resources"] -= 25
        loaded = campaign_from_dict(state.to_dict())
        self.assertEqual(61, loaded.battalions[battalion.battalion_id].condition)
        self.assertEqual(province.resource_yield, loaded.provinces["e3_1937"].resource_yield)

    def test_catalog_identity_ignores_absolute_source_path_spelling(self) -> None:
        first = _resolved_catalog()
        second = copy.deepcopy(first)
        second["source_layers"][0]["path"] = "D:/equivalent/vanilla"
        second["source_layers"][1]["path"] = "D:/equivalent/gates"
        second["stack_signature"] = "other-path-derived-stack-signature"
        second["wiring_signature"] = "other-path-derived-wiring-signature"
        a = build_earth3_v1_campaign(resolved_catalog=first)
        b = build_earth3_v1_campaign(resolved_catalog=second)
        self.assertEqual(
            a.map_metadata[BOOTSTRAP_METADATA_KEY]["catalog_identity"],
            b.map_metadata[BOOTSTRAP_METADATA_KEY]["catalog_identity"],
        )
        serialized_runtime = json.dumps(a.map_metadata[ACTOR_CONTENT_KEY], sort_keys=True)
        self.assertNotIn("C:/first/location", serialized_runtime)
        self.assertNotIn("D:/equivalent", serialized_runtime)

    def test_catalog_content_change_changes_identity(self) -> None:
        first = _resolved_catalog()
        second = copy.deepcopy(first)
        second["actors"][0]["units"][0]["members"]["fixture_crew"] = 6
        a = build_earth3_v1_campaign(resolved_catalog=first)
        b = build_earth3_v1_campaign(resolved_catalog=second)
        self.assertNotEqual(
            a.map_metadata[BOOTSTRAP_METADATA_KEY]["catalog_identity"],
            b.map_metadata[BOOTSTRAP_METADATA_KEY]["catalog_identity"],
        )

    def test_identical_inputs_and_permuted_catalog_rows_produce_identical_campaign_bytes(self) -> None:
        first = _resolved_catalog()
        permuted = copy.deepcopy(first)
        permuted["actors"].reverse()
        for actor in permuted["actors"]:
            actor["units"].reverse()
            actor["research_nodes"].reverse()
        a = build_earth3_v1_campaign(resolved_catalog=first)
        b = build_earth3_v1_campaign(resolved_catalog=permuted)
        first_bytes = (json.dumps(a.to_dict(), indent=2, ensure_ascii=False) + "\n").encode()
        second_bytes = (json.dumps(b.to_dict(), indent=2, ensure_ascii=False) + "\n").encode()
        self.assertEqual(first_bytes, second_bytes)

    def test_missing_catalog_and_unmaterializable_required_category_fail_closed(self) -> None:
        with self.assertRaisesRegex(Earth3BootstrapError, "active stack or resolved catalog"):
            build_earth3_v1_campaign()
        payload = _resolved_catalog()
        usa = next(row for row in payload["actors"] if row["actor_id"] == "usa")
        usa["units"] = [row for row in usa["units"] if row["category"] != "tank"]
        with self.assertRaisesRegex(Earth3BootstrapError, "usa.*tank"):
            build_earth3_v1_campaign(resolved_catalog=payload)

    def test_mutable_state_changes_do_not_change_persisted_bootstrap_identity(self) -> None:
        state = _campaign()
        before = copy.deepcopy(state.map_metadata[BOOTSTRAP_METADATA_KEY])
        state.battalions[next(iter(state.battalions))].condition = 50
        state.provinces["e3_1937"].resource_yield += 1
        validate_earth3_bootstrap_provenance(state)
        self.assertEqual(before, state.map_metadata[BOOTSTRAP_METADATA_KEY])


if __name__ == "__main__":
    unittest.main()
