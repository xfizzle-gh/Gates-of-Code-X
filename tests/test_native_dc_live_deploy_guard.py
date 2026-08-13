"""Regression coverage for Core-safe Workshop deployment before bounded GOC staging."""
from __future__ import annotations

import unittest
from pathlib import Path


class NativeDcLiveDeployGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.script = (cls.root / "tools/deploy_workshop_live.ps1").read_text(encoding="utf-8")

    def test_default_live_deploy_excludes_global_native_dc_picker_surfaces(self) -> None:
        for relative in (
            "resource/set/dynamic_campaign/values.set",
            "resource/set/multiplayer/games/campaign_capture_the_flag.set",
            "resource/set/multiplayer/games/presets/alliances_generic.inc",
        ):
            self.assertIn(f'"{relative}"', self.script)
        self.assertIn("^resource/set/multiplayer/armies/goc_[^/]+\\.set$", self.script)
        self.assertIn("Test-ExcludedNativeDcRegistration", self.script)
        self.assertIn('deployment_kind = "core_safe_owner_native_live_workshop"', self.script)

    def test_powershell_strict_mode_initializes_last_exit_code(self) -> None:
        self.assertIn("Set-StrictMode -Version Latest", self.script)
        self.assertIn("$global:LASTEXITCODE = 0", self.script)

    def test_deploy_fails_if_goc_armies_or_global_picker_files_leak(self) -> None:
        self.assertIn("Core-safe deployment leaked GOC army registration", self.script)
        self.assertIn("Core-safe deployment leaked global Dynamic Conquest registration", self.script)


if __name__ == "__main__":
    unittest.main()
