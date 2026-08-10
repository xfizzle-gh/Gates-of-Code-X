from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_gitignore_covers_runtime_paths(self) -> None:
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for token in (
            "live/",
            "godot/campaign_snapshot.json",
            "godot/frontend_commands.json",
            "godot/.godot/",
            "backups/",
        ):
            self.assertIn(token, text)

    def test_runtime_paths_are_not_tracked(self) -> None:
        tracked = subprocess.check_output(
            ["git", "ls-files", "live", "godot/campaign_snapshot.json", "godot/frontend_commands.json"],
            cwd=ROOT,
            text=True,
        ).strip()
        self.assertEqual("", tracked)

    def test_no_runtime_json_is_tracked_at_the_godot_project_root(self) -> None:
        """Generic guard for generated queue/snapshot artifacts.

        The enumerated check above only knows the names it was given, so a
        runtime queue written under a different name (``godot/commands.json``)
        was once committed while that test stayed green. Authored Godot JSON
        lives under ``assets/`` or ``fixtures/``; nothing belongs at the project
        root, so anything appearing there is generated output.
        """
        tracked = subprocess.check_output(
            ["git", "ls-files", "godot/*.json"], cwd=ROOT, text=True
        ).split()
        at_root = [path for path in tracked if path.count("/") == 1]
        self.assertEqual([], at_root)

    def test_deployment_scripts_do_not_default_to_unrelated_workshop_item(self) -> None:
        for relative in (
            "tools/deploy_workshop_test.ps1",
            "tools/install_gates_of_codex.ps1",
        ):
            body = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("3700832981", body)
            self.assertIn("GATES_CODEX_DEPLOY_ROOT", body)

    def test_hygiene_doc_present(self) -> None:
        path = ROOT / "docs/repository-hygiene.md"
        self.assertTrue(path.is_file())
        body = path.read_text(encoding="utf-8")
        self.assertIn("live/", body)
        self.assertIn("campaign_snapshot.json", body)


if __name__ == "__main__":
    unittest.main()
