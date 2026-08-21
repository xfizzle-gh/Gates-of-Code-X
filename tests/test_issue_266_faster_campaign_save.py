from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType
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
    EARTH3_DATASET_PATH,
    EARTH3_MANIFEST_PATH,
    EARTH3_METADATA_PATH,
    EARTH3_PRODUCTION_AUTHORITY_PATH,
    Earth3AuthorityError,
    _default_authority_root,
)
from gates_of_codex.frontend_runtime_patch import (
    RUNTIME_PATCH_SCHEMA,
    RUNTIME_PATCH_SCHEMA_VERSION,
)
from gates_of_codex.persistent_backend import _fingerprint
from gates_of_codex.scenario import build_scenario
from gates_of_codex.state_io import load_campaign
from gates_of_codex.turn_cycle import install_frontend_turn_cycle_op
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
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "query_supply"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "issue_move_order"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "upgrade_site"}]))

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
        self.assertIn("MappingProxyType", source)
        self.assertIn("_detach_p1_projection", source)
        self.assertIn("_clone_p1_row", source)

    def test_owner_ab_harness_refuses_missing_campaign(self) -> None:
        harness = ROOT / "tools/ab_issue_266_campaign_save.py"
        self.assertTrue(harness.is_file())
        completed = subprocess.run(
            [sys.executable, str(harness)],
            check=False,
            capture_output=True,
            text=True,
            env={key: value for key, value in os.environ.items() if key != "GOC_OWNER_CAMPAIGN"},
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("owner campaign missing", completed.stderr)
        self.assertIn("does not invent owner timings", completed.stderr)

    def test_owner_ab_harness_exposes_production_command_paths(self) -> None:
        import importlib.util

        from gates_of_codex.state_io import save_campaign
        from tests.test_s10_frontend_presentation_contract import (
            _create_prepared_contact,
            _state,
        )

        harness = ROOT / "tools/ab_issue_266_campaign_save.py"
        source = harness.read_text(encoding="utf-8")
        self.assertIn("measured_apply_frontend_commands", source)
        self.assertIn("PRODUCTION_COMMAND_PATHS", source)
        self.assertIn("issue_commit", source)
        self.assertIn("end_player_round", source)
        self.assertIn("auto_resolve", source)
        self.assertIn("_LIVE_MOVE_BATCH", source)
        self.assertIn("_direct_cache_loader", source)
        self.assertIn("persistent_backend", source)
        spec = importlib.util.spec_from_file_location(
            "ab_issue_266_campaign_save", harness
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            ("issue_commit", "end_player_round", "auto_resolve"),
            module.PRODUCTION_COMMAND_PATHS,
        )
        self.assertIn("load_ms", module.COMMAND_METRIC_KEYS)
        self.assertEqual(
            ("total_ms", "load_ms", *module.METRIC_KEYS),
            module.COMMAND_METRIC_KEYS,
        )
        self.assertEqual(
            ("issue_move_order", "commit_move_orders"),
            command_cycle_perf._LIVE_MOVE_BATCH,
        )

        install_frontend_turn_cycle_op()
        applied: list[list[str]] = []
        real_apply = command_cycle_perf.measured_apply_frontend_commands

        def recording_apply(campaign_path, *, commands=None, **kwargs):
            applied.append([str(item.get("op", "")) for item in (commands or [])])
            return real_apply(campaign_path, commands=commands, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            save_campaign(_state(root), campaign)
            with patch(
                "gates_of_codex.command_cycle_perf.measured_apply_frontend_commands",
                side_effect=recording_apply,
            ):
                payload = module._sample_production_commands(campaign, repeats=1)

        self.assertFalse(payload["issue_commit"].get("skipped"))
        self.assertEqual(
            ["issue_move_order", "commit_move_orders"],
            payload["issue_commit"]["ops"],
        )
        self.assertTrue(payload["issue_commit"]["persist_runtime_snapshot"])
        self.assertEqual(1, payload["issue_commit"]["repeats"])
        self.assertIn("total_ms", payload["issue_commit"]["min"])
        self.assertIn("load_ms", payload["issue_commit"]["min"])
        self.assertLessEqual(
            payload["issue_commit"]["min"]["load_ms"], module.WARM_LOAD_MS_LIMIT
        )
        self.assertEqual(
            "persistent_backend._direct_cache_loader",
            payload["issue_commit"]["cache_seam"],
        )
        self.assertEqual(["end_player_round"], payload["end_player_round"]["ops"])
        self.assertFalse(payload["end_player_round"]["persist_runtime_snapshot"])
        self.assertLessEqual(
            payload["end_player_round"]["min"]["load_ms"], module.WARM_LOAD_MS_LIMIT
        )
        self.assertTrue(payload["auto_resolve"]["skipped"])
        self.assertEqual("no prepared contact", payload["auto_resolve"]["reason"])
        self.assertNotIn("min", payload["auto_resolve"])
        self.assertIn(["issue_move_order", "commit_move_orders"], applied)
        self.assertIn(["end_player_round"], applied)
        self.assertNotIn(["auto_resolve"], applied)
        # Warmup apply + one measured repeat for each executed path.
        self.assertEqual(2, applied.count(["issue_move_order", "commit_move_orders"]))
        self.assertEqual(2, applied.count(["end_player_round"]))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            _create_prepared_contact(state)
            campaign = root / "campaign.json"
            save_campaign(state, campaign)
            applied.clear()
            with patch(
                "gates_of_codex.command_cycle_perf.measured_apply_frontend_commands",
                side_effect=recording_apply,
            ):
                contacted = module._sample_production_commands(campaign, repeats=1)
        self.assertTrue(contacted["issue_commit"]["skipped"])
        self.assertTrue(contacted["end_player_round"]["skipped"])
        self.assertEqual("pending battle", contacted["end_player_round"]["reason"])
        self.assertFalse(contacted["auto_resolve"].get("skipped"))
        self.assertEqual(["auto_resolve"], contacted["auto_resolve"]["ops"])
        self.assertTrue(contacted["auto_resolve"]["persist_runtime_snapshot"])
        self.assertIn(["auto_resolve"], applied)
        self.assertNotIn(["issue_move_order", "commit_move_orders"], applied)
        self.assertNotIn(["end_player_round"], applied)

    def test_owner_ab_harness_provenance_uses_src_root_not_checkout(self) -> None:
        harness = ROOT / "tools/ab_issue_266_campaign_save.py"
        with tempfile.TemporaryDirectory() as temporary:
            fake_src = Path(temporary) / "src"
            package = fake_src / "gates_of_codex"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(
                "PROVENANCE = 'fake-base'\n", encoding="utf-8"
            )
            (package / "p2_integrity.py").write_text("", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(harness),
                    "--provenance-only",
                    "--src-root",
                    str(fake_src),
                    "--sha",
                    "deadbeef",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("deadbeef", payload["sha"])
        self.assertFalse(payload["has_p1_projection"])
        self.assertEqual(str(fake_src.resolve()), payload["imported_src_root"])
        checkout_src = str((ROOT / "src").resolve())
        self.assertNotEqual(checkout_src, payload["imported_src_root"])
        self.assertTrue(
            payload["imported_module"].startswith(str(fake_src.resolve()))
        )
        for key in (
            "save_ms",
            "save_validate_ms",
            "total_ms",
            "load_ms",
            "min",
            "median",
            "samples",
            "commands",
        ):
            self.assertNotIn(key, payload)

    def test_owner_ab_harness_worktree_imports_exact_sha_src(self) -> None:
        import importlib.util

        harness = ROOT / "tools/ab_issue_266_campaign_save.py"
        source = harness.read_text(encoding="utf-8")
        self.assertIn("def _ensure_commit(", source)
        self.assertIn('fetch", "--depth=1", "origin"', source)
        spec = importlib.util.spec_from_file_location("ab_issue_266_campaign_save", harness)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        base_sha = module.BASE_SHA
        head_sha = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        base_report = module._provenance_at_sha(repo=ROOT, sha=base_sha)
        head_report = module._provenance_at_sha(repo=ROOT, sha=head_sha)
        checkout_src = str((ROOT / "src").resolve())
        self.assertEqual(base_sha, base_report["sha"])
        self.assertEqual(head_sha, head_report["sha"])
        self.assertFalse(base_report["has_p1_projection"])
        self.assertTrue(head_report["has_p1_projection"])
        self.assertNotEqual(checkout_src, base_report["imported_src_root"])
        self.assertNotEqual(checkout_src, head_report["imported_src_root"])
        self.assertNotEqual(
            base_report["imported_src_root"], head_report["imported_src_root"]
        )
        self.assertNotEqual(base_report["imported_module"], head_report["imported_module"])
        self.assertIn("goc-266-ab-", base_report["imported_src_root"])
        self.assertIn("goc-266-ab-", head_report["imported_src_root"])

    def test_owner_ab_harness_warm_apply_uses_direct_cache_loader(self) -> None:
        """Measured command path leases persistent_backend._direct_cache_loader."""

        import importlib.util

        from gates_of_codex import frontend_commands as commands_module
        from gates_of_codex.persistent_backend import _direct_cache_loader
        from gates_of_codex.state_io import save_campaign
        from tests.test_s10_frontend_presentation_contract import _state

        harness = ROOT / "tools/ab_issue_266_campaign_save.py"
        spec = importlib.util.spec_from_file_location(
            "ab_issue_266_campaign_save_cache_seam", harness
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual("persistent_backend._direct_cache_loader", module.CACHE_SEAM)
        self.assertIn("_direct_cache_loader", harness.read_text(encoding="utf-8"))

        install_frontend_turn_cycle_op()
        leases: list[object] = []
        real_factory = _direct_cache_loader

        def recording_factory(cached_state, original_loader):
            leases.append(cached_state)
            return real_factory(cached_state, original_loader)

        def boom_loader(path):
            raise AssertionError(
                f"warm measured apply must not cold-load {path}"
            )

        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / "campaign.json"
            save_campaign(_state(Path(temporary)), campaign)
            source_bytes = campaign.read_bytes()
            original = commands_module.load_campaign
            try:
                commands_module.load_campaign = boom_loader
                with patch(
                    "gates_of_codex.persistent_backend._direct_cache_loader",
                    side_effect=recording_factory,
                ):
                    payload = module._measure_warm_apply(
                        campaign,
                        module._end_player_round_commands(),
                        repeats=2,
                    )
            finally:
                commands_module.load_campaign = original
            self.assertEqual(source_bytes, campaign.read_bytes())

        self.assertFalse(payload.get("skipped"))
        self.assertEqual(["end_player_round"], payload["ops"])
        self.assertEqual(module.CACHE_SEAM, payload["cache_seam"])
        # One unmeasured warmup lease plus one lease per measured repeat.
        self.assertEqual(3, len(leases))
        self.assertEqual(2, payload["repeats"])
        self.assertIn("load_ms", payload["min"])
        self.assertLessEqual(payload["min"]["load_ms"], module.WARM_LOAD_MS_LIMIT)
        for sample in payload["samples"]:
            self.assertLessEqual(sample["load_ms"], module.WARM_LOAD_MS_LIMIT)
            self.assertIn("total_ms", sample)


class FasterCampaignSaveEarth3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        command_cycle_perf.install_command_cycle_perf_path()
        command_scoped_p2_auth.install_command_scoped_p2_auth()
        install_frontend_turn_cycle_op()
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
            again = _fingerprint(path)
            self.assertEqual(before[0], again[0])
            self.assertEqual(before[2], again[2])
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
            campaign = Path(temporary) / "campaign.json"
            snapshot = Path(temporary) / "snapshot.json"
            snapshot.write_text("{}", encoding="utf-8")
            cold: dict[str, float] = {}
            _compact_save_campaign(state, campaign, subphase_seconds=cold)
            warm_samples: list[dict[str, float]] = []
            for _ in range(3):
                sample: dict[str, float] = {}
                _compact_save_campaign(state, campaign, subphase_seconds=sample)
                warm_samples.append(sample)
            warm = min(warm_samples, key=lambda row: row.get("validate_base", 9e9))
            encode_samples = [row["encode"] for row in warm_samples]
            encode_diagnostics = (
                "encode timings are diagnostic evidence only; shared runners "
                "cannot honor an absolute 80ms encode cap "
                f"(#275 observed ~0.19-0.25s): cold_encode={cold['encode']:.6f}s "
                f"warm_encode={warm['encode']:.6f}s warm_encodes={encode_samples}"
            )
            self.assertGreater(cold["encode"], 0.0, encode_diagnostics)
            self.assertGreater(warm["encode"], 0.0, encode_diagnostics)
            self.assertGreater(
                cold["validate_base"], warm["validate_base"], encode_diagnostics
            )
            self.assertLess(
                warm["validate_base"],
                cold["validate_base"] * 0.6,
                encode_diagnostics,
            )
            with patch.object(
                p2_integrity,
                "_p1_projection_from_authority",
                side_effect=AssertionError("warm save must reuse the slim P1 projection"),
            ):
                again: dict[str, float] = {}
                _compact_save_campaign(state, campaign, subphase_seconds=again)
                self.assertLess(
                    again["validate_base"],
                    cold["validate_base"] * 0.6,
                    encode_diagnostics,
                )

            report = command_cycle_perf.measured_apply_frontend_commands(
                campaign,
                commands=[{"op": "end_player_round"}],
                snapshot_path=snapshot,
            )
            self.assertTrue(report.get("ok"), report)
            save_ms = float(report["timings"]["save_ms"])
            save_base_ms = float(report["timings"]["save_validate_base_ms"])
            # Top-level compact-save phases only. Nested validate_* keys are
            # already counted inside "validate" and must not be double-summed.
            cold_save_ms = 1000.0 * sum(
                float(cold[name])
                for name in (
                    "strategic",
                    "positions",
                    "orders",
                    "site_control",
                    "supply",
                    "s11_schema",
                    "observer_refresh",
                    "validate",
                    "encode",
                    "write",
                )
            )
            apply_diagnostics = (
                f"{encode_diagnostics}; apply_save_ms={save_ms:.3f} "
                f"apply_save_base_ms={save_base_ms:.3f} "
                f"cold_save_ms={cold_save_ms:.3f}"
            )
            # Load already warmed the slim projection, matching a warm daemon
            # after the first authenticated validate in the process. The leftover
            # on main was ~570 ms of P1 dataset cloning inside save_validate_base.
            self.assertLess(
                save_base_ms,
                cold["validate_base"] * 1000.0 * 0.6,
                apply_diagnostics,
            )
            self.assertLess(save_ms, cold_save_ms, apply_diagnostics)

    def test_cached_projection_cannot_poison_later_validate(self) -> None:
        state = self._fresh_state()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            _compact_save_campaign(state, path)
        first = p2_integrity.load_p1_integrity_projection()
        cached = p2_integrity.load_p1_integrity_projection()
        self.assertIsInstance(cached.rows, MappingProxyType)
        self.assertIsNot(first, cached)
        self.assertIsNot(first.rows, cached.rows)
        victim_id = next(iter(cached.rows))
        self.assertIsNot(first.rows[victim_id], cached.rows[victim_id])
        self.assertEqual(1, len(p2_integrity._P1_PROJECTION_CACHE))
        internal_row = next(iter(p2_integrity._P1_PROJECTION_CACHE.values())).rows[
            victim_id
        ]
        self.assertNotEqual(id(cached.rows[victim_id]), id(internal_row))
        poison = p2_integrity._P1ProvinceRow(
            is_water=True,
            neighbors=("e3_smuggle",),
            label=(0.0, 0.0),
            centroid=(0.0, 0.0),
            source_id=0,
            terrain_id=0,
            continent_id=0,
        )
        with self.assertRaises(TypeError):
            cached.rows[victim_id] = poison  # type: ignore[index]
        with self.assertRaises(TypeError):
            del cached.rows[victim_id]  # type: ignore[attr-defined]
        with self.assertRaises(FrozenInstanceError):
            cached.rows = {}  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            cached.rows[victim_id].neighbors = ("e3_smuggle",)  # type: ignore[misc]
        canonical_neighbors = tuple(cached.rows[victim_id].neighbors)
        self.assertNotEqual(("e3_smuggle",), canonical_neighbors)
        object.__setattr__(cached.rows[victim_id], "neighbors", ("e3_smuggle",))
        self.assertEqual(("e3_smuggle",), cached.rows[victim_id].neighbors)
        self.assertEqual(canonical_neighbors, tuple(internal_row.neighbors))
        after_row_poison = p2_integrity.load_p1_integrity_projection()
        self.assertIsNot(cached.rows[victim_id], after_row_poison.rows[victim_id])
        self.assertNotEqual(id(after_row_poison.rows[victim_id]), id(internal_row))
        self.assertEqual(canonical_neighbors, after_row_poison.rows[victim_id].neighbors)
        object.__setattr__(cached, "rows", MappingProxyType({}))
        self.assertEqual(0, len(cached.rows))
        later = p2_integrity.load_p1_integrity_projection()
        self.assertEqual(APPROVED_PROVINCE_COUNT, len(later.rows))
        self.assertIn(victim_id, later.rows)
        self.assertEqual(canonical_neighbors, later.rows[victim_id].neighbors)
        self.assertNotEqual(("e3_smuggle",), later.rows[victim_id].neighbors)
        state.validate()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            again: dict[str, float] = {}
            _compact_save_campaign(state, path, subphase_seconds=again)
            self.assertGreater(again["validate_base"], 0.0)
            loaded = load_campaign(path)
            self.assertEqual(
                list(canonical_neighbors), loaded.provinces[victim_id].neighbors
            )
        smuggled = self._fresh_state()
        smuggled.map_metadata["vertices"] = [[0, 0]]
        with self.assertRaisesRegex(Earth3BootstrapError, "contains geometry authority"):
            smuggled.validate()
        tampered = self._fresh_state()
        victim = next(province for province in tampered.provinces.values() if province.neighbors)
        victim.neighbors = list(victim.neighbors) + ["e3_missing"]
        with self.assertRaisesRegex(
            Earth3BootstrapError, "persisted province topology mismatch"
        ):
            tampered.validate()

    def test_changed_p1_file_bytes_invalidate_process_cache(self) -> None:
        """Real same-process hash-key miss. Does not mock _capture_p1_identity."""

        source_root = _default_authority_root()
        fixed_files = (
            EARTH3_MANIFEST_PATH,
            EARTH3_DATASET_PATH,
            EARTH3_METADATA_PATH,
            EARTH3_PRODUCTION_AUTHORITY_PATH,
        )
        rebuilds: list[str] = []
        original_from_authority = p2_integrity._p1_projection_from_authority

        def counting_from_authority(authority):
            rebuilds.append(str(authority.root))
            return original_from_authority(authority)

        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary) / "authority"
            for relative in fixed_files:
                target = dest / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_root / relative, target)

            first_key = command_scoped_p2_auth._capture_p1_identity(dest)
            first = p2_integrity.load_p1_integrity_projection(dest)
            self.assertEqual(APPROVED_PROVINCE_COUNT, len(first.rows))
            self.assertEqual([first_key], list(p2_integrity._P1_PROJECTION_CACHE))

            p2_integrity._p1_projection_from_authority = counting_from_authority
            try:
                warmed = p2_integrity.load_p1_integrity_projection(dest)
                self.assertEqual([], rebuilds)
                self.assertEqual(APPROVED_PROVINCE_COUNT, len(warmed.rows))

                metadata = dest / EARTH3_METADATA_PATH
                metadata.write_bytes(metadata.read_bytes() + b"\n")
                changed_key = command_scoped_p2_auth._capture_p1_identity(dest)
                self.assertNotEqual(first_key, changed_key)
                self.assertEqual(first_key[0], changed_key[0])
                rebuilt = p2_integrity.load_p1_integrity_projection(dest)
                self.assertEqual(1, len(rebuilds))
                self.assertEqual(APPROVED_PROVINCE_COUNT, len(rebuilt.rows))
                self.assertIn(first_key, p2_integrity._P1_PROJECTION_CACHE)
                self.assertIn(changed_key, p2_integrity._P1_PROJECTION_CACHE)

                dataset = dest / EARTH3_DATASET_PATH
                dataset.write_bytes(dataset.read_bytes() + b" ")
                with self.assertRaisesRegex(
                    Earth3AuthorityError, "dataset bytes/SHA-256 mismatch"
                ):
                    command_scoped_p2_auth._capture_p1_identity(dest)
                with self.assertRaisesRegex(
                    Earth3AuthorityError, "dataset bytes/SHA-256 mismatch"
                ):
                    p2_integrity.load_p1_integrity_projection(dest)
                self.assertEqual(1, len(rebuilds))
            finally:
                p2_integrity._p1_projection_from_authority = original_from_authority

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
