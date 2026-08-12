"""P6 native packaging regressions discovered by owner Windows acceptance."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gates_of_codex import fast_entrypoint, frozen_runtime

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
    def test_campaign_executable_dispatches_directly_to_player_shell(self) -> None:
        launcher = (ROOT / "run_gates_of_codex.py").read_text(encoding="utf-8")
        self.assertIn("from gates_of_codex.fast_entrypoint import player_main", launcher)
        self.assertNotIn("gates_of_codex.gui", launcher)
        self.assertIn("raise SystemExit(player_main())", launcher)

    def test_zero_argument_player_executable_defaults_new_then_continue(self) -> None:
        shell_main = Mock(return_value=0)
        with (
            patch("gates_of_codex.frontend_fastpath.install_frontend_fast_path"),
            patch("gates_of_codex.turn_cycle.install_frontend_turn_cycle_op"),
            patch("gates_of_codex.frozen_runtime.configure_frozen_earth3_authority"),
            patch("gates_of_codex.player_shell.main", shell_main),
            patch("gates_of_codex.player_shell.read_last_campaign", return_value=None),
        ):
            self.assertEqual(0, fast_entrypoint.player_main([]))
        shell_main.assert_called_once_with(["--new"])

        shell_main.reset_mock()
        with (
            patch("gates_of_codex.frontend_fastpath.install_frontend_fast_path"),
            patch("gates_of_codex.turn_cycle.install_frontend_turn_cycle_op"),
            patch("gates_of_codex.frozen_runtime.configure_frozen_earth3_authority"),
            patch("gates_of_codex.player_shell.main", shell_main),
            patch(
                "gates_of_codex.player_shell.read_last_campaign",
                return_value=Path("remembered/campaign.json"),
            ),
        ):
            self.assertEqual(0, fast_entrypoint.player_main([]))
        shell_main.assert_called_once_with(["--continue"])

    def test_explicit_player_arguments_are_not_rewritten(self) -> None:
        shell_main = Mock(return_value=0)
        arguments = ["--new", "--campaign", "C:/test/campaign"]
        with (
            patch("gates_of_codex.frontend_fastpath.install_frontend_fast_path"),
            patch("gates_of_codex.turn_cycle.install_frontend_turn_cycle_op"),
            patch("gates_of_codex.frozen_runtime.configure_frozen_earth3_authority"),
            patch("gates_of_codex.player_shell.main", shell_main),
            patch("gates_of_codex.player_shell.read_last_campaign") as remembered,
        ):
            self.assertEqual(0, fast_entrypoint.player_main(arguments))
        shell_main.assert_called_once_with(arguments)
        remembered.assert_not_called()

    def test_frozen_bundle_configuration_redirects_only_default_p1_p3_roots(self) -> None:
        from gates_of_codex import earth3_campaign, earth3_operational

        original_p1_root = earth3_campaign._default_authority_root
        original_p3_loader = earth3_operational.load_authenticated_p3_graph
        original_configured = frozen_runtime._CONFIGURED_ROOT
        fake_p3 = Mock(return_value={"nodes": [], "edges": []})
        try:
            earth3_operational.load_authenticated_p3_graph = fake_p3
            frozen_runtime._CONFIGURED_ROOT = None
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                with (
                    patch.object(sys, "frozen", True, create=True),
                    patch.object(sys, "_MEIPASS", str(root), create=True),
                ):
                    self.assertEqual(root, frozen_runtime.configure_frozen_earth3_authority())
                    self.assertEqual(root, earth3_campaign._default_authority_root())
                    wrapped = earth3_operational.load_authenticated_p3_graph
                    wrapped()
                    fake_p3.assert_called_once_with(repository_root=root)
                    explicit = root / "explicit"
                    wrapped(repository_root=explicit)
                    fake_p3.assert_called_with(repository_root=explicit)
        finally:
            earth3_campaign._default_authority_root = original_p1_root
            earth3_operational.load_authenticated_p3_graph = original_p3_loader
            frozen_runtime._CONFIGURED_ROOT = original_configured

    def test_package_registers_one_automatic_pyinstaller_authority_contract(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        registration = (ROOT / "src" / "gates_of_codex" / "__pyinstaller.py").read_text(
            encoding="utf-8"
        )
        hook = (
            ROOT
            / "src"
            / "gates_of_codex"
            / "pyinstaller_hooks"
            / "hook-gates_of_codex.py"
        ).read_text(encoding="utf-8")
        self.assertIn("[project.entry-points.pyinstaller40]", pyproject)
        self.assertIn('hook-dirs = "gates_of_codex.__pyinstaller:get_hook_dirs"', pyproject)
        self.assertIn("pyinstaller_hooks", registration)
        self.assertIn('collect_data_files("gates_of_codex")', hook)
        for relative in AUTHORITY_FILES:
            self.assertIn(relative.replace("\\", "/"), hook)

    def test_gates_ci_frozen_live_smoke_executes_authority_loaders(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "gates-of-codex.yml").read_text(
            encoding="utf-8"
        )
        live_launcher = (ROOT / "run_gates_of_codex_live.py").read_text(encoding="utf-8")
        self.assertIn("GatesOfCodeXLive.exe", workflow)
        self.assertIn("--help", workflow)
        self.assertIn("_authenticate_frozen_earth3()", live_launcher)
        self.assertIn("load_earth3_authority", live_launcher)
        self.assertIn("load_authenticated_p3_graph", live_launcher)

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
        self.assertEqual(2, installer.count("--collect-data gates_of_codex"))
        self.assertIn("@AuthorityAddDataArgs", installer)
        self.assertIn("Frozen executable is missing Earth3 runtime authority", installer)
        self.assertIn("bootstrap.json", installer)
        self.assertIn("formations.json", installer)

    def test_release_build_embeds_same_authenticated_authority_set(self) -> None:
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("$authorityData = @(", release)
        self.assertEqual(2, release.count("--collect-data gates_of_codex"))
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
            "bootstrap.json",
            "formations.json",
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
