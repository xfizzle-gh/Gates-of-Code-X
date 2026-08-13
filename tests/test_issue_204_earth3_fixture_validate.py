from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"
VALIDATOR = GODOT / "scripts/tools/earth3_fixture_validate.gd"
WORKFLOW = ROOT / ".github/workflows/gates-of-codex.yml"
PRODUCTION_SNAPSHOT = GODOT / "fixtures/snapshots/earth3_operational.json"
PRODUCTION_FIXTURE = GODOT / "fixtures/presentation/e3_operational.json"
KNOWN_FIXTURE_PROVINCE = "e3_2108"
KNOWN_SNAPSHOT_ORIGIN = "e3_2781"


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


def _run_validator(*user_args: str) -> subprocess.CompletedProcess[str]:
    executable = _godot_executable()
    if executable is None:
        raise unittest.SkipTest(
            "GODOT_BIN is unset; live Godot 4.7 proof runs in godot-map"
        )
    command = [
        str(executable),
        "--headless",
        "--path",
        str(GODOT),
        "--audio-driver",
        "Dummy",
        "-s",
        "res://scripts/tools/earth3_fixture_validate.gd",
    ]
    if user_args:
        command.append("--")
        command.extend(user_args)
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class FixtureValidateContractTests(unittest.TestCase):
    def test_validator_type_checks_every_former_string_constructor_site(self) -> None:
        source = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn("func _as_id(", source)
        self.assertIn("func _as_key(", source)
        self.assertIn("null identifier at", source)
        self.assertIn("non-string identifier at", source)
        self.assertIn("malformed 2-tuple reference", source)
        self.assertIn("_failed", source)
        self.assertNotIn("var a := String(", source)
        self.assertNotIn("var b := String(", source)
        self.assertNotIn("out.append(String(", source)
        self.assertNotIn("var pid := String(", source)
        self.assertNotIn("var id := String(r)", source)
        self.assertNotIn('String((b as Dictionary).get("faction"', source)

    def test_validator_accepts_path_overrides_for_adversarial_copies(self) -> None:
        source = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn("--fixture=", source)
        self.assertIn("--snapshot=", source)
        self.assertIn("--dataset=", source)

    def test_godot_map_treats_script_error_as_failure_and_requires_pass(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = _step_named(workflow, "Godot Earth3 operational fixture validate (e3_* only)")
        self.assertIn("earth3_fixture_validate.gd", step)
        self.assertIn("SCRIPT ERROR", step)
        self.assertIn("earth3_fixture_validate: FAIL", step)
        self.assertIn("earth3_fixture_validate: PASS", step)
        self.assertIn(
            'GODOT_BIN="$HOME/godot" python -m unittest tests.test_issue_204_earth3_fixture_validate -v',
            workflow,
        )


class FixtureValidateLiveTests(unittest.TestCase):
    def test_production_fixture_passes_without_script_error(self) -> None:
        completed = _run_validator()
        output = completed.stdout + completed.stderr
        self.assertNotIn("SCRIPT ERROR", output, output)
        self.assertNotIn("earth3_fixture_validate: FAIL", output, output)
        self.assertIn("earth3_fixture_validate: PASS", output)
        self.assertEqual(0, completed.returncode, output)

    def test_corrupted_goe_province_reference_exits_nonzero(self) -> None:
        fixture = json.loads(PRODUCTION_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(KNOWN_FIXTURE_PROVINCE, fixture["selected_province_id"])
        fixture["selected_province_id"] = "Baden"
        with tempfile.TemporaryDirectory() as temporary:
            corrupt = Path(temporary) / "corrupt_fixture.json"
            _write_json(corrupt, fixture)
            completed = _run_validator(f"--fixture={corrupt.resolve().as_posix()}")
        output = completed.stdout + completed.stderr
        self.assertNotIn("SCRIPT ERROR", output, output)
        self.assertNotIn("earth3_fixture_validate: PASS", output, output)
        self.assertIn("earth3_fixture_validate: FAIL", output)
        self.assertIn("Baden", output)
        self.assertNotEqual(0, completed.returncode, output)

    def test_corrupted_missing_e3_reference_exits_nonzero(self) -> None:
        fixture = json.loads(PRODUCTION_FIXTURE.read_text(encoding="utf-8"))
        fixture["selected_province_id"] = "e3_does_not_exist"
        with tempfile.TemporaryDirectory() as temporary:
            corrupt = Path(temporary) / "missing_fixture.json"
            _write_json(corrupt, fixture)
            completed = _run_validator(f"--fixture={corrupt.resolve().as_posix()}")
        output = completed.stdout + completed.stderr
        self.assertNotIn("SCRIPT ERROR", output, output)
        self.assertNotIn("earth3_fixture_validate: PASS", output, output)
        self.assertIn("earth3_fixture_validate: FAIL", output)
        self.assertIn("e3_does_not_exist", output)
        self.assertNotEqual(0, completed.returncode, output)

    def test_null_province_reference_fails_closed_without_string_constructor_error(
        self,
    ) -> None:
        snapshot = json.loads(PRODUCTION_SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(
            KNOWN_SNAPSHOT_ORIGIN,
            snapshot["pending_battle"]["origin_province_id"],
        )
        snapshot["pending_battle"]["origin_province_id"] = None
        with tempfile.TemporaryDirectory() as temporary:
            corrupt = Path(temporary) / "null_snapshot.json"
            _write_json(corrupt, snapshot)
            completed = _run_validator(f"--snapshot={corrupt.resolve().as_posix()}")
        output = completed.stdout + completed.stderr
        self.assertNotIn("SCRIPT ERROR", output, output)
        self.assertNotIn("Nonexistent 'String' constructor", output, output)
        self.assertNotIn("earth3_fixture_validate: PASS", output, output)
        self.assertIn("earth3_fixture_validate: FAIL", output)
        self.assertIn("null identifier", output)
        self.assertNotEqual(0, completed.returncode, output)


class FrozenAuthorityBytesTests(unittest.TestCase):
    def test_issue_does_not_rewrite_production_earth3_bytes(self) -> None:
        self.assertTrue(PRODUCTION_SNAPSHOT.is_file())
        self.assertTrue(PRODUCTION_FIXTURE.is_file())
        fixture = json.loads(PRODUCTION_FIXTURE.read_text(encoding="utf-8"))
        snapshot = json.loads(PRODUCTION_SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(KNOWN_FIXTURE_PROVINCE, fixture["selected_province_id"])
        self.assertEqual(
            KNOWN_SNAPSHOT_ORIGIN,
            snapshot["pending_battle"]["origin_province_id"],
        )
        self.assertNotIn("Baden", json.dumps(fixture))
        self.assertNotIn("e3_does_not_exist", json.dumps(fixture))
