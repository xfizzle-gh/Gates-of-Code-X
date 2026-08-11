"""P6 automated golden-path integration through production seams."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import replace as dc_replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))


class P6GoldenPathTests(unittest.TestCase):
    def test_verify_import_exactly_once_and_continuation(self) -> None:
        """Production verify/import path + exactly-once + reload continuation."""
        from gates_of_codex.frontend_commands import apply_frontend_commands
        from gates_of_codex.service import GatesOfCodeXService
        from gates_of_codex.state_io import load_campaign
        from gates_of_codex.turn_cycle import install_frontend_turn_cycle_op
        from test_s10_frontend_presentation_contract import (
            _create_prepared_contact,
            _state,
            _write_completed_external_battle,
        )

        install_frontend_turn_cycle_op()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            _create_prepared_contact(state)
            campaign_path, save_path = _write_completed_external_battle(root, state)

            verified = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "verify_result", "command_id": "p6-verify"}],
                snapshot_path=None,
            )
            self.assertTrue(verified["ok"], verified)
            self.assertTrue(verified["results"][0]["data"].get("verified"), verified)

            imported = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle", "command_id": "p6-import"}],
                snapshot_path=None,
            )
            self.assertTrue(imported["ok"], imported)
            after = load_campaign(campaign_path)
            self.assertIsNone(after.pending_battle)

            replay = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle", "command_id": "p6-import"}],
                snapshot_path=None,
            )
            self.assertTrue(replay["ok"], replay)
            detail = replay["results"][0].get("detail", "")
            data = replay["results"][0].get("data") or {}
            self.assertTrue(data.get("duplicate") or "duplicate" in detail, replay)

            reloaded = load_campaign(campaign_path)
            self.assertIsNone(reloaded.pending_battle)
            refreshed = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "refresh", "command_id": "p6-refresh"}],
                snapshot_path=None,
            )
            self.assertTrue(refreshed["ok"], refreshed)

            # Failed verification cannot import.
            fail_root = root / "fail"
            fail_root.mkdir()
            fail_state = _state(fail_root)
            _create_prepared_contact(fail_state)
            fail_campaign, fail_save = _write_completed_external_battle(
                fail_root, fail_state
            )
            service = GatesOfCodeXService()
            sidecar = service.manifest_path(fail_save)
            manifest = service.load_manifest(sidecar)
            service.write_manifest(
                dc_replace(manifest, battle_id="not-the-pending-id"), sidecar
            )
            blocked = apply_frontend_commands(
                fail_campaign,
                commands=[{"op": "import_battle", "command_id": "p6-block"}],
                snapshot_path=None,
            )
            self.assertFalse(blocked["ok"], blocked)
            self.assertIsNotNone(load_campaign(fail_campaign).pending_battle)

    def test_snapshot_carries_package_provenance_not_campaign_authority(self) -> None:
        from gates_of_codex.frontend import build_frontend_snapshot
        from gates_of_codex.state_io import save_campaign
        from test_s10_frontend_presentation_contract import _state

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {
                **os.environ,
                "GATES_OF_CODEX_SOURCE_COMMIT": "e" * 40,
            }
            with mock.patch.dict(os.environ, env, clear=False):
                state = _state(root)
                campaign = root / "campaign.json"
                snapshot_path = root / "campaign_snapshot.json"
                save_campaign(state, campaign)
                snapshot = build_frontend_snapshot(
                    state,
                    campaign_path=campaign,
                    snapshot_path=snapshot_path,
                )
                application = snapshot["application"]
                self.assertEqual("e" * 40, application.get("source_commit"))
                self.assertEqual(("e" * 40)[:12], application.get("source_commit_short"))
                self.assertTrue(str(application.get("version") or ""))
                self.assertEqual(
                    Path(application["campaign_path"]).resolve(),
                    campaign.resolve(),
                )
                self.assertNotEqual(snapshot_path.resolve(), campaign.resolve())

    def test_end_player_round_is_registered_for_golden_path(self) -> None:
        from gates_of_codex.frontend_commands import apply_frontend_commands
        from gates_of_codex.turn_cycle import PLAYER_ROUND_OP, install_frontend_turn_cycle_op
        from test_s10_frontend_presentation_contract import _state
        from gates_of_codex.state_io import save_campaign

        install_frontend_turn_cycle_op()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            campaign = root / "campaign.json"
            save_campaign(state, campaign)
            # No pending battle on the S10 fixture opening state; round may advance.
            result = apply_frontend_commands(
                campaign,
                commands=[{"op": PLAYER_ROUND_OP, "command_id": "p6-round"}],
                snapshot_path=None,
            )
            # Either completes or fails closed for fixture-specific reasons; the op
            # must be recognized (not "unknown").
            self.assertEqual(PLAYER_ROUND_OP, result["results"][0]["op"])
            self.assertNotIn("unknown", result["results"][0].get("detail", "").lower())

    def test_continue_reopens_exact_campaign_path(self) -> None:
        from gates_of_codex.player_shell import (
            continue_campaign,
            resolve_campaign_paths,
            write_last_campaign,
            read_last_campaign,
            CampaignPaths,
            CAMPAIGN_FILE_NAME,
            SNAPSHOT_FILE_NAME,
            COMMANDS_FILE_NAME,
        )
        from gates_of_codex.state_io import save_campaign, load_campaign
        from test_s10_frontend_presentation_contract import _state

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir()
            env = {
                **os.environ,
                "GATES_OF_CODEX_HOME": str(home),
                "LOCALAPPDATA": str(Path(temporary)),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                root = home / "campaigns" / "earth3_v1"
                root.mkdir(parents=True, exist_ok=True)
                paths = CampaignPaths(
                    root=root,
                    campaign=root / CAMPAIGN_FILE_NAME,
                    snapshot=root / SNAPSHOT_FILE_NAME,
                    commands=root / COMMANDS_FILE_NAME,
                )
                state = _state(root)
                save_campaign(state, paths.campaign)
                write_last_campaign(paths.campaign, environ=env)
                remembered = read_last_campaign(environ=env)
                self.assertEqual(paths.campaign.resolve(), remembered.resolve())
                continued = continue_campaign(paths=paths)
                self.assertEqual(load_campaign(paths.campaign).map_id, continued.map_id)


if __name__ == "__main__":
    unittest.main()
