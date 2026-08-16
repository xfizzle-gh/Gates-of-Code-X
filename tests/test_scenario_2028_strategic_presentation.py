from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SCENE = ROOT / "godot/main.tscn"
PRODUCTION_SCRIPT = ROOT / "godot/scripts/main_composed_presentation_refresh_safe.gd"
POST_P8_GATE = ROOT / "docs/research/noresus-map-performance/production-switch-gate.json"


def test_production_strategic_screen_surfaces_active_2028_scenario_and_controller_identity() -> None:
    scene = PRODUCTION_SCENE.read_text(encoding="utf-8")
    script = PRODUCTION_SCRIPT.read_text(encoding="utf-8")

    assert "main_composed_presentation_refresh_safe.gd" in scene
    assert 'extends "res://scripts/main_composed_presentation.gd"' in script
    for token in (
        "scenario_selection",
        "active_scenario_id",
        "active_scenario_label",
        "active_actor_id",
        "ww3_2028_controller_profile",
        "sovereign_owner",
        "military_controller",
        "controller_profile",
        "Scenario:",
        "SOV %s  |  CTRL %s",
    ):
        assert token in script


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
