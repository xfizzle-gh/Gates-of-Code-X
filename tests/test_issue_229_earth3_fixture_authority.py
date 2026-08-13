from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from gates_of_codex.earth3_fixture_authority import (
    FIXTURE_AUTHORITY_KEY,
    FIXTURE_SCENARIO_ID,
    Earth3FixtureAuthorityError,
    _require_exact_manifest,
    authored_fixture_authority_marker,
    load_fixture_manifest,
    validate_earth3_native_acceptance_fixture,
    validate_earth3_operational_authority,
)
from gates_of_codex.earth3_operational import (
    P3_MIGRATION_METADATA_KEY,
    P3_STARTING_FORMATION_IDS,
    Earth3OperationalAuthorityError,
    authenticate_earth3_p3_base,
    validate_earth3_p3_campaign_extension,
)
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import Faction
from gates_of_codex.scenario import DEFAULT_SCENARIO_ID, build_scenario, get_scenario
from gates_of_codex.state_io import campaign_from_dict, save_campaign

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_p2_earth3_campaign_bootstrap import _resolved_catalog


ROOT = Path(__file__).resolve().parents[1]
FROZEN_PATHS = (
    ROOT / "config/earth3/production_authority.json",
    ROOT / "config/earth3/p3_operational_authority.json",
    ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json",
    ROOT / "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json",
    ROOT / "src/gates_of_codex/data/earth3_v1/formations.json",
)
PRC_FORMATION_ID = "sf_fix_prc_acceptance"
SELECTED = {
    "nato": "sf_pol_vilnius",
    "ukr": "sf_ukr_zaporizhzhia",
    "rusa": "sf_rus_donetsk",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _production():
    return build_scenario(DEFAULT_SCENARIO_ID, resolved_catalog=_resolved_catalog())


def _fixture():
    return build_scenario(FIXTURE_SCENARIO_ID, resolved_catalog=_resolved_catalog())


class _CachedStates(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.production = _production()
        cls.fixture = _fixture()

    def _production_copy(self):
        return copy.deepcopy(self.production)

    def _fixture_copy(self):
        return copy.deepcopy(self.fixture)


class FrozenAuthorityTests(_CachedStates):
    def test_frozen_earth3_bytes_are_unchanged(self) -> None:
        self.assertEqual(
            "e8ae502e05ea30233d52257a3cfba7509250601015c2ea00f1acdbe32c63b31c",
            _sha256(ROOT / "src/gates_of_codex/data/earth3_v1/formations.json"),
        )
        for path in FROZEN_PATHS:
            self.assertTrue(path.is_file(), path)
        self.assertEqual(P3_STARTING_FORMATION_IDS, set(self.production.strategic_formations))
        self.assertNotIn(PRC_FORMATION_ID, P3_STARTING_FORMATION_IDS)


class DispatchContractTests(_CachedStates):
    def test_earth3_v1_without_marker_uses_production_validator(self) -> None:
        state = self._production_copy()
        provinces = validate_earth3_operational_authority(state)
        self.assertTrue(provinces)
        self.assertNotIn(FIXTURE_AUTHORITY_KEY, state.map_metadata)
        self.assertEqual(DEFAULT_SCENARIO_ID, state.map_metadata["scenario_id"])

    def test_earth3_v1_with_valid_looking_marker_fails(self) -> None:
        state = self._production_copy()
        state.map_metadata[FIXTURE_AUTHORITY_KEY] = authored_fixture_authority_marker()
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "cannot carry"):
            validate_earth3_operational_authority(state)
        validate_earth3_p3_campaign_extension(state)

    def test_earth3_v1_with_fixture_prc_fails_production_validator(self) -> None:
        production = self._production_copy()
        production.strategic_formations[PRC_FORMATION_ID] = copy.deepcopy(
            self.fixture.strategic_formations[PRC_FORMATION_ID]
        )
        with self.assertRaises(Earth3OperationalAuthorityError):
            validate_earth3_p3_campaign_extension(production)
        with self.assertRaises(Earth3OperationalAuthorityError):
            validate_earth3_operational_authority(production)

    def test_earth3_v1_with_marker_and_prc_fails_both_paths(self) -> None:
        production = self._production_copy()
        production.map_metadata[FIXTURE_AUTHORITY_KEY] = authored_fixture_authority_marker()
        production.strategic_formations[PRC_FORMATION_ID] = copy.deepcopy(
            self.fixture.strategic_formations[PRC_FORMATION_ID]
        )
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "cannot carry"):
            validate_earth3_operational_authority(production)
        with self.assertRaises(Earth3OperationalAuthorityError):
            validate_earth3_p3_campaign_extension(production)

    def test_fixture_scenario_without_marker_fails(self) -> None:
        state = self._fixture_copy()
        del state.map_metadata[FIXTURE_AUTHORITY_KEY]
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "requires exact fixture"):
            validate_earth3_operational_authority(state)

    def test_fixture_scenario_with_malformed_marker_fails(self) -> None:
        state = self._fixture_copy()
        state.map_metadata[FIXTURE_AUTHORITY_KEY] = {"debug": True}
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "marker"):
            validate_earth3_operational_authority(state)

    def test_unknown_scenario_with_marker_fails(self) -> None:
        state = self._fixture_copy()
        state.map_metadata["scenario_id"] = "not-a-scenario"
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "illegal on scenario"):
            validate_earth3_operational_authority(state)

    def test_exact_fixture_identity_uses_fixture_validator(self) -> None:
        state = self._fixture_copy()
        provinces = validate_earth3_operational_authority(state)
        self.assertIn("e3_2795", provinces)
        self.assertIn(PRC_FORMATION_ID, state.strategic_formations)
        validate_earth3_native_acceptance_fixture(state)

    def test_direct_production_validator_rejects_fixture_expanded_state(self) -> None:
        state = self._fixture_copy()
        with self.assertRaisesRegex(
            Earth3OperationalAuthorityError,
            "outside the authorized P2 initialization set",
        ):
            validate_earth3_p3_campaign_extension(state)


class FixturePrimitiveTests(_CachedStates):
    def test_default_new_campaign_identity_remains_earth3_v1(self) -> None:
        self.assertEqual("earth3_v1", DEFAULT_SCENARIO_ID)
        production = get_scenario(DEFAULT_SCENARIO_ID)
        fixture = get_scenario(FIXTURE_SCENARIO_ID)
        self.assertEqual("production", production.status)
        self.assertEqual("debug", fixture.status)
        self.assertNotEqual(production.scenario_id, fixture.scenario_id)

    def test_fixture_contains_required_identities(self) -> None:
        for expected in SELECTED.values():
            self.assertIn(expected, self.fixture.strategic_formations)
        prc = self.fixture.strategic_formations[PRC_FORMATION_ID]
        self.assertEqual("prc", prc.actor_id)
        self.assertEqual(Faction.PRC, prc.faction)
        self.assertEqual("e3_2795", prc.province_id)
        self.assertIsNone(self.fixture.pending_battle)

    def test_fixture_does_not_mutate_production_ownership(self) -> None:
        self.assertEqual(
            {pid: row.owner for pid, row in self.production.provinces.items()},
            {pid: row.owner for pid, row in self.fixture.provinces.items()},
        )
        self.assertEqual(Faction.NEUTRAL, self.fixture.provinces["e3_2795"].owner)

    def test_fixture_validation_rejects_unknown_formation(self) -> None:
        state = self._fixture_copy()
        extra = copy.deepcopy(state.strategic_formations[PRC_FORMATION_ID])
        extra.strategic_formation_id = "sf_fix_unknown"
        state.strategic_formations["sf_fix_unknown"] = extra
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "allowlist"):
            validate_earth3_native_acceptance_fixture(state)

    def test_fixture_validation_rejects_actor_substitution(self) -> None:
        state = self._fixture_copy()
        force = state.strategic_formations[PRC_FORMATION_ID]
        force.template_formation_id = "toe_sf_pol_vilnius"
        force.faction = Faction.NATO
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "substitution"):
            validate_earth3_native_acceptance_fixture(state)

    def test_fixture_validation_rejects_off_graph_position(self) -> None:
        state = self._fixture_copy()
        force = state.strategic_formations[PRC_FORMATION_ID]
        force.province_id = "e3_0000"
        force.position.node_id = "op-node-e3_0000-anchor"
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "PRC"):
            validate_earth3_native_acceptance_fixture(state)

    def test_deterministic_regeneration(self) -> None:
        self.assertEqual(self.fixture.to_dict(), _fixture().to_dict())

    def test_round_trip_preserves_fixture_identity(self) -> None:
        import tempfile

        original = self._fixture_copy()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(original, path)
            loaded = campaign_from_dict(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(FIXTURE_SCENARIO_ID, loaded.map_metadata["scenario_id"])
        self.assertIn(PRC_FORMATION_ID, loaded.strategic_formations)
        validate_earth3_operational_authority(loaded)

    def test_frontend_snapshot_identifies_debug_fixture(self) -> None:
        snapshot = build_frontend_snapshot(self._fixture_copy())
        encoded = json.dumps(snapshot)
        self.assertIn(FIXTURE_SCENARIO_ID, encoded)
        self.assertNotIn('"scenario_id": "earth3_v1"', encoded)


class ProductionIsolationTests(_CachedStates):
    def test_production_start_state_is_unchanged(self) -> None:
        first = self.production
        second = _production()
        self.assertEqual(set(first.strategic_formations), P3_STARTING_FORMATION_IDS)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertNotIn(PRC_FORMATION_ID, first.strategic_formations)
        self.assertNotIn(FIXTURE_AUTHORITY_KEY, first.map_metadata)

    def test_unknown_scenario_still_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown scenario ID"):
            build_scenario("not-a-scenario")


class SharedP3BaseTests(_CachedStates):
    def test_both_paths_reject_disabled_maneuver(self) -> None:
        production = self._production_copy()
        fixture = self._fixture_copy()
        production.map_metadata["operational_maneuver_enabled"] = False
        fixture.map_metadata["operational_maneuver_enabled"] = False
        with self.assertRaisesRegex(Earth3OperationalAuthorityError, "operational maneuver"):
            validate_earth3_p3_campaign_extension(production)
        with self.assertRaisesRegex(Earth3OperationalAuthorityError, "operational maneuver"):
            validate_earth3_native_acceptance_fixture(fixture)
        with self.assertRaisesRegex(Earth3OperationalAuthorityError, "operational maneuver"):
            validate_earth3_operational_authority(fixture)
        self._assert_save_load_rejects(fixture)

    def test_both_paths_reject_missing_p3_migration(self) -> None:
        production = self._production_copy()
        fixture = self._fixture_copy()
        del production.map_metadata[P3_MIGRATION_METADATA_KEY]
        del fixture.map_metadata[P3_MIGRATION_METADATA_KEY]
        with self.assertRaisesRegex(Earth3OperationalAuthorityError, "migration provenance"):
            validate_earth3_p3_campaign_extension(production)
        with self.assertRaisesRegex(Earth3OperationalAuthorityError, "migration provenance"):
            validate_earth3_native_acceptance_fixture(fixture)
        self._assert_save_load_rejects(fixture)

    def test_both_paths_reject_tampered_p3_migration(self) -> None:
        production = self._production_copy()
        fixture = self._fixture_copy()
        production.map_metadata[P3_MIGRATION_METADATA_KEY]["placement"] = "tampered"
        fixture.map_metadata[P3_MIGRATION_METADATA_KEY]["placement"] = "tampered"
        with self.assertRaisesRegex(Earth3OperationalAuthorityError, "migration provenance"):
            validate_earth3_p3_campaign_extension(production)
        with self.assertRaisesRegex(Earth3OperationalAuthorityError, "migration provenance"):
            validate_earth3_native_acceptance_fixture(fixture)
        self._assert_save_load_rejects(fixture)

    def test_both_paths_authenticate_the_same_p3_base(self) -> None:
        production_base = authenticate_earth3_p3_base(self._production_copy())
        fixture_base = authenticate_earth3_p3_base(self._fixture_copy())
        self.assertEqual(production_base["graph_provinces"], fixture_base["graph_provinces"])
        self.assertEqual(production_base["node_ids"], fixture_base["node_ids"])
        self.assertTrue(self.production.map_metadata["operational_maneuver_enabled"] is True)
        self.assertTrue(self.fixture.map_metadata["operational_maneuver_enabled"] is True)
        self.assertEqual(
            self.production.map_metadata[P3_MIGRATION_METADATA_KEY],
            self.fixture.map_metadata[P3_MIGRATION_METADATA_KEY],
        )

    def _assert_save_load_rejects(self, state) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            path.write_text(json.dumps(state.to_dict()), encoding="utf-8")
            with self.assertRaises(Earth3OperationalAuthorityError):
                campaign_from_dict(json.loads(path.read_text(encoding="utf-8")))


class ManifestParserTests(unittest.TestCase):
    def test_committed_manifest_is_exact(self) -> None:
        manifest = load_fixture_manifest()
        self.assertEqual(FIXTURE_SCENARIO_ID, manifest["fixture_id"])
        self.assertIs(False, manifest["production_scenario"])
        self.assertIsInstance(manifest["schema_version"], int)
        self.assertNotIsInstance(manifest["schema_version"], bool)

    def test_extra_field_is_rejected(self) -> None:
        payload = load_fixture_manifest()
        payload["debug"] = True
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "fields are not exact"):
            _require_exact_manifest(payload)

    def test_coercible_wrong_types_are_rejected(self) -> None:
        payload = load_fixture_manifest()
        payload["schema_version"] = True
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "must be an int"):
            _require_exact_manifest(payload)
        payload = load_fixture_manifest()
        payload["production_scenario"] = 0
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "must be a bool"):
            _require_exact_manifest(payload)


if __name__ == "__main__":
    unittest.main()

