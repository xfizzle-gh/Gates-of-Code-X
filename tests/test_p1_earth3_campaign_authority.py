from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.cli import build_parser, main
from gates_of_codex.earth3_campaign import (
    CAMPAIGN_DATASET_IDENTIFIER,
    CAMPAIGN_MANIFEST_IDENTIFIER,
    PRODUCTION_AUTHORITY_IDENTIFIER,
    Earth3AuthorityError,
    _canonical_authority_root,
    build_earth3_campaign,
    load_earth3_authority,
)
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import Faction, FactionState
from gates_of_codex.scenario import (
    DEFAULT_SCENARIO_ID,
    build_scenario,
    get_scenario,
    load_legacy_test_scenario,
    scenario_ids,
)
from gates_of_codex.state_io import load_campaign, save_campaign


ROOT = Path(__file__).resolve().parents[1]
EARTH3_ASSETS = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
PRODUCTION_AUTHORITY = ROOT / "config/earth3/production_authority.json"
MANIFEST = EARTH3_ASSETS / "map_manifest.json"
DATASET = EARTH3_ASSETS / "polygon_dataset.json"
APPROVED_MANIFEST_SHA256 = "614a926e79f11e3cfac8c867c7bacce107fc69344b17fabb6b4545cdeaa6a357"
APPROVED_DATASET_SHA256 = "8ae59bd89419a368fe9131ef7c50d94a7f1cafacd1cfae44362ac9b5d9decced"
APPROVED_EMBEDDED_DATASET_SHA256 = (
    "8ae59c33da5094b722b1ffad61d2862cdd4805369d74d6c6298425735982a241"
)
APPROVED_DATASET_RAW_SHA256 = (
    "4aadab4b5106bbfa4c2d37e8173c3d1675f35a448cbd7f32a8b871c464ce1b84"
)
APPROVED_GEOMETRY_SHA256 = "7715807367932662642ff6d0c52faf8657b379abf6f67978a9acece3d18f2678"
APPROVED_PRODUCTION_ASSET_VERSION = "earth3_production_v1"
APPROVED_IDS_SHA256 = "f3931d2e34558e451d02a7c49270b2071a79a628668c49228f5ff607a75315b8"
APPROVED_PROVINCE_COUNT = 3514
APPROVED_LAND_COUNT = 3299
APPROVED_WATER_COUNT = 215
APPROVED_SELECTABLE_COUNT = 3299
APPROVED_TOPOLOGY_EDGE_COUNT = 10249
STALE_EMBEDDED_EDGE_COUNT = 10223
STALE_METADATA_SELECTABLE_COUNT = 3295
EARTH3_MAP_ID = "earth3_europe_mediterranean"
EARTH3_SCENARIO_ID = "earth3_v1"
LEGACY_GOE_MAP_ID = "goe_europe_alpha_graph_v1"


def _normalized_sha256(path: Path, *, strip_one_trailing_newline: bool = False) -> str:
    raw = path.read_bytes()
    if strip_one_trailing_newline:
        if not raw.endswith(b"\n"):
            raise AssertionError(f"{path} does not have the required trailing LF")
        raw = raw[:-1]
    return hashlib.sha256(raw).hexdigest()


def _windows_short_path(path: Path) -> str | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    get_short_path_name = ctypes.windll.kernel32.GetShortPathNameW
    get_short_path_name.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short_path_name.restype = wintypes.DWORD

    long_path = str(path.resolve())
    needed = get_short_path_name(long_path, None, 0)
    if needed == 0:
        return None
    buffer = ctypes.create_unicode_buffer(needed)
    if get_short_path_name(long_path, buffer, needed) == 0:
        return None
    short_path = buffer.value
    if os.path.normcase(short_path) == os.path.normcase(long_path):
        return None
    return short_path


def _all_dict_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key))
            keys.update(_all_dict_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_all_dict_keys(nested))
    return keys


def _all_strings(value) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        values.append(value)
    elif isinstance(value, dict):
        for nested in value.values():
            values.extend(_all_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            values.extend(_all_strings(nested))
    return values


class Earth3ScenarioRegistryTests(unittest.TestCase):
    def test_registry_has_exact_required_scenarios_and_default(self) -> None:
        self.assertEqual("ww3_2028_core", DEFAULT_SCENARIO_ID)
        self.assertEqual("production", get_scenario(DEFAULT_SCENARIO_ID).status)
        self.assertEqual("production", get_scenario("ww3_2028_core").status)
        self.assertEqual(EARTH3_SCENARIO_ID, get_scenario(EARTH3_SCENARIO_ID).scenario_id)
        self.assertEqual(
            (
                "earth3_v1",
                "ww3_2028_core",
                "ww3_2028_expanded",
                "legacy_goe_europe",
                "legacy_goe_europe_mediterranean",
                "earth3_native_acceptance",
            ),
            scenario_ids(),
        )
        production = get_scenario(EARTH3_SCENARIO_ID)
        self.assertEqual(EARTH3_MAP_ID, production.map_id)
        self.assertEqual("production", production.status)
        self.assertTrue(any(
            value.endswith("map_manifest.json")
            for value in production.required_asset_authority
        ))
        legacy_goe = get_scenario("legacy_goe_europe")
        legacy_em = get_scenario("legacy_goe_europe_mediterranean")
        self.assertEqual(LEGACY_GOE_MAP_ID, legacy_goe.map_id)
        self.assertEqual("legacy", legacy_goe.status)
        self.assertEqual("europe_mediterranean_from_goe", legacy_em.map_id)
        self.assertEqual("legacy", legacy_em.status)

    def test_unknown_scenario_id_fails_clearly(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Unknown scenario ID 'not-a-scenario'.*earth3_v1.*legacy_goe_europe",
        ):
            build_scenario("not-a-scenario")

    def test_default_scenario_never_invokes_a_goe_builder(self) -> None:
        with (
            patch("gates_of_codex.europe.build_goe_europe_campaign") as legacy_goe,
            patch(
                "gates_of_codex.europe_mediterranean_from_goe."
                "build_europe_mediterranean_from_goe_campaign"
            ) as legacy_em,
            patch(
                "gates_of_codex.earth3_bootstrap.build_earth3_v1_campaign",
                return_value=build_earth3_campaign(),
            ),
        ):
            state = build_scenario(EARTH3_SCENARIO_ID)
        legacy_goe.assert_not_called()
        legacy_em.assert_not_called()
        self.assertEqual(EARTH3_SCENARIO_ID, state.map_metadata["scenario_id"])
        self.assertEqual(EARTH3_MAP_ID, state.map_id)
        self.assertEqual("ww3_2028_core", DEFAULT_SCENARIO_ID)
        self.assertNotEqual(DEFAULT_SCENARIO_ID, EARTH3_SCENARIO_ID)

    def test_explicit_legacy_scenarios_remain_available_and_are_never_default(self) -> None:
        goe = build_scenario("legacy_goe_europe")
        em = build_scenario("legacy_goe_europe_mediterranean")
        self.assertEqual(LEGACY_GOE_MAP_ID, goe.map_id)
        self.assertEqual("legacy_goe_europe", goe.map_metadata["scenario_id"])
        self.assertEqual("europe_mediterranean_from_goe", em.map_id)
        self.assertEqual(
            "legacy_goe_europe_mediterranean",
            em.map_metadata["scenario_id"],
        )
        self.assertNotEqual(DEFAULT_SCENARIO_ID, goe.map_metadata["scenario_id"])
        self.assertNotEqual(DEFAULT_SCENARIO_ID, em.map_metadata["scenario_id"])


class Earth3ProductionAuthorityTests(unittest.TestCase):
    def test_committed_hashes_counts_ids_and_policies_match_approved_authority(self) -> None:
        authority = load_earth3_authority()
        self.assertEqual(APPROVED_MANIFEST_SHA256, _normalized_sha256(MANIFEST))
        self.assertEqual(
            APPROVED_EMBEDDED_DATASET_SHA256,
            _normalized_sha256(DATASET, strip_one_trailing_newline=True),
        )
        self.assertEqual(
            APPROVED_DATASET_RAW_SHA256,
            _normalized_sha256(DATASET),
        )
        self.assertEqual(APPROVED_MANIFEST_SHA256, authority.manifest_sha256)
        self.assertEqual(APPROVED_DATASET_SHA256, authority.dataset_sha256)
        self.assertEqual(
            APPROVED_EMBEDDED_DATASET_SHA256,
            authority.embedded_dataset_sha256,
        )
        self.assertEqual(APPROVED_GEOMETRY_SHA256, authority.geometry_sha256)
        self.assertEqual(
            APPROVED_PRODUCTION_ASSET_VERSION,
            authority.production_asset_version,
        )
        self.assertEqual(APPROVED_TOPOLOGY_EDGE_COUNT, authority.topology_edge_count)
        self.assertEqual(APPROVED_IDS_SHA256, authority.included_ids_sha256)
        self.assertEqual(APPROVED_PROVINCE_COUNT, len(authority.provinces))
        self.assertEqual(APPROVED_PROVINCE_COUNT, authority.manifest["province_count"])
        self.assertEqual(APPROVED_PROVINCE_COUNT, authority.dataset["province_count"])
        self.assertEqual(APPROVED_PROVINCE_COUNT, authority.metadata["province_count"])
        self.assertEqual(APPROVED_PROVINCE_COUNT, authority.production["province_count"])
        self.assertEqual(APPROVED_LAND_COUNT, authority.dataset["land_count"])
        self.assertEqual(APPROVED_LAND_COUNT, authority.metadata["land_count"])
        self.assertEqual(APPROVED_LAND_COUNT, authority.production["land_count"])
        self.assertEqual(APPROVED_WATER_COUNT, authority.dataset["water_count"])
        self.assertEqual(APPROVED_WATER_COUNT, authority.metadata["water_count"])
        self.assertEqual(APPROVED_WATER_COUNT, authority.production["water_count"])
        self.assertEqual(
            STALE_METADATA_SELECTABLE_COUNT,
            authority.metadata["selectable_province_count"],
        )
        self.assertEqual(
            APPROVED_SELECTABLE_COUNT,
            authority.production["selectable_province_count"],
        )
        self.assertEqual(
            STALE_EMBEDDED_EDGE_COUNT,
            authority.dataset["edge_count"],
        )
        self.assertEqual(
            STALE_EMBEDDED_EDGE_COUNT,
            authority.metadata["edge_count"],
        )
        self.assertEqual(
            "europe_mediterranean_from_goe",
            authority.manifest["fallback_map_id"],
        )

    def test_stale_summaries_cannot_override_actual_records_and_topology(self) -> None:
        authority = load_earth3_authority()
        self.assertEqual(STALE_EMBEDDED_EDGE_COUNT, authority.dataset["edge_count"])
        self.assertEqual(STALE_EMBEDDED_EDGE_COUNT, authority.metadata["edge_count"])
        self.assertEqual(
            STALE_METADATA_SELECTABLE_COUNT,
            authority.metadata["selectable_province_count"],
        )
        self.assertEqual(APPROVED_TOPOLOGY_EDGE_COUNT, authority.topology_edge_count)
        self.assertEqual(
            APPROVED_SELECTABLE_COUNT,
            sum(not bool(row["is_water"]) for row in authority.provinces),
        )

    def test_builder_has_no_dataset_correction_or_rewrite_path(self) -> None:
        before = DATASET.read_bytes()
        metadata_before = (EARTH3_ASSETS / "dataset_meta.json").read_bytes()
        build_earth3_campaign()
        self.assertEqual(before, DATASET.read_bytes())
        self.assertEqual(
            metadata_before,
            (EARTH3_ASSETS / "dataset_meta.json").read_bytes(),
        )

    def test_builder_projects_all_stable_ids_deterministically_without_geometry(self) -> None:
        state = build_earth3_campaign()
        dataset = json.loads(DATASET.read_text(encoding="utf-8"))
        source_ids = [str(row["id"]) for row in dataset["provinces"]]
        campaign_ids = list(state.provinces)
        self.assertEqual(APPROVED_PROVINCE_COUNT, len(campaign_ids))
        self.assertEqual(APPROVED_PROVINCE_COUNT, len(set(campaign_ids)))
        self.assertEqual(source_ids, campaign_ids)
        self.assertEqual(APPROVED_LAND_COUNT, sum(
            not province.metadata["is_water"] for province in state.provinces.values()
        ))
        self.assertEqual(APPROVED_WATER_COUNT, sum(
            province.metadata["is_water"] for province in state.provinces.values()
        ))
        self.assertEqual(APPROVED_SELECTABLE_COUNT, sum(
            province.metadata["selectable"] for province in state.provinces.values()
        ))
        serialized = state.to_dict()
        keys = _all_dict_keys(serialized)
        self.assertTrue({"source_id", "centroid", "terrain_id", "continent_id"} <= keys)
        self.assertTrue({"vertices", "triangles", "ring", "border_segments"}.isdisjoint(keys))

    def test_campaign_records_stable_relative_provenance_without_p2_content(self) -> None:
        state = build_earth3_campaign()
        metadata = state.map_metadata
        self.assertEqual(EARTH3_SCENARIO_ID, metadata["scenario_id"])
        self.assertEqual(EARTH3_MAP_ID, metadata["strategic_map_id"])
        self.assertEqual(
            "assets/maps/earth3_europe_mediterranean/map_manifest.json",
            metadata["strategic_map_manifest"],
        )
        self.assertEqual(APPROVED_MANIFEST_SHA256, metadata["manifest_sha256"])
        self.assertEqual(APPROVED_DATASET_SHA256, metadata["dataset_sha256"])
        self.assertEqual(
            APPROVED_EMBEDDED_DATASET_SHA256,
            metadata["embedded_dataset_sha256"],
        )
        self.assertEqual(APPROVED_GEOMETRY_SHA256, metadata["geometry_sha256"])
        self.assertEqual(
            APPROVED_PRODUCTION_ASSET_VERSION,
            metadata["production_asset_version"],
        )
        self.assertEqual(
            APPROVED_TOPOLOGY_EDGE_COUNT,
            metadata["topology_edge_count"],
        )
        self.assertEqual(APPROVED_PROVINCE_COUNT, metadata["province_count"])
        self.assertEqual(APPROVED_IDS_SHA256, metadata["included_ids_sha256"])
        self.assertFalse(metadata["operational_maneuver_enabled"])
        self.assertIsNone(metadata["operational_graph"])
        self.assertEqual([], metadata["operational_objectives"])
        self.assertEqual({}, metadata["coalition_capitals"])
        self.assertEqual("p1_schema_compatibility_only", metadata["runtime_faction_state"])
        self.assertEqual({Faction.NATO.value}, set(state.factions))
        nato = state.factions[Faction.NATO.value]
        self.assertEqual(Faction.NATO, nato.faction)
        self.assertEqual(FactionState(faction=Faction.NATO).resources, nato.resources)
        self.assertTrue(nato.is_human_controlled)
        self.assertEqual([], nato.researched_keys)
        self.assertEqual([], nato.recruited_pool)
        self.assertEqual([], nato.reinforcement_pool)
        self.assertEqual(0, nato.income_last_round)
        self.assertEqual(0, nato.maintenance_last_round)
        self.assertFalse(nato.is_eliminated)
        self.assertFalse(state.fog_of_war_enabled)
        self.assertEqual({}, state.alliances)
        self.assertEqual({}, state.formations)
        self.assertEqual({}, state.strategic_formations)
        self.assertEqual({}, state.commanders)
        self.assertEqual({}, state.research_nodes)
        self.assertEqual({}, state.unit_economy)
        self.assertEqual({}, state.battalions)
        for value in _all_strings(metadata):
            self.assertFalse(Path(value).is_absolute(), value)


class Earth3FailureBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _copy_authority(self) -> Path:
        destination = self.root / "authority"
        asset_destination = destination / "godot/assets/maps/earth3_europe_mediterranean"
        asset_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(EARTH3_ASSETS, asset_destination)
        auth_destination = destination / "config/earth3/production_authority.json"
        auth_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PRODUCTION_AUTHORITY, auth_destination)
        return destination

    @staticmethod
    @contextmanager
    def _repin_manifest(manifest: Path):
        digest = _normalized_sha256(manifest)
        with (
            patch(
                "gates_of_codex.earth3_campaign.APPROVED_MANIFEST_SHA256",
                digest,
            ),
            patch(
                "gates_of_codex.earth3_campaign._APPROVED_EXACT_BYTE_IDENTITIES",
                {
                    (
                        digest,
                        APPROVED_DATASET_RAW_SHA256,
                        APPROVED_EMBEDDED_DATASET_SHA256,
                    ): (
                        APPROVED_DATASET_SHA256,
                        APPROVED_GEOMETRY_SHA256,
                        APPROVED_PRODUCTION_ASSET_VERSION,
                    )
                },
            ),
        ):
            yield

    @contextmanager
    def _mutated_structural_authority(self, root: Path, mutate):
        assets = root / "godot/assets/maps/earth3_europe_mediterranean"
        dataset_path = assets / "polygon_dataset.json"
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        mutate(dataset)
        dataset_path.write_bytes(
            (json.dumps(dataset, separators=(",", ":")) + "\n").encode("utf-8")
        )
        digest = _normalized_sha256(dataset_path, strip_one_trailing_newline=True)
        dataset_raw_digest = _normalized_sha256(dataset_path)

        metadata_path = assets / "dataset_meta.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["dataset_sha256"] = digest
        metadata_path.write_bytes((json.dumps(metadata, indent=2) + "\n").encode("utf-8"))

        production_path = root / "config/earth3/production_authority.json"
        production = json.loads(production_path.read_text(encoding="utf-8"))
        production["dataset_sha256"] = digest
        production_path.write_bytes((json.dumps(production, indent=2) + "\n").encode("utf-8"))

        manifest_path = assets / "map_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["polygon_dataset"]["sha256"] = digest
        manifest_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        manifest_digest = _normalized_sha256(manifest_path)

        with (
            patch(
                "gates_of_codex.earth3_campaign.APPROVED_EMBEDDED_DATASET_SHA256",
                digest,
            ),
            patch(
                "gates_of_codex.earth3_campaign.APPROVED_MANIFEST_SHA256",
                manifest_digest,
            ),
            patch(
                "gates_of_codex.earth3_campaign.APPROVED_DATASET_RAW_SHA256",
                dataset_raw_digest,
            ),
            patch(
                "gates_of_codex.earth3_campaign._APPROVED_EXACT_BYTE_IDENTITIES",
                {
                    (manifest_digest, dataset_raw_digest, digest): (
                        APPROVED_DATASET_SHA256,
                        APPROVED_GEOMETRY_SHA256,
                        APPROVED_PRODUCTION_ASSET_VERSION,
                    )
                },
            ),
        ):
            yield

    def test_missing_manifest_fails_closed(self) -> None:
        root = self._copy_authority()
        (root / "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json").unlink()
        with self.assertRaisesRegex(Earth3AuthorityError, "Earth3 manifest missing"):
            build_earth3_campaign(root)

    def test_missing_production_dataset_fails_closed(self) -> None:
        root = self._copy_authority()
        (root / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json").unlink()
        with self.assertRaisesRegex(Earth3AuthorityError, "Earth3 production dataset missing"):
            build_earth3_campaign(root)

    def test_modified_manifest_bytes_fail_closed(self) -> None:
        root = self._copy_authority()
        manifest = root / "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json"
        manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(Earth3AuthorityError, "manifest SHA-256 mismatch"):
            build_earth3_campaign(root)

    def test_modified_dataset_bytes_fail_closed(self) -> None:
        root = self._copy_authority()
        dataset = root / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
        text = dataset.read_text(encoding="utf-8")
        dataset.write_text(text[:-1] + " " + text[-1:], encoding="utf-8")
        with self.assertRaisesRegex(Earth3AuthorityError, "dataset bytes/SHA-256 mismatch"):
            build_earth3_campaign(root)

    def test_crlf_converted_dataset_bytes_fail_closed(self) -> None:
        root = self._copy_authority()
        dataset = root / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
        dataset.write_bytes(dataset.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(Earth3AuthorityError, "dataset bytes/SHA-256 mismatch"):
            build_earth3_campaign(root)

    def test_dataset_without_its_required_terminal_lf_fails_closed(self) -> None:
        root = self._copy_authority()
        dataset = root / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
        raw = dataset.read_bytes()
        self.assertEqual(b"\n", raw[-1:])
        dataset.write_bytes(raw[:-1])
        with self.assertRaisesRegex(Earth3AuthorityError, "dataset bytes/SHA-256 mismatch"):
            build_earth3_campaign(root)

    def test_dataset_trailing_byte_fails_closed(self) -> None:
        root = self._copy_authority()
        dataset = root / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
        dataset.write_bytes(dataset.read_bytes() + b" ")
        with self.assertRaisesRegex(Earth3AuthorityError, "dataset bytes/SHA-256 mismatch"):
            build_earth3_campaign(root)

    def test_symlinked_dataset_fails_closed(self) -> None:
        root = self._copy_authority()
        dataset = root / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
        dataset.unlink()
        try:
            dataset.symlink_to(DATASET)
        except OSError as exc:
            self.skipTest(f"platform refused dataset symlink creation: {exc}")
        with self.assertRaisesRegex(Earth3AuthorityError, "symlink"):
            build_earth3_campaign(root)

    def test_symlinked_intermediate_authority_directory_fails_closed(self) -> None:
        root = self._copy_authority()
        maps = root / "godot/assets/maps"
        substituted_maps = root / "godot/assets/maps-substituted"
        maps.rename(substituted_maps)
        try:
            maps.symlink_to(substituted_maps, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"platform refused authority-directory symlink creation: {exc}")
        with self.assertRaisesRegex(Earth3AuthorityError, "symlink"):
            build_earth3_campaign(root)

    def test_symlinked_authority_root_fails_closed(self) -> None:
        root = self._copy_authority()
        substituted_root = self.root / "authority-substitution"
        try:
            substituted_root.symlink_to(root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"platform refused authority-root symlink creation: {exc}")
        with self.assertRaisesRegex(Earth3AuthorityError, "authority root.*symlink"):
            build_earth3_campaign(substituted_root)

    def test_windows_short_path_alias_accepted_for_authority_root(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-only 8.3 alias regression")
        root = self._copy_authority()
        short_path = _windows_short_path(root)
        if short_path is None:
            self.skipTest("filesystem does not provide a distinct short-name alias")
        authority = build_earth3_campaign(Path(short_path))
        self.assertEqual(APPROVED_PROVINCE_COUNT, len(authority.provinces))

    def test_windows_temp_directory_resolve_spelling_is_not_symlink_evidence(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-only path-alias regression")
        temp_path = Path(self.temporary.name)
        canonical_root = _canonical_authority_root(temp_path)
        self.assertTrue(os.path.samefile(temp_path, canonical_root))
        root = self._copy_authority()
        build_earth3_campaign(root)

    def test_windows_junction_substitution_fails_closed(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-only junction regression")
        root = self._copy_authority()
        maps = root / "godot/assets/maps"
        substituted_maps = root / "godot/assets/maps-substituted"
        maps.rename(substituted_maps)
        try:
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(maps), str(substituted_maps)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(
                    "platform refused junction creation: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
        except OSError as exc:
            self.skipTest(f"platform refused junction creation: {exc}")
        with self.assertRaisesRegex(Earth3AuthorityError, "symlink"):
            build_earth3_campaign(root)

    def test_manifest_declared_hash_mismatch_fails_closed(self) -> None:
        root = self._copy_authority()
        manifest = root / "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["polygon_dataset"]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        with self._repin_manifest(manifest):
            with self.assertRaisesRegex(Earth3AuthorityError, "polygon_dataset.sha256"):
                build_earth3_campaign(root)

    def test_manifest_and_dataset_count_mismatch_fails_closed(self) -> None:
        root = self._copy_authority()
        manifest = root / "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["province_count"] = 3513
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        with self._repin_manifest(manifest):
            with self.assertRaisesRegex(Earth3AuthorityError, "province_count"):
                build_earth3_campaign(root)

    def test_only_designated_metadata_selectable_summary_is_ignored(self) -> None:
        root = self._copy_authority()
        metadata_path = root / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["selectable_province_count"] = 3294
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(Earth3AuthorityError, "stale selectable_province_count"):
            build_earth3_campaign(root)

    def test_only_designated_embedded_edge_summary_is_ignored(self) -> None:
        root = self._copy_authority()

        def revise_summary(dataset) -> None:
            dataset["edge_count"] = APPROVED_TOPOLOGY_EDGE_COUNT

        with (
            self._mutated_structural_authority(root, revise_summary),
            self.assertRaisesRegex(Earth3AuthorityError, "stale edge_count summary"),
        ):
            build_earth3_campaign(root)

    def test_duplicate_normalized_edge_fails_closed(self) -> None:
        root = self._copy_authority()

        def duplicate_edge(dataset) -> None:
            a, b = dataset["edges"][0]
            dataset["edges"].append([b, a])

        with (
            self._mutated_structural_authority(root, duplicate_edge),
            self.assertRaisesRegex(Earth3AuthorityError, "duplicated"),
        ):
            build_earth3_campaign(root)

    def test_missing_declared_edge_fails_closed(self) -> None:
        root = self._copy_authority()

        with (
            self._mutated_structural_authority(root, lambda dataset: dataset["edges"].pop()),
            self.assertRaisesRegex(Earth3AuthorityError, "does not match province adjacency"),
        ):
            build_earth3_campaign(root)

    def test_invalid_edge_endpoint_fails_closed(self) -> None:
        root = self._copy_authority()

        def invalidate_edge(dataset) -> None:
            dataset["edges"][0][1] = "e3_9999"

        with (
            self._mutated_structural_authority(root, invalidate_edge),
            self.assertRaisesRegex(Earth3AuthorityError, "committed edge row .* invalid"),
        ):
            build_earth3_campaign(root)

    def test_self_edge_fails_closed(self) -> None:
        root = self._copy_authority()

        def make_self_edge(dataset) -> None:
            dataset["edges"][0][1] = dataset["edges"][0][0]

        with (
            self._mutated_structural_authority(root, make_self_edge),
            self.assertRaisesRegex(Earth3AuthorityError, "committed edge row .* invalid"),
        ):
            build_earth3_campaign(root)

    def test_nonreciprocal_neighbor_row_fails_closed(self) -> None:
        root = self._copy_authority()

        def break_reciprocity(dataset) -> None:
            a, b = dataset["edges"][0]
            row = next(province for province in dataset["provinces"] if province["id"] == b)
            row["neighbors"].remove(a)

        with (
            self._mutated_structural_authority(root, break_reciprocity),
            self.assertRaisesRegex(Earth3AuthorityError, "adjacency is not reciprocal"),
        ):
            build_earth3_campaign(root)

    def test_earth3_failure_never_invokes_legacy_builder(self) -> None:
        root = self._copy_authority()
        (root / "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json").unlink()
        with (
            patch("gates_of_codex.europe.build_goe_europe_campaign") as legacy_goe,
            patch(
                "gates_of_codex.europe_mediterranean_from_goe."
                "build_europe_mediterranean_from_goe_campaign"
            ) as legacy_em,
            self.assertRaises(Earth3AuthorityError),
        ):
            build_scenario(EARTH3_SCENARIO_ID, authority_root=root)
        legacy_goe.assert_not_called()
        legacy_em.assert_not_called()

    def test_cli_failure_emits_no_partial_campaign_or_temporary_file(self) -> None:
        output = self.root / "new-campaign.json"
        with (
            patch("gates_of_codex.cli.build_scenario", side_effect=Earth3AuthorityError("missing")),
            self.assertRaises(Earth3AuthorityError),
        ):
            main(["new", str(output)])
        self.assertFalse(output.exists())
        self.assertEqual([], list(self.root.glob(f".{output.name}.*.tmp")))

    def test_cli_failure_does_not_overwrite_existing_valid_campaign(self) -> None:
        output = self.root / "existing-campaign.json"
        original = b'{"valid":"existing"}\n'
        output.write_bytes(original)
        with (
            patch("gates_of_codex.cli.build_scenario", side_effect=Earth3AuthorityError("mismatch")),
            self.assertRaises(Earth3AuthorityError),
        ):
            main(["new", str(output)])
        self.assertEqual(original, output.read_bytes())


class Earth3DefaultCreationAndFrontendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _copy_authority(self) -> Path:
        destination = self.root / "authority"
        asset_destination = destination / "godot/assets/maps/earth3_europe_mediterranean"
        asset_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(EARTH3_ASSETS, asset_destination)
        auth_destination = destination / "config/earth3/production_authority.json"
        auth_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PRODUCTION_AUTHORITY, auth_destination)
        return destination

    def test_new_parser_defaults_to_earth3_and_accepts_positional_output(self) -> None:
        output = self.root / "campaign.json"
        args = build_parser().parse_args(["new", str(output)])
        self.assertEqual(DEFAULT_SCENARIO_ID, args.scenario)
        self.assertEqual("ww3_2028_core", args.scenario)
        self.assertEqual(str(output), args.campaign)

    def test_default_new_creates_earth3_without_reading_stale_snapshot(self) -> None:
        output = self.root / "campaign.json"
        stale = self.root / "godot/campaign_snapshot.json"
        stale.parent.mkdir(parents=True)
        stale.write_text('{"campaign":{"map_id":"goe_europe"}}\n', encoding="utf-8")
        original_read_text = Path.read_text

        def guarded_read_text(path: Path, *args, **kwargs):
            if path.resolve() == stale.resolve():
                raise AssertionError("default creation read stale campaign_snapshot.json")
            return original_read_text(path, *args, **kwargs)

        previous = Path.cwd()
        os.chdir(self.root)
        try:
            with (
                patch.object(Path, "read_text", guarded_read_text),
                patch("gates_of_codex.europe.build_goe_europe_campaign") as legacy_goe,
                patch(
                    "gates_of_codex.cli.build_scenario",
                    return_value=build_earth3_campaign(),
                ),
            ):
                self.assertEqual(0, main(["new", str(output)]))
        finally:
            os.chdir(previous)
        legacy_goe.assert_not_called()
        state = load_campaign(output)
        self.assertEqual(EARTH3_SCENARIO_ID, state.map_metadata["scenario_id"])
        self.assertEqual(EARTH3_MAP_ID, state.map_id)
        self.assertEqual({Faction.NATO.value}, set(state.factions))
        self.assertEqual(Faction.NATO, state.factions[Faction.NATO.value].faction)
        self.assertTrue(state.factions[Faction.NATO.value].is_human_controlled)

    def test_default_frontend_snapshot_identifies_only_earth3_production_map(self) -> None:
        state = build_earth3_campaign()
        with patch("gates_of_codex.frontend.apply_marker_layout") as legacy_layout:
            snapshot = build_frontend_snapshot(
                state,
                campaign_path=self.root / "campaign.json",
                snapshot_path=ROOT / "godot/campaign_snapshot.json",
            )
        legacy_layout.assert_not_called()
        strategic_map = snapshot["strategic_map"]
        self.assertEqual(Faction.NATO.value, snapshot["campaign"]["selected_faction"])
        self.assertEqual(Faction.NATO.value, snapshot["campaign"]["current_faction"])
        self.assertEqual(EARTH3_MAP_ID, snapshot["campaign"]["map_id"])
        self.assertEqual(EARTH3_MAP_ID, strategic_map["map_id"])
        self.assertEqual([EARTH3_MAP_ID], strategic_map["available_map_ids"])
        self.assertEqual([EARTH3_MAP_ID], strategic_map["production_map_ids"])
        self.assertEqual("none", strategic_map["fallback"])
        self.assertNotIn("goe", json.dumps({
            "available": strategic_map["available_map_ids"],
            "fallback": strategic_map["fallback"],
            "active": strategic_map["map_id"],
        }).lower())

    def test_missing_earth3_frontend_assets_fail_clearly(self) -> None:
        state = build_earth3_campaign()
        empty_authority = self.root / "empty-authority"
        empty_authority.mkdir()
        with (
            patch(
                "gates_of_codex.earth3_campaign._default_authority_root",
                return_value=empty_authority,
            ),
            self.assertRaisesRegex(FileNotFoundError, "Earth3 map manifest missing"),
        ):
            build_frontend_snapshot(state, snapshot_path=self.root / "snapshot.json")

    def test_earth3_frontend_rejects_noncanonical_persisted_manifest_paths(self) -> None:
        for configured in (
            str(MANIFEST.resolve()),
            "../assets/maps/earth3_europe_mediterranean/map_manifest.json",
        ):
            with self.subTest(configured=configured):
                state = build_earth3_campaign()
                state.map_metadata["strategic_map_manifest"] = configured
                with self.assertRaisesRegex(
                    Earth3AuthorityError,
                    "strategic_map_manifest",
                ):
                    build_frontend_snapshot(
                        state,
                        snapshot_path=self.root / "snapshot.json",
                    )

    def test_earth3_frontend_rejects_plausible_external_manifest_copy(self) -> None:
        state = build_earth3_campaign()
        external = self.root / "external/map_manifest.json"
        external.parent.mkdir(parents=True)
        shutil.copy2(MANIFEST, external)
        state.map_metadata["strategic_map_manifest"] = str(external.resolve())
        with self.assertRaisesRegex(Earth3AuthorityError, "strategic_map_manifest"):
            build_frontend_snapshot(state, snapshot_path=self.root / "snapshot.json")

    def test_earth3_frontend_rejects_persisted_authority_identity_changes(self) -> None:
        replacements = {
            "manifest_sha256": "0" * 64,
            "dataset_sha256": "1" * 64,
            "embedded_dataset_sha256": "2" * 64,
            "geometry_sha256": "3" * 64,
            "production_asset_version": "substituted",
            "included_ids_sha256": "4" * 64,
            "topology_edge_count": APPROVED_TOPOLOGY_EDGE_COUNT - 1,
            "manifest_identifier": "assets/maps/substituted/map_manifest.json",
            "dataset_identifier": "assets/maps/substituted/polygon_dataset.json",
            "production_authority_identifier": "config/substituted/authority.json",
        }
        for field, replacement in replacements.items():
            with self.subTest(field=field):
                state = build_earth3_campaign()
                state.map_metadata[field] = replacement
                with self.assertRaisesRegex(Earth3AuthorityError, field):
                    build_frontend_snapshot(
                        state,
                        snapshot_path=self.root / "snapshot.json",
                    )

    def test_earth3_frontend_requires_both_map_identities(self) -> None:
        for field in ("state.map_id", "strategic_map_id"):
            with self.subTest(field=field):
                state = build_earth3_campaign()
                if field == "state.map_id":
                    state.map_id = LEGACY_GOE_MAP_ID
                else:
                    state.map_metadata["strategic_map_id"] = LEGACY_GOE_MAP_ID
                with (
                    patch("gates_of_codex.frontend.apply_marker_layout") as legacy_layout,
                    self.assertRaisesRegex(Earth3AuthorityError, "map_id"),
                ):
                    build_frontend_snapshot(
                        state,
                        snapshot_path=self.root / "snapshot.json",
                    )
                legacy_layout.assert_not_called()

    def test_earth3_frontend_propagates_fixed_loader_symlink_rejection(self) -> None:
        state = build_earth3_campaign()
        authority_root = self._copy_authority()
        dataset = (
            authority_root
            / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
        )
        dataset.unlink()
        try:
            dataset.symlink_to(DATASET)
        except OSError as exc:
            self.skipTest(f"platform refused dataset symlink creation: {exc}")
        with (
            patch(
                "gates_of_codex.earth3_campaign._default_authority_root",
                return_value=authority_root,
            ),
            self.assertRaisesRegex(Earth3AuthorityError, "symlink"),
        ):
            build_frontend_snapshot(state, snapshot_path=self.root / "snapshot.json")

    def test_earth3_frontend_accepts_only_canonical_persisted_identifiers(self) -> None:
        state = build_earth3_campaign()
        self.assertEqual(
            CAMPAIGN_MANIFEST_IDENTIFIER,
            state.map_metadata["strategic_map_manifest"],
        )
        self.assertEqual(
            CAMPAIGN_MANIFEST_IDENTIFIER,
            state.map_metadata["manifest_identifier"],
        )
        self.assertEqual(
            CAMPAIGN_DATASET_IDENTIFIER,
            state.map_metadata["dataset_identifier"],
        )
        self.assertEqual(
            PRODUCTION_AUTHORITY_IDENTIFIER,
            state.map_metadata["production_authority_identifier"],
        )
        snapshot = build_frontend_snapshot(
            state,
            snapshot_path=ROOT / "godot/campaign_snapshot.json",
        )
        self.assertEqual(EARTH3_MAP_ID, snapshot["strategic_map"]["map_id"])
        self.assertTrue(snapshot["strategic_map"]["enabled"])

    def test_legacy_save_round_trip_and_frontend_export_preserve_map_identity(self) -> None:
        for scenario_id, expected_map_id in (
            ("legacy_goe_europe", LEGACY_GOE_MAP_ID),
            ("legacy_goe_europe_mediterranean", "europe_mediterranean_from_goe"),
        ):
            with self.subTest(scenario_id=scenario_id):
                state = build_scenario(scenario_id)
                campaign = self.root / f"{scenario_id}.json"
                save_campaign(state, campaign)
                loaded = load_campaign(campaign)
                self.assertEqual(expected_map_id, loaded.map_id)
                self.assertNotEqual(EARTH3_MAP_ID, loaded.map_id)
                snapshot = build_frontend_snapshot(
                    loaded,
                    campaign_path=campaign,
                    snapshot_path=ROOT / "godot" / f"{scenario_id}.json",
                )
                self.assertEqual(expected_map_id, snapshot["campaign"]["map_id"])
                self.assertEqual(expected_map_id, snapshot["strategic_map"]["map_id"])
                self.assertEqual(
                    "marker_non_authoritative",
                    snapshot["strategic_map"]["fallback"],
                )

    def test_existing_legacy_save_fixture_loads_without_earth3_migration(self) -> None:
        legacy = load_legacy_test_scenario()
        original_map_id = legacy.map_id
        campaign = self.root / "legacy-fixture.json"
        save_campaign(legacy, campaign)
        loaded = load_campaign(campaign)
        self.assertEqual(original_map_id, loaded.map_id)
        self.assertNotEqual(EARTH3_MAP_ID, loaded.map_id)


if __name__ == "__main__":
    unittest.main()
