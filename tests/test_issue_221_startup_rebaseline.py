from __future__ import annotations

import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gates_of_codex import persistent_backend, startup_rebaseline


ROOT = Path(__file__).resolve().parents[1]


class StartupRebaselineTests(unittest.TestCase):
    def test_rebaseline_marker_requires_exact_campaign_and_snapshot_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")

            with (
                patch.dict(
                    os.environ,
                    {"GATES_OF_CODEX_HOME": str(root / "home")},
                ),
                patch.object(
                    persistent_backend,
                    "_runtime_source_commit",
                    return_value="a" * 40,
                ),
                patch.object(
                    startup_rebaseline,
                    "_current_maintenance_signature",
                    return_value="maintenance-a",
                ),
            ):
                marker = startup_rebaseline._marker_path(campaign, snapshot)
                self.assertNotEqual(campaign.parent, marker.parent)
                self.assertTrue(
                    startup_rebaseline._write_rebaseline_marker(
                        persistent_backend,
                        campaign,
                        snapshot,
                    )
                )
                self.assertEqual(
                    {"campaign.json", "campaign_snapshot.json"},
                    {child.name for child in root.iterdir() if child.is_file()},
                )
                self.assertTrue(
                    startup_rebaseline._rebaseline_marker_matches(
                        persistent_backend,
                        campaign,
                        snapshot,
                    )
                )
                campaign.write_text('{"turn":2}\n', encoding="utf-8")
                self.assertFalse(
                    startup_rebaseline._rebaseline_marker_matches(
                        persistent_backend,
                        campaign,
                        snapshot,
                    )
                )

    def test_validated_rebaseline_allows_current_daemon_state_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":2}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":2}\n', encoding="utf-8")
            state = types.SimpleNamespace(
                map_metadata={
                    "scenario_id": "earth3_v1",
                    "resource_stack": [],
                    "player_launch": {},
                },
                map_id="earth3_europe_mediterranean",
                selected_faction=types.SimpleNamespace(value="nato"),
                difficulty="normal",
                fog_of_war_enabled=False,
                turn_number=2,
                game_directory="",
                profile_directory="",
                code_x_directory="",
            )
            rejected = {
                "handled": True,
                "exit_code": 0,
                "ok": False,
                "reason": "daemon_state_advanced_since_startup",
            }

            with (
                patch.dict(
                    os.environ,
                    {"GATES_OF_CODEX_HOME": str(root / "home")},
                ),
                patch.object(
                    persistent_backend,
                    "_runtime_source_commit",
                    return_value="b" * 40,
                ),
                patch.object(
                    startup_rebaseline,
                    "_current_maintenance_signature",
                    return_value="maintenance-b",
                ),
            ):
                self.assertTrue(
                    startup_rebaseline._write_rebaseline_marker(
                        persistent_backend,
                        campaign,
                        snapshot,
                    )
                )
                current = persistent_backend._fingerprint(campaign)
                accepted = startup_rebaseline._rebaseline_response_if_safe(
                    persistent_backend,
                    rejected,
                    cached_state=state,
                    cached_fingerprint=current,
                    campaign=campaign,
                    snapshot=snapshot,
                )
                self.assertTrue(accepted["ok"])
                self.assertTrue(accepted["rebaseline"])
                self.assertEqual(2, accepted["state"]["turn_number"])

                snapshot.write_text('{"snapshot":"stale"}\n', encoding="utf-8")
                refused = startup_rebaseline._rebaseline_response_if_safe(
                    persistent_backend,
                    rejected,
                    cached_state=state,
                    cached_fingerprint=current,
                    campaign=campaign,
                    snapshot=snapshot,
                )
                self.assertFalse(refused["ok"])

    def test_maintenance_change_invalidates_warm_reuse_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")

            with (
                patch.dict(
                    os.environ,
                    {"GATES_OF_CODEX_HOME": str(root / "home")},
                ),
                patch.object(
                    persistent_backend,
                    "_runtime_source_commit",
                    return_value="c" * 40,
                ),
                patch.object(
                    startup_rebaseline,
                    "_current_maintenance_signature",
                    return_value="maintenance-before",
                ),
            ):
                self.assertTrue(
                    startup_rebaseline._write_rebaseline_marker(
                        persistent_backend,
                        campaign,
                        snapshot,
                    )
                )
                self.assertTrue(
                    startup_rebaseline._marker_metadata_matches(
                        persistent_backend,
                        campaign,
                        snapshot,
                    )
                )

            with (
                patch.dict(
                    os.environ,
                    {"GATES_OF_CODEX_HOME": str(root / "home")},
                ),
                patch.object(
                    persistent_backend,
                    "_runtime_source_commit",
                    return_value="c" * 40,
                ),
                patch.object(
                    startup_rebaseline,
                    "_current_maintenance_signature",
                    return_value="maintenance-after",
                ),
            ):
                self.assertFalse(
                    startup_rebaseline._marker_metadata_matches(
                        persistent_backend,
                        campaign,
                        snapshot,
                    )
                )

    def test_probe_guard_refuses_daemon_state_when_maintenance_is_stale(self) -> None:
        fake_backend = types.SimpleNamespace(
            diagnose_startup_reuse=lambda _campaign, _snapshot: (
                {"turn_number": 1},
                "ok",
            ),
        )
        startup_rebaseline._install_probe_maintenance_guard(fake_backend)
        with patch.object(
            startup_rebaseline,
            "_marker_metadata_matches",
            return_value=False,
        ):
            state, reason = fake_backend.diagnose_startup_reuse(
                Path("campaign.json"),
                Path("campaign_snapshot.json"),
            )
            self.assertIsNone(state)
            self.assertEqual("maintenance_mismatch", reason)
            self.assertIsNone(
                fake_backend.probe_startup_reuse(
                    Path("campaign.json"),
                    Path("campaign_snapshot.json"),
                )
            )

    def test_pre_s11_continue_preserves_canonical_migration_save(self) -> None:
        from gates_of_codex import state_io

        for incoming_schema, expected_saves in ((10, 1), (11, 0)):
            with self.subTest(incoming_schema=incoming_schema):
                fake_state = object()
                paths = types.SimpleNamespace(campaign=Path("campaign.json"))

                def fake_continue(*, paths):
                    del paths
                    return state_io.campaign_from_dict(
                        {"schema_version": incoming_schema}
                    )

                fake_shell = types.SimpleNamespace(continue_campaign=fake_continue)
                startup_rebaseline._install_canonical_migration_save_guard(fake_shell)
                fake_from_dict = Mock(return_value=fake_state)
                with (
                    patch.object(state_io, "campaign_from_dict", fake_from_dict),
                    patch.object(state_io, "save_campaign") as save_campaign,
                ):
                    result = fake_shell.continue_campaign(paths=paths)
                self.assertIs(fake_state, result)
                self.assertEqual(expected_saves, save_campaign.call_count)
                if expected_saves:
                    save_campaign.assert_called_once_with(fake_state, paths.campaign)

    def test_both_packaged_runners_install_rebaseline_contract(self) -> None:
        player = (ROOT / "run_gates_of_codex.py").read_text(encoding="utf-8")
        live = (ROOT / "run_gates_of_codex_live.py").read_text(encoding="utf-8")
        self.assertIn("install_startup_rebaseline_contracts()", player)
        self.assertIn("install_startup_rebaseline_contracts()", live)
        self.assertLess(
            player.index("install_startup_rebaseline_contracts()"),
            player.index("raise SystemExit(player_main())"),
        )
        self.assertLess(
            live.index("install_startup_rebaseline_contracts()"),
            live.index("from gates_of_codex.fast_entrypoint import main as application_main"),
        )


if __name__ == "__main__":
    unittest.main()
