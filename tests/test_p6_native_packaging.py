"""P6 native packaging regressions discovered by owner Windows acceptance."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AUTHORITY_FILES = (
    "config\\earth3\\production_authority.json",
    "config\\earth3\\p3_operational_authority.json",
    "godot\\assets\\maps\\earth3_europe_mediterranean\\map_manifest.json",
    "godot\\assets\\maps\\earth3_europe_mediterranean\\polygon_dataset.json",
    "godot\\assets\\maps\\earth3_europe_mediterranean\\dataset_meta.json",
    "godot\\assets\\maps\\earth3_europe_mediterranean\\p3_authority\\p3_operational_graph.json",
    "docs\\audits\\p3-first-corridor-route-inventory.json",
    "src\\gates_of_codex\\data\\earth3_v1\\sites.json",
)


class P6NativePackagingTests(unittest.TestCase):
    def test_campaign_executable_uses_player_shell_not_legacy_tk_gui(self) -> None:
        launcher = (ROOT / "run_gates_of_codex.py").read_text(encoding="utf-8")
        self.assertIn("from gates_of_codex.fast_entrypoint import main", launcher)
        self.assertNotIn("gates_of_codex.gui", launcher)
        self.assertIn("raise SystemExit(main())", launcher)

    def test_source_installer_stages_and_authenticates_exact_earth3_runtime_files(self) -> None:
        installer = (ROOT / "tools" / "install_gates_of_codex.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('$InstalledAuthorityRoot = Join-Path $Venv "Lib"', installer)
        self.assertIn("Installed Earth3 P1/P3 authority smoke failed", installer)
        self.assertIn("load_earth3_authority", installer)
        self.assertIn("load_authenticated_p3_graph", installer)
        for relative in AUTHORITY_FILES:
            self.assertIn(f'"{relative}"', installer, relative)
        self.assertIn("@AuthorityAddDataArgs", installer)
        self.assertIn("Frozen executable is missing Earth3 runtime authority", installer)

    def test_release_build_embeds_same_authenticated_authority_set(self) -> None:
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("$authorityData = @(", release)
        self.assertEqual(2, release.count("@authorityData --add-data"))
        self.assertIn("Smoke frozen provenance and Earth3 authority payload", release)
        required_names = (
            "production_authority.json",
            "p3_operational_authority.json",
            "map_manifest.json",
            "polygon_dataset.json",
            "dataset_meta.json",
            "p3_operational_graph.json",
            "p3-first-corridor-route-inventory.json",
            "sites.json",
        )
        for name in required_names:
            self.assertIn(name, release, name)

    def test_workshop_deployment_provenance_never_falls_back_to_unknown(self) -> None:
        deploy = (ROOT / "tools" / "deploy_workshop_test.ps1").read_text(
            encoding="utf-8-sig"
        )
        installer = (ROOT / "tools" / "install_gates_of_codex.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('[string]$SourceCommit = ""', deploy)
        self.assertIn("rev-parse --verify HEAD", deploy)
        self.assertIn("Unable to authenticate deployment source commit", deploy)
        self.assertNotIn('$commit = "unknown"', deploy)
        self.assertIn("-SourceCommit $SourceCommit", installer)


if __name__ == "__main__":
    unittest.main()
