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

    def test_hygiene_doc_present(self) -> None:
        path = ROOT / "docs/repository-hygiene.md"
        self.assertTrue(path.is_file())
        body = path.read_text(encoding="utf-8")
        self.assertIn("live/", body)
        self.assertIn("campaign_snapshot.json", body)


if __name__ == "__main__":
    unittest.main()
