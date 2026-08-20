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
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.frontend_runtime_patch import (
    RUNTIME_PATCH_SCHEMA,
    RUNTIME_PATCH_SCHEMA_VERSION,
    apply_runtime_patch_to_snapshot,
    build_frontend_runtime_patch,
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
    slim_construction_options,
    slim_unused_frontend_fields,
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


def _godot_live_snapshot_gets() -> set[str]:
    pattern = re.compile(r'snapshot\.get\(\s*"([A-Za-z0-9_]+)"')
    found: set[str] = set()
    for path in LIVE_GODOT:
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


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


class SlimParityTests(unittest.TestCase):
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
