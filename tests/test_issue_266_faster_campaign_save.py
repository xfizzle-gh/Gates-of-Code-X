from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import command_cycle_perf, command_scoped_p2_auth, p2_integrity
from gates_of_codex.command_cycle_perf import (
    _should_persist_runtime_snapshot,
    _compact_save_campaign,
)
from gates_of_codex.earth3_bootstrap import Earth3BootstrapError
from gates_of_codex.earth3_campaign import (
    APPROVED_DATASET_SHA256,
    APPROVED_PROVINCE_COUNT,
    Earth3AuthorityError,
)
from gates_of_codex.frontend_runtime_patch import (
    RUNTIME_PATCH_SCHEMA,
    RUNTIME_PATCH_SCHEMA_VERSION,
)
from gates_of_codex.persistent_backend import _fingerprint
from gates_of_codex.scenario import build_scenario
from gates_of_codex.state_io import load_campaign
from tests.test_issue_266_runtime_patch_live_batch import _move_batch
from tests.test_p2_earth3_campaign_bootstrap import _resolved_catalog


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FasterCampaignSaveContractTests(unittest.TestCase):
    def test_slice2_persist_gate_remains_exact(self) -> None:
        self.assertTrue(_should_persist_runtime_snapshot(_move_batch()))
        self.assertTrue(_should_persist_runtime_snapshot([{"op": "auto_resolve"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "end_player_round"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "refresh"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "issue_move_order"}]))

    def test_runtime_patch_schema_remains_v1(self) -> None:
        self.assertEqual("gates-of-codex.frontend-runtime-patch", RUNTIME_PATCH_SCHEMA)
        self.assertEqual(1, RUNTIME_PATCH_SCHEMA_VERSION)

    def test_compact_save_still_validates_and_writes_atomically(self) -> None:
        source = (ROOT / "src/gates_of_codex/command_cycle_perf.py").read_text(
            encoding="utf-8"
        )
        compact = source.split("def _compact_save_campaign(", 1)[1].split(
            "def _bulk_formation_presentation_rows(", 1
        )[0]
        self.assertIn("_profiled_campaign_validation(state, subphase_seconds)", compact)
        self.assertIn("_runtime_state_json(state)", compact)
        self.assertIn("temporary_path.replace(destination)", compact)
        self.assertNotIn("indent=2", compact)
        profiler = source.split("def _profiled_campaign_validation(", 1)[1].split(
            "def _ensure_runtime_operational_positions(", 1
        )[0]
        self.assertIn("state.validate()", profiler)

    def test_p1_integrity_still_rehashes_fixed_files(self) -> None:
        source = (ROOT / "src/gates_of_codex/p2_integrity.py").read_text(encoding="utf-8")
        self.assertIn("load_p1_integrity_projection", source)
        self.assertIn("_capture_p1_identity", source)
        self.assertIn("load_earth3_authority", source)


class FasterCampaignSaveEarth3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        command_cycle_perf.install_command_cycle_perf_path()
        command_scoped_p2_auth.install_command_scoped_p2_auth()
        cls.state = build_scenario("earth3_v1", resolved_catalog=_resolved_catalog())

    def setUp(self) -> None:
        p2_integrity._clear_p1_integrity_projection_cache_for_tests()

    def _fresh_state(self):
        return copy.deepcopy(self.state)

    def test_compact_save_load_round_trip_preserves_authority(self) -> None:
        state = self._fresh_state()
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "campaign.json"
            second = Path(temporary) / "roundtrip.json"
            subphase: dict[str, float] = {}
            _compact_save_campaign(state, first, subphase_seconds=subphase)
            loaded = load_campaign(first)
            self.assertEqual(state.schema_version, loaded.schema_version)
            self.assertEqual(APPROVED_PROVINCE_COUNT, len(loaded.provinces))
            self.assertEqual(set(state.strategic_formations), set(loaded.strategic_formations))
            self.assertEqual(APPROVED_DATASET_SHA256, loaded.map_metadata["dataset_sha256"])
            for formation_id, force in state.strategic_formations.items():
                restored = loaded.strategic_formations[formation_id]
                self.assertEqual(force.province_id, restored.province_id)
                self.assertEqual(force.position, restored.position)
                self.assertEqual(force.actor_id, restored.actor_id)
            loaded.validate()
            _compact_save_campaign(loaded, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(_sha256(first), _fingerprint(first)[2])
            self.assertGreater(first.stat().st_size, 1_000_000)
            self.assertNotIn(b"\n  ", first.read_bytes()[:200])

    def test_fingerprint_lease_bytes_change_only_when_authority_changes(self) -> None:
        state = self._fresh_state()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            _compact_save_campaign(state, path)
            before = _fingerprint(path)
            _compact_save_campaign(state, path)
            self.assertEqual(before, _fingerprint(path))
            state.turn_number += 1
            _compact_save_campaign(state, path)
            after = _fingerprint(path)
            self.assertNotEqual(before[2], after[2])
            reloaded = load_campaign(path)
            self.assertEqual(state.turn_number, reloaded.turn_number)
            reloaded.validate()

    def test_compact_json_matches_canonical_to_dict_contract(self) -> None:
        state = self._fresh_state()
        expected = json.dumps(
            state.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        actual = command_cycle_perf._runtime_state_json(state)
        self.assertEqual(expected, actual)

    def test_warm_save_skips_dataset_clone_and_stays_faster(self) -> None:
        state = self._fresh_state()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            cold: dict[str, float] = {}
            _compact_save_campaign(state, path, subphase_seconds=cold)
            warm_samples: list[dict[str, float]] = []
            for _ in range(3):
                sample: dict[str, float] = {}
                _compact_save_campaign(state, path, subphase_seconds=sample)
                warm_samples.append(sample)
            warm = min(warm_samples, key=lambda row: row.get("validate", 9e9))
            self.assertGreater(cold["validate_base"], warm["validate_base"])
            self.assertLess(warm["validate_base"], cold["validate_base"] * 0.6)
            self.assertLess(warm["validate"], cold["validate"] * 0.6)
            self.assertLess(warm["encode"], 0.08)
            total_warm = (
                warm["validate"]
                + warm["encode"]
                + warm["write"]
                + warm.get("supply", 0.0)
                + warm.get("strategic", 0.0)
                + warm.get("orders", 0.0)
                + warm.get("site_control", 0.0)
            )
            total_cold = (
                cold["validate"]
                + cold["encode"]
                + cold["write"]
                + cold.get("supply", 0.0)
                + cold.get("strategic", 0.0)
                + cold.get("orders", 0.0)
                + cold.get("site_control", 0.0)
            )
            self.assertLess(total_warm, total_cold * 0.7)
            self.assertLess(total_warm, 0.75)
            with patch.object(
                p2_integrity,
                "_p1_projection_from_authority",
                side_effect=AssertionError("warm save must reuse the slim P1 projection"),
            ):
                again: dict[str, float] = {}
                _compact_save_campaign(state, path, subphase_seconds=again)
                self.assertLess(again["validate_base"], cold["validate_base"] * 0.6)

    def test_changed_p1_bytes_still_fail_closed(self) -> None:
        state = self._fresh_state()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            _compact_save_campaign(state, path)
        with patch(
            "gates_of_codex.command_scoped_p2_auth._capture_p1_identity",
            side_effect=Earth3AuthorityError(
                "Earth3 production dataset bytes/SHA-256 mismatch"
            ),
        ):
            with self.assertRaisesRegex(
                Earth3AuthorityError, "dataset bytes/SHA-256 mismatch"
            ):
                state.validate()

    def test_in_memory_topology_tamper_is_still_rejected(self) -> None:
        state = self._fresh_state()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            _compact_save_campaign(state, path)
            loaded = load_campaign(path)
        victim = next(iter(loaded.provinces.values()))
        if not victim.neighbors:
            self.skipTest("fixture province unexpectedly has no neighbors")
        victim.neighbors = list(victim.neighbors) + ["e3_missing"]
        with self.assertRaisesRegex(
            Earth3BootstrapError, "persisted province topology mismatch"
        ):
            loaded.validate()

    def test_persisted_hash_tamper_is_still_rejected(self) -> None:
        state = self._fresh_state()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            _compact_save_campaign(state, path)
            loaded = load_campaign(path)
        loaded.map_metadata["dataset_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            Earth3BootstrapError, "persisted P1 authority mismatch: dataset_sha256"
        ):
            loaded.validate()

    def test_geometry_smuggle_is_still_rejected(self) -> None:
        state = self._fresh_state()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            _compact_save_campaign(state, path)
            loaded = load_campaign(path)
        loaded.map_metadata["vertices"] = [[0, 0]]
        with self.assertRaisesRegex(
            Earth3BootstrapError, "contains geometry authority"
        ):
            loaded.validate()


if __name__ == "__main__":
    unittest.main()
