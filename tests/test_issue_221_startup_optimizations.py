from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import fast_entrypoint, persistent_backend, startup_cold_optimizations


ROOT = Path(__file__).resolve().parents[1]


class StartupReuseAuthorityTests(unittest.TestCase):
    def test_daemon_startup_reuse_requires_exact_untouched_files_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            campaign_fingerprint = persistent_backend._fingerprint(campaign)
            snapshot_fingerprint = persistent_backend._fingerprint(snapshot)
            state = types.SimpleNamespace(
                map_metadata={
                    "scenario_id": "earth3_v1",
                    "stack_config": "stack.json",
                    "preferred_map": "map",
                    "resource_stack": ["vanilla", "codex"],
                    "player_launch": {},
                },
                map_id="earth3_europe_mediterranean",
                selected_faction=types.SimpleNamespace(value="nato"),
                difficulty="normal",
                fog_of_war_enabled=False,
                turn_number=1,
                game_directory="game",
                profile_directory="profile",
                code_x_directory="codex",
            )

            response = persistent_backend._startup_reuse_response(
                cached_state=state,
                cached_fingerprint=campaign_fingerprint,
                startup_campaign_fingerprint=campaign_fingerprint,
                startup_snapshot_fingerprint=snapshot_fingerprint,
                campaign=campaign,
                snapshot=snapshot,
            )
            self.assertTrue(response["ok"])

            snapshot.write_text('{"snapshot":2}\n', encoding="utf-8")
            changed = persistent_backend._startup_reuse_response(
                cached_state=state,
                cached_fingerprint=campaign_fingerprint,
                startup_campaign_fingerprint=campaign_fingerprint,
                startup_snapshot_fingerprint=snapshot_fingerprint,
                campaign=campaign,
                snapshot=snapshot,
            )
            self.assertFalse(changed["ok"])
            self.assertEqual("snapshot_changed_since_startup", changed["reason"])

            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            advanced = persistent_backend._startup_reuse_response(
                cached_state=state,
                cached_fingerprint=(0, 0, "f" * 64),
                startup_campaign_fingerprint=campaign_fingerprint,
                startup_snapshot_fingerprint=snapshot_fingerprint,
                campaign=campaign,
                snapshot=snapshot,
            )
            self.assertFalse(advanced["ok"])
            self.assertEqual("daemon_state_advanced_since_startup", advanced["reason"])

    def test_fast_continue_compatibility_rejects_any_launch_setting_change(self) -> None:
        paths = types.SimpleNamespace(
            campaign=Path("campaign.json"),
            snapshot=Path("campaign_snapshot.json"),
            commands=Path("frontend_commands.json"),
        )
        args = types.SimpleNamespace(
            faction=None,
            difficulty=None,
            fog_of_war=None,
            tactical_map=None,
        )
        shell = types.SimpleNamespace(
            _codex_layer_from_stack=lambda _layers: "codex",
        )
        state = {
            "selected_faction": "nato",
            "difficulty": "normal",
            "fog_of_war": "off",
            "game_directory": "game",
            "profile_directory": "profile",
            "tactical_map": "map",
            "stack_config": "stack.json",
            "resource_stack": ["vanilla", "codex"],
            "code_x_directory": "codex",
            "player_launch": {
                "campaign_path": str(paths.campaign),
                "snapshot_path": str(paths.snapshot),
                "commands_path": str(paths.commands),
                "godot_executable": "godot",
                "godot_project": "project",
            },
        }
        self.assertTrue(
            fast_entrypoint._fast_continue_state_compatible(
                shell,
                args,
                state,
                paths=paths,
                stack_layers=["vanilla", "codex"],
                stack_config="stack.json",
                game_directory="game",
                profile_directory="profile",
                godot_executable="godot",
                godot_project="project",
            )
        )
        args.difficulty = "hard"
        self.assertFalse(
            fast_entrypoint._fast_continue_state_compatible(
                shell,
                args,
                state,
                paths=paths,
                stack_layers=["vanilla", "codex"],
                stack_config="stack.json",
                game_directory="game",
                profile_directory="profile",
                godot_executable="godot",
                godot_project="project",
            )
        )


class FullStartupShortcutTests(unittest.TestCase):
    def test_snapshot_cache_requires_exact_campaign_and_snapshot_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            context = {
                "schema": startup_cold_optimizations.SNAPSHOT_CACHE_SCHEMA,
                "schema_version": startup_cold_optimizations.SNAPSHOT_CACHE_VERSION,
                "source_commit": "a" * 40,
                "runtime_executable": {
                    "path": "runtime",
                    "size": 1,
                    "sha256": "b" * 64,
                },
                "managed_home": str(root),
                "campaign_path": str(campaign.resolve()),
                "snapshot_path": str(snapshot.resolve()),
                "maintenance_signature": "c" * 64,
            }
            with patch.object(
                startup_cold_optimizations,
                "_snapshot_context",
                return_value=context,
            ):
                self.assertTrue(
                    startup_cold_optimizations._write_snapshot_cache(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
                self.assertTrue(
                    startup_cold_optimizations._snapshot_cache_valid(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
                campaign.write_text('{"turn":2}\n', encoding="utf-8")
                self.assertFalse(
                    startup_cold_optimizations._snapshot_cache_valid(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )

    def test_backend_start_is_nonblocking_and_does_not_sleep(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            snapshot.write_text("{}\n", encoding="utf-8")
            fake = types.SimpleNamespace(
                _runtime_source_commit=lambda: "d" * 40,
                _drop_session_descriptor=lambda _campaign: None,
                _ping=lambda _campaign: False,
            )
            startup_cold_optimizations._BACKEND_STARTING.clear()
            with (
                patch.object(startup_cold_optimizations.subprocess, "Popen") as popen,
                patch.object(startup_cold_optimizations.time, "sleep") as sleep,
            ):
                ready = startup_cold_optimizations._begin_backend_session_nonblocking(
                    fake,
                    campaign,
                    snapshot,
                )
            self.assertFalse(ready)
            popen.assert_called_once()
            sleep.assert_not_called()

    def test_import_stamp_is_ignored_if_godot_class_cache_was_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            original = lambda _project: {"schema": "valid"}
            fake_entrypoint = types.SimpleNamespace(
                _read_godot_import_stamp=original,
            )
            startup_cold_optimizations._install_import_cache_guard(fake_entrypoint)
            self.assertIsNone(fake_entrypoint._read_godot_import_stamp(project))

            class_cache = project / ".godot" / "global_script_class_cache.cfg"
            class_cache.parent.mkdir()
            class_cache.write_text("cache\n", encoding="utf-8")
            self.assertEqual(
                {"schema": "valid"},
                fake_entrypoint._read_godot_import_stamp(project),
            )

    def test_packaged_runner_installs_full_startup_shortcuts(self) -> None:
        source = (ROOT / "run_gates_of_codex.py").read_text(encoding="utf-8")
        self.assertIn("install_packaged_full_startup_shortcuts", source)
        self.assertLess(
            source.index("install_packaged_full_startup_shortcuts()"),
            source.index("raise SystemExit(player_main())"),
        )


if __name__ == "__main__":
    unittest.main()
