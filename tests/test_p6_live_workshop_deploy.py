from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class P6LiveWorkshopDeploymentContractTests(unittest.TestCase):
    def test_live_deploy_is_explicit_backed_up_and_byte_verified(self) -> None:
        source = (ROOT / "tools/deploy_workshop_live.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$AcceptWorkshopMutation", source)
        self.assertIn("Live Workshop deployment is destructive by design", source)
        self.assertIn("gates-of-codex.live-workshop-backup", source)
        self.assertIn("Get-ChildItem -LiteralPath $Target -Force | ForEach-Object", source)
        self.assertIn("Copy-Item -LiteralPath $_.FullName -Destination $backupDirectory", source)
        self.assertIn("Get-ChildItem -LiteralPath $Target -Force | Remove-Item -Recurse -Force", source)
        self.assertIn("git.Source -C $Source ls-files -- mod.info resource localizations", source)
        self.assertIn("Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256", source)
        self.assertIn("Get-FileHash -LiteralPath $destination -Algorithm SHA256", source)
        self.assertIn('deployment_kind = "owner_native_live_workshop"', source)
        self.assertIn("source_commit = $commit", source)
        self.assertIn("Unexpected files remain in authoritative live Workshop target", source)

    def test_live_deploy_does_not_copy_repository_only_surfaces(self) -> None:
        source = (ROOT / "tools/deploy_workshop_live.ps1").read_text(encoding="utf-8")

        self.assertIn('$RuntimeRoots = @("mod.info", "resource", "localizations")', source)
        self.assertNotIn("ls-files -- docs", source)
        self.assertNotIn("ls-files -- tests", source)
        self.assertNotIn("ls-files -- godot", source)

    def test_restore_requires_matching_backup_identity_and_explicit_mutation(self) -> None:
        source = (ROOT / "tools/restore_workshop_live.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$AcceptWorkshopMutation", source)
        self.assertIn('metadata.schema -ne "gates-of-codex.live-workshop-backup"', source)
        self.assertIn("Backup belongs to", source)
        self.assertIn("Get-ChildItem -LiteralPath $Target -Force | Remove-Item -Recurse -Force", source)
        self.assertIn("Copy-Item -LiteralPath $_.FullName -Destination $Target", source)

    def test_native_acceptance_must_not_use_disposable_gates_layer_for_goh(self) -> None:
        stack = (ROOT / "config/mod-stack.windows.json").read_text(encoding="utf-8")
        deploy = (ROOT / "tools/deploy_workshop_live.ps1").read_text(encoding="utf-8")

        self.assertIn("${GATES_CODEX_ROOT}", stack)
        self.assertIn("TargetRoot", deploy)
        self.assertIn("owner_native_live_workshop", deploy)


if __name__ == "__main__":
    unittest.main()
