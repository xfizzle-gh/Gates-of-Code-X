from __future__ import annotations

import json
from pathlib import Path

from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION
from gates_of_codex.frontend_snapshot_slim import (
    FRONTEND_CONSUMED_MAP_METADATA_KEYS,
    FRONTEND_OMITTED_PROVINCE_FIELDS,
    slim_unused_frontend_fields,
)


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SCENE = ROOT / "godot/main.tscn"
PRODUCTION_SCRIPT = ROOT / "godot/scripts/main_composed_presentation_refresh_safe.gd"
POST_P8_GATE = ROOT / "docs/research/noresus-map-performance/production-switch-gate.json"


def test_production_strategic_screen_surfaces_active_2028_scenario_and_controller_identity() -> None:
    scene = PRODUCTION_SCENE.read_text(encoding="utf-8")
    script = PRODUCTION_SCRIPT.read_text(encoding="utf-8")

    assert "main_composed_presentation_refresh_safe.gd" in scene
    assert 'extends "res://scripts/main_composed_presentation.gd"' in script
    assert 'province.get("metadata"' not in script
    for token in (
        "scenario_selection",
        "active_scenario_id",
        "active_scenario_label",
        "active_actor_id",
        "ww3_2028_controller_profile",
        "sovereign_owner",
        "military_controller",
        "controller_profile",
        'province.get("sovereign_owner"',
        "Scenario:",
        "SOV %s  |  CTRL %s",
    ):
        assert token in script


def test_slimed_2028_snapshot_keeps_scenario_and_controller_identity() -> None:
    snapshot = {
        "schema": "gates-of-codex.frontend",
        "schema_version": FRONTEND_SCHEMA_VERSION,
        "campaign": {
            "map_metadata": {
                "scenario_id": "ww3_2028_core",
                "scenario_display_name": "WW3 2028 Core",
                "ww3_2028_controller_profile": "core",
                "scenario_selection": {
                    "active_scenario_id": "ww3_2028_core",
                    "active_scenario_label": "WW3 2028 Core",
                    "active_actor_id": "nato",
                    "continue_uses_persisted_scenario": True,
                },
                "actor_content_runtime": {"drop": True},
            }
        },
        "provinces": [
            {
                "id": "e3_0001",
                "owner": "prc",
                "sovereign_owner": "BLR",
                "military_controller": "prc",
                "controller_profile": "core",
                "metadata": {"huge": True, "sovereign_owner": "BLR"},
            }
        ],
    }

    slimmed = slim_unused_frontend_fields(snapshot)
    metadata = slimmed["campaign"]["map_metadata"]
    province = slimmed["provinces"][0]

    assert metadata["scenario_id"] == "ww3_2028_core"
    assert metadata["ww3_2028_controller_profile"] == "core"
    assert metadata["scenario_selection"]["active_scenario_id"] == "ww3_2028_core"
    assert metadata["scenario_selection"]["active_actor_id"] == "nato"
    assert "actor_content_runtime" not in metadata
    assert set(metadata) <= set(FRONTEND_CONSUMED_MAP_METADATA_KEYS)
    assert province["sovereign_owner"] == "BLR"
    assert province["military_controller"] == "prc"
    assert province["controller_profile"] == "core"
    assert "metadata" not in province
    assert "metadata" in FRONTEND_OMITTED_PROVINCE_FIELDS


def test_frontend_lifts_2028_controller_identity_out_of_omitted_metadata() -> None:
    from gates_of_codex.frontend import _province_2028_presentation

    assert _province_2028_presentation(
        {
            "sovereign_owner": "BLR",
            "military_controller": "prc",
            "controller_profile": "core",
            "front_source": "omit-from-presentation",
        }
    ) == {
        "sovereign_owner": "BLR",
        "military_controller": "prc",
        "controller_profile": "core",
    }
    assert _province_2028_presentation({}) == {}
    assert _province_2028_presentation("not-a-mapping") == {}


def test_persist_seam_stays_live_move_batch_or_auto_resolve() -> None:
    from gates_of_codex.command_cycle_perf import (
        _LIVE_MOVE_BATCH,
        _RUNTIME_PATCH_OPS,
        _SNAPSHOT_PATCH_OPS,
        _should_persist_runtime_snapshot,
    )

    assert _LIVE_MOVE_BATCH == ("issue_move_order", "commit_move_orders")
    assert "refresh" not in _RUNTIME_PATCH_OPS
    assert "refresh" not in _SNAPSHOT_PATCH_OPS
    assert _should_persist_runtime_snapshot(
        [{"op": "issue_move_order"}, {"op": "commit_move_orders"}]
    )
    assert _should_persist_runtime_snapshot([{"op": "auto_resolve"}])
    assert not _should_persist_runtime_snapshot([{"op": "refresh"}])
    assert not _should_persist_runtime_snapshot([{"op": "end_player_round"}])


def test_production_unit_counter_color_follows_unit_faction_not_province_owner() -> None:
    script = PRODUCTION_SCRIPT.read_text(encoding="utf-8")

    assert 'battalion.get("faction", "neutral")' in script
    assert 'FACTION_COLORS.get(faction_id, FACTION_COLORS["neutral"])' in script
    assert "super._draw_battalion_counter(position, battalion, faction_color, selected)" in script


def test_post_p8_map_ui_regression_gate_remains_locked_for_slice_f() -> None:
    gate = json.loads(POST_P8_GATE.read_text(encoding="utf-8"))
    baseline = gate["accepted_post_p8_baseline"]
    regression = baseline["regression_rule"]

    assert gate["baseline_status"] == "ACCEPTED"
    assert baseline["production_renderer"] == "PolygonMap"
    assert baseline["hybrid_candidate"]["production_default"] is False
    assert regression["metric"] == "representative p95 frame time or command latency"
    assert regression["maximum_unapproved_regression_ratio"] == 0.10
    assert regression["exception"] == "explicit owner approval with documented tradeoff"
