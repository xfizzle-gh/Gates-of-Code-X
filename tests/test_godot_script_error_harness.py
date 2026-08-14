from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"
WORKFLOW = ROOT / ".github/workflows/gates-of-codex.yml"
GRAPH_TEST = GODOT / "scripts/tools/graph_movement_scene_test.gd"
MAP_TEST = GODOT / "scripts/tools/map_order_controls_test.gd"
FALSE_PASS = GODOT / "scripts/tools/script_error_false_pass_fixture.gd"

COMPILE_FAILURE_MARKERS = ("SCRIPT ERROR", "Parse Error", "Compile Error")


def _godot_executable() -> Path | None:
    explicit = str(os.environ.get("GODOT_BIN", "")).strip()
    if not explicit:
        return None
    candidate = Path(explicit)
    if not candidate.is_file():
        raise AssertionError(f"GODOT_BIN is not a file: {candidate}")
    return candidate.resolve()


def _step_named(workflow: str, name: str) -> str:
    marker = f"      - name: {name}"
    start = workflow.index(marker)
    rest = workflow[start + len(marker) :]
    nxt = rest.find("\n      - name:")
    if nxt < 0:
        nxt = rest.find("\n  ")
    return workflow[start : start + len(marker) + nxt]


def _run_godot_script(script: str) -> subprocess.CompletedProcess[str]:
    executable = _godot_executable()
    if executable is None:
        raise unittest.SkipTest(
            "GODOT_BIN is unset; live Godot 4.7 proof runs in godot-map"
        )
    return subprocess.run(
        [
            str(executable),
            "--headless",
            "--path",
            str(GODOT),
            "--audio-driver",
            "Dummy",
            "-s",
            script,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def godot_strict_exit_code(completed: subprocess.CompletedProcess[str]) -> int:
    output = completed.stdout + completed.stderr
    if any(marker in output for marker in COMPILE_FAILURE_MARKERS):
        return 1
    return int(completed.returncode)


class GodotScriptErrorHarnessContractTests(unittest.TestCase):
    def test_movement_tests_gate_production_main_before_pass(self) -> None:
        for path in (GRAPH_TEST, MAP_TEST):
            source = path.read_text(encoding="utf-8")
            self.assertIn("func _require_production_main()", source)
            self.assertIn("if not _require_production_main():", source)
            self.assertIn("production MainScript failed to preload", source)
            self.assertIn("can_instantiate()", source)
            self.assertLess(
                source.index("if not _require_production_main():"),
                source.index(": PASS"),
            )

    def test_godot_map_treats_movement_script_errors_as_failure(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        graph = _step_named(workflow, "Godot graph-native movement dispatch test (#206)")
        order = _step_named(workflow, "Godot map order-controls test (#218)")
        self.assertIn("graph_movement_scene_test.gd", graph)
        self.assertIn("SCRIPT ERROR", graph)
        self.assertIn("graph_movement_scene_test: PASS", graph)
        self.assertIn("map_order_controls_test.gd", order)
        self.assertIn("SCRIPT ERROR", order)
        self.assertIn("map_order_controls_test: PASS", order)
        map_source = MAP_TEST.read_text(encoding="utf-8")
        self.assertIn("_test_production_p3_graph_loads_and_renders_native_route", map_source)
        self.assertIn("scene._open_operational_graph()", map_source)
        self.assertLess(
            map_source.index("if not _require_production_main():"),
            map_source.index("_test_production_p3_graph_loads_and_renders_native_route"),
        )
        self.assertIn(
            'GODOT_BIN="$HOME/godot" python -m unittest tests.test_godot_script_error_harness -v',
            workflow,
        )

    def test_false_pass_fixture_loads_broken_startup_dependency(self) -> None:
        source = FALSE_PASS.read_text(encoding="utf-8")
        broken = (GODOT / "scripts/tools/broken_extends_layer.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'extends "res://scripts/main_startup_measured_ABSENT.gd"', broken
        )
        self.assertIn('load("res://scripts/tools/broken_extends_layer.gd")', source)
        self.assertIn("script_error_false_pass_fixture: PASS", source)


class GodotScriptErrorHarnessLiveTests(unittest.TestCase):
    def test_false_pass_after_compile_error_exits_nonzero(self) -> None:
        completed = _run_godot_script(
            "res://scripts/tools/script_error_false_pass_fixture.gd"
        )
        output = completed.stdout + completed.stderr
        self.assertTrue(
            any(marker in output for marker in COMPILE_FAILURE_MARKERS),
            output,
        )
        self.assertIn("script_error_false_pass_fixture: PASS", output)
        self.assertNotEqual(0, godot_strict_exit_code(completed), output)

    def test_graph_movement_scene_passes_without_script_error(self) -> None:
        completed = _run_godot_script(
            "res://scripts/tools/graph_movement_scene_test.gd"
        )
        output = completed.stdout + completed.stderr
        self.assertNotIn("SCRIPT ERROR", output, output)
        self.assertIn("graph_movement_scene_test: PASS", output)
        self.assertEqual(0, godot_strict_exit_code(completed), output)

    def test_map_order_controls_passes_without_script_error(self) -> None:
        completed = _run_godot_script("res://scripts/tools/map_order_controls_test.gd")
        output = completed.stdout + completed.stderr
        self.assertNotIn("SCRIPT ERROR", output, output)
        self.assertIn("map_order_controls_test: PASS", output)
        self.assertEqual(0, godot_strict_exit_code(completed), output)
