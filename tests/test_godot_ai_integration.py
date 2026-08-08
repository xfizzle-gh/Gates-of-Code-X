from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "dev" / "godot-ai" / "lock.json"
SETUP_PATH = ROOT / "dev" / "godot-ai" / "setup.ps1"
LAUNCHER_PATH = ROOT / "dev" / "godot-ai" / "open-editor.ps1"
DEPLOY_PATH = ROOT / "tools" / "deploy_workshop_test.ps1"


class GodotAiIntegrationContractTests(unittest.TestCase):
    def test_dependency_is_exactly_pinned(self) -> None:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

        self.assertEqual(lock["schema_version"], 1)
        self.assertEqual(lock["repository"], "https://github.com/hi-godot/godot-ai.git")
        self.assertEqual(lock["version"], "3.1.3")
        self.assertRegex(lock["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            lock["commit"],
            "22678e5f9b038d7203d6b43b0aae20a5417c500e",
        )
        self.assertEqual(lock["plugin_source_subpath"], "plugin/addons/godot_ai")
        self.assertEqual(lock["plugin_install_subpath"], "godot/addons/godot_ai")
        self.assertIs(lock["telemetry_disabled"], True)

    def test_local_addon_and_state_are_ignored(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn(".godot-ai/", ignore.splitlines())
        self.assertIn("godot/addons/godot_ai/", ignore.splitlines())

    def test_setup_verifies_commit_version_and_telemetry_contract(self) -> None:
        script = SETUP_PATH.read_text(encoding="utf-8")

        self.assertIn('"fetch", "--depth", "1", "origin", $Commit', script)
        self.assertIn("$ResolvedCommit -ne $Commit", script)
        self.assertIn("Pinned plugin version does not match lock version", script)
        self.assertIn("telemetry_disabled=true", script)
        self.assertIn("Do not use the plugin self-updater", script)
        self.assertIn("${LASTEXITCODE}: git", script)
        self.assertNotIn("$LASTEXITCODE: git", script)

    def test_powershell_integration_scripts_parse(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable on this runner")

        parse_command = (
            "$ErrorActionPreference='Stop'; "
            "[void][scriptblock]::Create([IO.File]::ReadAllText($args[0]))"
        )
        for script_path in (SETUP_PATH, LAUNCHER_PATH, DEPLOY_PATH):
            with self.subTest(script=script_path.relative_to(ROOT).as_posix()):
                result = subprocess.run(
                    [powershell, "-NoProfile", "-Command", parse_command, str(script_path)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    msg=(result.stdout + result.stderr).strip(),
                )

    def test_launcher_disables_telemetry_before_starting_godot(self) -> None:
        script = LAUNCHER_PATH.read_text(encoding="utf-8")

        disable_index = script.index('$env:GODOT_AI_DISABLE_TELEMETRY = "true"')
        launch_index = script.index("Start-Process")
        self.assertLess(disable_index, launch_index)
        self.assertIn('$env:DISABLE_TELEMETRY = "true"', script)
        self.assertIn('"--editor", "--path", $ProjectRoot', script)

    def test_workshop_deployment_excludes_development_tree(self) -> None:
        script = DEPLOY_PATH.read_text(encoding="utf-8")

        self.assertRegex(script, re.compile(r'\$DevelopmentOnlyPrefixes\s*=\s*@\(\s*"dev/"', re.S))
        self.assertIn("Test-DevelopmentOnlyPath", script)
        self.assertIn("excluded_development_files", script)
        self.assertIn("Where-Object { -not (Test-DevelopmentOnlyPath -Path $_) }", script)


if __name__ == "__main__":
    unittest.main()
