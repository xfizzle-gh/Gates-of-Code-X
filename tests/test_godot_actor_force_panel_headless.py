from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"
SCRIPT = "res://scripts/tools/actor_force_panel_test.gd"


def _godot_executable() -> Path | None:
    explicit = str(os.environ.get("GODOT_BIN", "")).strip()
    if not explicit:
        return None
    candidate = Path(explicit)
    if not candidate.is_file():
        raise AssertionError(f"GODOT_BIN is not a file: {candidate}")
    return candidate.resolve()


class GodotActorForcePanelHeadlessTests(unittest.TestCase):
    def test_headless_force_panel_contract(self) -> None:
        executable = _godot_executable()
        if executable is None:
            raise unittest.SkipTest(
                "GODOT_BIN is unset; live Godot 4.7 proof runs in godot-map"
            )
        completed = subprocess.run(
            [
                str(executable),
                "--headless",
                "--path",
                str(GODOT),
                "--audio-driver",
                "Dummy",
                "-s",
                SCRIPT,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        output = completed.stdout + completed.stderr
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("Parse Error", output)
        self.assertEqual(0, completed.returncode, output)
        self.assertIn("actor_force_panel_test:", output)


if __name__ == "__main__":
    unittest.main()
