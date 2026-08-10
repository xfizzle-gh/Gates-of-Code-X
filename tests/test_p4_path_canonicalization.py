from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.player_shell import (
    PLAYER_LAUNCH_KEY,
    build_play_parser,
    read_last_campaign,
    resolve_campaign_paths,
    run_play,
)
from gates_of_codex.state_io import load_campaign


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

    def test_launcher_and_snapshot_agree_on_one_campaign_identity(self) -> None:
        """The defect was a split between components, not a broken helper.

        ``resolve_campaign_paths`` canonicalizing correctly is necessary but not
        sufficient: the reported campaign path, the persisted launch settings,
        the remembered-campaign pointer, and the snapshot's control/application
        blocks must all name the campaign identically. A regression in any one
        of those consumers reintroduces the two-identity split that Windows 8.3
        aliases exposed, while a helper-only test would stay green.
        """
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

            environ = dict(os.environ)
            environ["GATES_OF_CODEX_HOME"] = str(root / "home")
            created = run_play(
                build_play_parser().parse_args(
                    [
                        "--new",
                        "--campaign",
                        str(alias / "campaign"),
                        "--no-launch",
                        "--scenario",
                        "legacy_goe_europe",
                    ]
                ),
                environ=environ,
            )
            snapshot = json.loads(
                Path(created.snapshot_path).read_text(encoding="utf-8")
            )
            state = load_campaign(created.campaign_path)
            remembered = read_last_campaign(environ)

            identity = created.campaign_path
            self.assertEqual(identity, snapshot["control"]["campaign_path"])
            self.assertEqual(identity, snapshot["application"]["campaign_path"])
            self.assertEqual(
                identity, state.map_metadata[PLAYER_LAUNCH_KEY]["campaign_path"]
            )
            self.assertEqual(identity, str(remembered))
            self.assertIn(identity, snapshot["control"]["play"]["continue_args"])
            # The alias must not survive anywhere as the campaign identity.
            self.assertNotIn(f"{os.sep}alias{os.sep}", identity)
            self.assertEqual(
                str(real_root.resolve()), str(Path(identity).parent.parent)
            )


if __name__ == "__main__":
    unittest.main()
