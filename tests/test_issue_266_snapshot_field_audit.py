from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from gates_of_codex import command_cycle_perf
from gates_of_codex.command_cycle_perf import measured_apply_frontend_commands
from gates_of_codex.frontend import (
    FRONTEND_PREVIOUS_SCHEMA_VERSION,
    FRONTEND_SCHEMA_VERSION,
    build_frontend_snapshot,
)
from gates_of_codex.frontend_runtime_patch import (
    RUNTIME_PATCH_SCHEMA,
    RUNTIME_PATCH_SCHEMA_VERSION,
    apply_runtime_patch_to_snapshot,
    build_frontend_runtime_patch,
    persist_runtime_patched_snapshot,
)
from gates_of_codex.frontend_snapshot_slim import (
    FRONTEND_CONSUMED_CAMPAIGN_FIELDS,
    FRONTEND_CONSUMED_CONSTRUCTION_OPTION_FIELDS,
    FRONTEND_CONSUMED_MAP_METADATA_KEYS,
    FRONTEND_CONSUMED_PROVINCE_FIELDS,
    FRONTEND_CONSUMED_TOP_LEVEL,
    FRONTEND_OMITTED_BATTALION_FIELDS,
    FRONTEND_OMITTED_CONSTRUCTION_OPTION_FIELDS,
    FRONTEND_OMITTED_PROVINCE_FIELDS,
    FRONTEND_OMITTED_TOP_LEVEL,
    require_slimmable_frontend_schema,
    slim_construction_options,
    slim_unused_frontend_fields,
    supported_frontend_schema_versions,
)
from gates_of_codex.state_io import save_campaign
from tests.test_issue_266_runtime_patch_live_batch import _move_batch
from tests.test_s10_frontend_presentation_contract import _state


ROOT = Path(__file__).resolve().parents[1]
GODOT_SCRIPTS = ROOT / "godot" / "scripts"
LIVE_GODOT = (
    GODOT_SCRIPTS / "main.gd",
    GODOT_SCRIPTS / "main_writeback.gd",
    GODOT_SCRIPTS / "main_perf.gd",
    GODOT_SCRIPTS / "main_perf_measured.gd",
    GODOT_SCRIPTS / "main_stack_panel.gd",
    GODOT_SCRIPTS / "main_color_id.gd",
    GODOT_SCRIPTS / "main_order_controls.gd",
    GODOT_SCRIPTS / "main_composed_presentation.gd",
    GODOT_SCRIPTS / "main_map_contract.gd",
    GODOT_SCRIPTS / "presentation" / "operational_graph_view.gd",
    GODOT_SCRIPTS / "presentation" / "operational_resolution_presenter.gd",
    GODOT_SCRIPTS / "polygon_map.gd",
    GODOT_SCRIPTS / "color_id_map.gd",
)


def _complete_snapshot(state, **kwargs) -> dict[str, Any]:
    with patch(
        "gates_of_codex.frontend_snapshot_slim.slim_unused_frontend_fields",
        side_effect=lambda payload: payload,
    ):
        return build_frontend_snapshot(state, **kwargs)


def _consumed_campaign(row: dict[str, Any]) -> dict[str, Any]:
    campaign = {
        key: row.get(key)
        for key in FRONTEND_CONSUMED_CAMPAIGN_FIELDS
        if key != "map_metadata"
    }
    metadata = row.get("map_metadata") if isinstance(row.get("map_metadata"), dict) else {}
    campaign["map_metadata"] = {
        key: metadata[key]
        for key in FRONTEND_CONSUMED_MAP_METADATA_KEYS
        if key in metadata
    }
    return campaign


def _consumed_province(row: dict[str, Any]) -> dict[str, Any]:
    projected = {
        key: row.get(key)
        for key in FRONTEND_CONSUMED_PROVINCE_FIELDS
        if key != "construction_options"
    }
    projected["construction_options"] = slim_construction_options(
        row.get("construction_options")
    )
    return projected


def _consumed_battalion(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in FRONTEND_OMITTED_BATTALION_FIELDS
    }


def _consumed_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key in sorted(FRONTEND_CONSUMED_TOP_LEVEL):
        if key not in snapshot:
            continue
        if key == "campaign" and isinstance(snapshot.get(key), dict):
            projected[key] = _consumed_campaign(snapshot[key])
            continue
        if key == "provinces":
            projected[key] = [
                _consumed_province(row)
                for row in snapshot.get(key) or []
                if isinstance(row, dict)
            ]
            continue
        if key == "battalions":
            projected[key] = [
                _consumed_battalion(row)
                for row in snapshot.get(key) or []
                if isinstance(row, dict)
            ]
            continue
        projected[key] = snapshot.get(key)
    return projected


def _removed_map_metadata_keys(snapshot: dict[str, Any]) -> set[str]:
    metadata = (snapshot.get("campaign") or {}).get("map_metadata") or {}
    if not isinstance(metadata, dict):
        return set()
    return set(metadata) - set(FRONTEND_CONSUMED_MAP_METADATA_KEYS)


def _assert_contains_omitted_inventory(test: unittest.TestCase, snapshot: dict[str, Any]) -> None:
    for key in FRONTEND_OMITTED_TOP_LEVEL:
        test.assertIn(key, snapshot)
    test.assertTrue(snapshot.get("provinces"))
    for row in snapshot.get("provinces") or []:
        for key in FRONTEND_OMITTED_PROVINCE_FIELDS:
            test.assertIn(key, row)
        options = [item for item in (row.get("construction_options") or []) if isinstance(item, dict)]
        test.assertTrue(options)
        for option in options:
            for key in FRONTEND_OMITTED_CONSTRUCTION_OPTION_FIELDS:
                test.assertIn(key, option)
    test.assertTrue(snapshot.get("battalions"))
    for row in snapshot.get("battalions") or []:
        for key in FRONTEND_OMITTED_BATTALION_FIELDS:
            test.assertIn(key, row)
    test.assertTrue(_removed_map_metadata_keys(snapshot))


def _assert_omitted_inventory_gone(test: unittest.TestCase, snapshot: dict[str, Any]) -> None:
    for key in FRONTEND_OMITTED_TOP_LEVEL:
        test.assertNotIn(key, snapshot)
    for row in snapshot.get("provinces") or []:
        for key in FRONTEND_OMITTED_PROVINCE_FIELDS:
            test.assertNotIn(key, row)
        for option in row.get("construction_options") or []:
            if not isinstance(option, dict):
                continue
            for key in FRONTEND_OMITTED_CONSTRUCTION_OPTION_FIELDS:
                test.assertNotIn(key, option)
    for row in snapshot.get("battalions") or []:
        for key in FRONTEND_OMITTED_BATTALION_FIELDS:
            test.assertNotIn(key, row)
    test.assertFalse(_removed_map_metadata_keys(snapshot))
    metadata = (snapshot.get("campaign") or {}).get("map_metadata") or {}
    test.assertTrue(set(metadata).issubset(FRONTEND_CONSUMED_MAP_METADATA_KEYS))


_SNAPSHOT_GET = re.compile(
    r"""\bsnapshot\s*(?:\.get\(\s*|\s*\[)\s*["']([A-Za-z0-9_]+)["']"""
)
_EXTENDS = re.compile(r'^extends\s+"res://([^"]+)"', re.MULTILINE)
_OMITTED_ACCESSORS = (
    'snapshot.get("research"',
    "snapshot.get('research'",
    'snapshot["research"]',
    'snapshot.get("commanders"',
    "snapshot.get('commanders'",
    'snapshot["commanders"]',
    'province.get("metadata"',
    'province.get("terrain"',
    'province.get("map_region"',
    'province.get("id_color"',
    'province.get("name_source"',
    'province.get("supply_source_for"',
    'option.get("blocked_reasons"',
    'option.get("level"',
    'option.get("max_level"',
    'battalion.get("roster"',
    'battalion.get("authorized_roster"',
)


def _production_godot_scripts() -> list[Path]:
    scripts: list[Path] = []
    for path in GODOT_SCRIPTS.rglob("*.gd"):
        if "tools" in path.parts:
            continue
        scripts.append(path)
    return scripts


def _follow_extends(start: Path) -> set[Path]:
    seen: set[Path] = set()
    stack = [start]
    while stack:
        path = stack.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8")
        match = _EXTENDS.search(text)
        if match is None:
            continue
        nxt = ROOT / "godot" / match.group(1).replace("/", "\\")
        if nxt.is_file():
            stack.append(nxt)
        else:
            nxt = ROOT / "godot" / match.group(1)
            if nxt.is_file():
                stack.append(nxt)
    return seen


def _live_scene_scripts() -> set[Path]:
    scene = ROOT / "godot" / "main.tscn"
    text = scene.read_text(encoding="utf-8")
    roots: list[Path] = []
    for match in re.finditer(r'path="res://([^"]+\.gd)"', text):
        roots.append(ROOT / "godot" / match.group(1))
    found: set[Path] = set()
    for root in roots:
        found.update(_follow_extends(root))
        found.add(root)
    return {path for path in found if path.is_file()}


def _godot_snapshot_keys(paths: list[Path] | set[Path]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        found.update(_SNAPSHOT_GET.findall(path.read_text(encoding="utf-8")))
    return found


def _godot_live_snapshot_gets() -> set[str]:
    return _godot_snapshot_keys(_live_scene_scripts() | set(_production_godot_scripts()))


class ConsumerInventoryTests(unittest.TestCase):
    def test_inventory_keeps_every_live_godot_snapshot_get(self) -> None:
        live = _godot_live_snapshot_gets()
        self.assertTrue(live)
        unknown = live - FRONTEND_CONSUMED_TOP_LEVEL - {"schema"}
        self.assertEqual(set(), unknown)

    def test_live_godot_still_reads_required_keep_fields(self) -> None:
        main = (GODOT_SCRIPTS / "main.gd").read_text(encoding="utf-8")
        self.assertIn('province.get("construction_options", [])', main)
        self.assertIn('snapshot.get("province_names", {})', main)
        self.assertIn('campaign.get("map_metadata", {})', main)
        self.assertIn('meta.get("province_names", {})', main)
        self.assertIn('snapshot.get("edges", [])', main)
        self.assertIn('snapshot.get("alliances", [])', main)
        stack = (GODOT_SCRIPTS / "main_stack_panel.gd").read_text(encoding="utf-8")
        self.assertIn('map_metadata", {}).get("debug_show_placeholder_units"', stack)
        graph = (
            GODOT_SCRIPTS / "presentation" / "operational_graph_view.gd"
        ).read_text(encoding="utf-8")
        self.assertIn('meta.get("operational_graph"', graph)
        self.assertIn('meta.get("strategic_map_id"', graph)

    def test_live_godot_does_not_read_omitted_snapshot_fields(self) -> None:
        joined = "\n".join(path.read_text(encoding="utf-8") for path in LIVE_GODOT)
        self.assertNotIn('snapshot.get("research"', joined)
        self.assertNotIn('snapshot.get("commanders"', joined)
        self.assertNotIn('province.get("metadata"', joined)
        self.assertNotIn('province.get("terrain"', joined)
        self.assertNotIn('province.get("map_region"', joined)
        self.assertNotIn('province.get("id_color"', joined)
        self.assertNotIn('province.get("name_source"', joined)
        self.assertNotIn('province.get("supply_source_for"', joined)
        self.assertNotIn('option.get("blocked_reasons"', joined)
        self.assertNotIn('battalion.get("roster"', joined)
        self.assertNotIn('battalion.get("authorized_roster"', joined)

    def test_omitted_sets_do_not_overlap_consumed_sets(self) -> None:
        self.assertFalse(FRONTEND_OMITTED_TOP_LEVEL & FRONTEND_CONSUMED_TOP_LEVEL)
        self.assertFalse(
            FRONTEND_OMITTED_PROVINCE_FIELDS & FRONTEND_CONSUMED_PROVINCE_FIELDS
        )
        self.assertFalse(
            FRONTEND_OMITTED_CONSTRUCTION_OPTION_FIELDS
            & FRONTEND_CONSUMED_CONSTRUCTION_OPTION_FIELDS
        )

    def test_inventory_covers_live_scene_inheritance_and_all_production_scripts(self) -> None:
        live_scene = _live_scene_scripts()
        production = set(_production_godot_scripts())
        self.assertIn(GODOT_SCRIPTS / "main_composed_presentation_refresh_safe.gd", live_scene)
        self.assertIn(GODOT_SCRIPTS / "main.gd", live_scene)
        self.assertIn(GODOT_SCRIPTS / "main_writeback.gd", live_scene)
        self.assertTrue(production)
        self.assertTrue(production >= live_scene)
        keys = _godot_snapshot_keys(production)
        unknown = keys - FRONTEND_CONSUMED_TOP_LEVEL - {"schema"}
        self.assertEqual(set(), unknown, sorted(unknown))

    def test_production_godot_has_no_omitted_field_accessors(self) -> None:
        hits: list[str] = []
        for path in _production_godot_scripts():
            text = path.read_text(encoding="utf-8")
            for token in _OMITTED_ACCESSORS:
                if token in text:
                    hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertEqual([], hits)

    def test_production_python_does_not_read_omitted_frontend_snapshot_keys(self) -> None:
        src = ROOT / "src" / "gates_of_codex"
        allow = {
            src / "frontend.py",
            src / "frontend_snapshot_slim.py",
            src / "frontend_runtime_patch.py",
            src / "frontend_fastpath.py",
        }
        omitted = (
            FRONTEND_OMITTED_TOP_LEVEL
            | FRONTEND_OMITTED_PROVINCE_FIELDS
            | FRONTEND_OMITTED_CONSTRUCTION_OPTION_FIELDS
            | FRONTEND_OMITTED_BATTALION_FIELDS
        )
        with tempfile.TemporaryDirectory() as temporary:
            complete = _complete_snapshot(_state(Path(temporary)))
            slimmed = slim_unused_frontend_fields(dict(complete))
            complete_meta = (complete.get("campaign") or {}).get("map_metadata") or {}
            slim_meta = (slimmed.get("campaign") or {}).get("map_metadata") or {}
            omitted = omitted | (set(complete_meta) - set(slim_meta))
        tokens = []
        for key in sorted(omitted):
            tokens.append(f'get("{key}"')
            tokens.append(f'["{key}"]')
        hits: list[str] = []
        for path in src.rglob("*.py"):
            if path in allow or "data" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "gates-of-codex.frontend" not in text and "campaign_snapshot" not in text:
                continue
            for token in tokens:
                if token in text:
                    hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertEqual([], hits)


class SlimParityTests(unittest.TestCase):
    def test_schema_bumps_and_old_snapshots_migrate(self) -> None:
        self.assertEqual(17, FRONTEND_SCHEMA_VERSION)
        self.assertEqual(16, FRONTEND_PREVIOUS_SCHEMA_VERSION)
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            complete = _complete_snapshot(state)
            complete["schema_version"] = FRONTEND_PREVIOUS_SCHEMA_VERSION
            self.assertIn("commanders", complete)
            self.assertIn("metadata", complete["provinces"][0])
            migrated = slim_unused_frontend_fields(complete)
            self.assertEqual(FRONTEND_SCHEMA_VERSION, migrated["schema_version"])
            self.assertEqual("gates-of-codex.frontend", migrated["schema"])
            for key in FRONTEND_OMITTED_TOP_LEVEL:
                self.assertNotIn(key, migrated)
            self.assertNotIn("metadata", migrated["provinces"][0])
            before = _consumed_projection(complete)
            after = _consumed_projection(migrated)
            before.pop("schema_version", None)
            after.pop("schema_version", None)
            self.assertEqual(before, after)

    def test_unsupported_schema_versions_are_rejected(self) -> None:
        self.assertEqual(
            {FRONTEND_PREVIOUS_SCHEMA_VERSION, FRONTEND_SCHEMA_VERSION},
            set(supported_frontend_schema_versions()),
        )
        with tempfile.TemporaryDirectory() as temporary:
            complete = _complete_snapshot(_state(Path(temporary)))
            for bad in (15, 18, True, "16", None):
                payload = dict(complete)
                payload["schema_version"] = bad
                with self.assertRaises(ValueError) as raised:
                    require_slimmable_frontend_schema(payload)
                self.assertIn("unsupported frontend snapshot schema_version", str(raised.exception))
                with self.assertRaises(ValueError):
                    slim_unused_frontend_fields(payload)

    def test_persist_migrates_schema_16_file_and_rejects_others(self) -> None:
        self.assertEqual(
            FRONTEND_SCHEMA_VERSION,
            require_slimmable_frontend_schema({}),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            complete = _complete_snapshot(state)
            snapshot = root / "campaign_snapshot.json"
            fat = dict(complete)
            fat["schema_version"] = FRONTEND_PREVIOUS_SCHEMA_VERSION
            _assert_contains_omitted_inventory(self, fat)
            snapshot.write_text(json.dumps(fat, indent=2) + "\n", encoding="utf-8")
            pre_slim_fat = json.loads(snapshot.read_text(encoding="utf-8"))
            patch = {
                "schema": RUNTIME_PATCH_SCHEMA,
                "schema_version": RUNTIME_PATCH_SCHEMA_VERSION,
                "merge": {
                    "application": {},
                    "campaign": {},
                    "provinces": [],
                    "formations": [],
                },
                "replace": {},
            }
            persist_runtime_patched_snapshot(snapshot, patch)
            persisted = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(FRONTEND_SCHEMA_VERSION, persisted["schema_version"])
            before = _consumed_projection(pre_slim_fat)
            after = _consumed_projection(persisted)
            before.pop("schema_version", None)
            after.pop("schema_version", None)
            self.assertEqual(before, after)
            self.assertEqual(
                _consumed_projection(persisted),
                _consumed_projection(slim_unused_frontend_fields(dict(pre_slim_fat))),
            )
            _assert_omitted_inventory_gone(self, persisted)
            for bad in (15, 18):
                unsupported = root / f"old-{bad}.json"
                old = dict(complete)
                old["schema_version"] = bad
                unsupported.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
                before_bytes = unsupported.read_bytes()
                with self.assertRaises(ValueError):
                    persist_runtime_patched_snapshot(unsupported, patch)
                self.assertEqual(before_bytes, unsupported.read_bytes())

    def test_used_fields_match_pre_slim_and_unused_stay_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            complete = _complete_snapshot(state)
            slimmed = build_frontend_snapshot(state)
            self.assertEqual(_consumed_projection(complete), _consumed_projection(slimmed))
            for key in FRONTEND_OMITTED_TOP_LEVEL:
                self.assertNotIn(key, slimmed)
            for row in slimmed.get("provinces") or []:
                for key in FRONTEND_OMITTED_PROVINCE_FIELDS:
                    self.assertNotIn(key, row)
                for option in row.get("construction_options") or []:
                    self.assertEqual(
                        FRONTEND_CONSUMED_CONSTRUCTION_OPTION_FIELDS,
                        frozenset(option),
                    )
                    for key in FRONTEND_OMITTED_CONSTRUCTION_OPTION_FIELDS:
                        self.assertNotIn(key, option)
            for row in slimmed.get("battalions") or []:
                for key in FRONTEND_OMITTED_BATTALION_FIELDS:
                    self.assertNotIn(key, row)
            metadata = (slimmed.get("campaign") or {}).get("map_metadata") or {}
            self.assertTrue(
                set(metadata).issubset(FRONTEND_CONSUMED_MAP_METADATA_KEYS)
            )
            self.assertIn("construction_options", slimmed["provinces"][0])
            self.assertIn("province_names", slimmed)
            self.assertIn("map_metadata", slimmed["campaign"])

    def test_earth3_projection_omits_static_dataset_duplicate(self) -> None:
        from tests.test_p2_earth3_campaign_bootstrap import _campaign

        slimmed = build_frontend_snapshot(_campaign())
        self.assertGreater(len(slimmed["provinces"]), 3000)
        self.assertIn("construction_options", slimmed["provinces"][0])
        self.assertNotIn("metadata", slimmed["provinces"][0])
        self.assertNotIn("research", slimmed)
        self.assertNotIn("commanders", slimmed)
        actor_runtime = (slimmed.get("campaign") or {}).get("map_metadata") or {}
        self.assertNotIn("actor_content_runtime", actor_runtime)
        self.assertIn("strategic_map_id", actor_runtime)

    def test_runtime_patch_omits_unused_fields_without_widening_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            campaign = root / "campaign.json"
            save_campaign(state, campaign)
            patch = build_frontend_runtime_patch(state, campaign_path=campaign)
            self.assertEqual(RUNTIME_PATCH_SCHEMA, patch["schema"])
            self.assertEqual(RUNTIME_PATCH_SCHEMA_VERSION, patch["schema_version"])
            replace = patch["replace"]
            self.assertNotIn("commanders", replace)
            self.assertNotIn("research", replace)
            for row in replace.get("battalions") or []:
                for key in FRONTEND_OMITTED_BATTALION_FIELDS:
                    self.assertNotIn(key, row)
            for row in patch["merge"].get("provinces") or []:
                for key in FRONTEND_OMITTED_PROVINCE_FIELDS:
                    self.assertNotIn(key, row)
                for option in row.get("construction_options") or []:
                    for key in FRONTEND_OMITTED_CONSTRUCTION_OPTION_FIELDS:
                        self.assertNotIn(key, option)

    def test_refresh_rewrites_slimmer_snapshot_and_is_not_fast(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            save_campaign(state, campaign)
            fat = _complete_snapshot(state, campaign_path=campaign)
            snapshot.write_text(json.dumps(fat, indent=2) + "\n", encoding="utf-8")
            before = snapshot.read_bytes()
            report = measured_apply_frontend_commands(
                campaign,
                commands=[{"op": "refresh"}],
                snapshot_path=snapshot,
            )
            self.assertTrue(report.get("ok"), report)
            self.assertFalse(report["timings"]["snapshot_fast_path"])
            self.assertFalse(report["timings"]["runtime_patch_fast_path"])
            self.assertNotEqual(before, snapshot.read_bytes())
            published = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual("gates-of-codex.frontend", published["schema"])
            for key in FRONTEND_OMITTED_TOP_LEVEL:
                self.assertNotIn(key, published)
            self.assertIn("construction_options", published["provinces"][0])
            self.assertIn("province_names", published)
            self.assertNotIn("commit_move_orders", command_cycle_perf._SNAPSHOT_PATCH_OPS)

    def test_persist_slims_leftover_unused_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            complete = _complete_snapshot(state)
            self.assertIn("commanders", complete)
            self.assertIn("metadata", complete["provinces"][0])
            patch = {
                "schema": RUNTIME_PATCH_SCHEMA,
                "schema_version": RUNTIME_PATCH_SCHEMA_VERSION,
                "merge": {"application": {}, "campaign": {}, "provinces": [], "formations": []},
                "replace": {},
            }
            updated = slim_unused_frontend_fields(
                apply_runtime_patch_to_snapshot(complete, patch)
            )
            self.assertNotIn("commanders", updated)
            self.assertNotIn("metadata", updated["provinces"][0])


def _assert_dynamic_parity(test: unittest.TestCase, patched: dict, full: dict) -> None:
    from tests.test_issue_266_runtime_patch_live_batch import LiveBatchParityTests

    LiveBatchParityTests._assert_dynamic_parity(test, patched, full)


class Slice2StillGreenTests(unittest.TestCase):
    def test_commit_is_not_in_snapshot_patch_ops(self) -> None:
        self.assertNotIn("commit_move_orders", command_cycle_perf._SNAPSHOT_PATCH_OPS)

    def test_issue_commit_parity_survives_slim(self) -> None:
        from gates_of_codex.frontend_runtime_patch import apply_runtime_patch_to_snapshot
        from gates_of_codex.state_io import load_campaign

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            save_campaign(state, campaign)
            before = build_frontend_snapshot(state, campaign_path=campaign)
            snapshot.write_text(json.dumps(before), encoding="utf-8")
            report = measured_apply_frontend_commands(
                campaign,
                commands=_move_batch(),
                snapshot_path=snapshot,
            )
            self.assertTrue(report.get("ok"))
            self.assertTrue(report["timings"]["runtime_patch_fast_path"])
            patched = apply_runtime_patch_to_snapshot(before, report["frontend_patch"])
            full = build_frontend_snapshot(load_campaign(campaign), campaign_path=campaign)
            _assert_dynamic_parity(self, patched, full)
