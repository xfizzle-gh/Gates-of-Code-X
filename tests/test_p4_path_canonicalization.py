from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.player_shell import resolve_campaign_paths


class CampaignPathCanonicalizationTests(unittest.TestCase):
    def test_existing_alias_parent_canonicalizes_before_identity_is_persisted(self) -> None:
        """POSIX symlinks exercise the same identity split as Windows 8.3 aliases."""
        if os.name == "nt":
            self.skipTest("Windows 8.3 canonicalization is exercised by native CI")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_root = root / "real campaigns"
            real_root.mkdir()
            alias = root / "alias"
            try:
                alias.symlink_to(real_root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            paths = resolve_campaign_paths(alias / "campaign")
            expected_root = (real_root / "campaign").resolve()

        self.assertEqual(expected_root, paths.root)
        self.assertEqual(expected_root / "campaign.json", paths.campaign)
        self.assertEqual(expected_root / "campaign_snapshot.json", paths.snapshot)
        self.assertEqual(expected_root / "frontend_commands.json", paths.commands)


if __name__ == "__main__":
    unittest.main()
