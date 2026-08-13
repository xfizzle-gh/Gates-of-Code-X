from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import (
    fast_entrypoint,
    persistent_backend,
    player_shell,
    startup_cold_optimizations,
)


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
            restored_snapshot_fingerprint = persistent_backend._fingerprint(snapshot)
            advanced = persistent_backend._startup_reuse_response(
                cached_state=state,
                cached_fingerprint=(0, 0, "f" * 64),
                startup_campaign_fingerprint=campaign_fingerprint,
                startup_snapshot_fingerprint=restored_snapshot_fingerprint,
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
            home = root / "home"
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
                "managed_home": str(home.resolve()),
                "campaign_path": str(campaign.resolve()),
                "snapshot_path": str(snapshot.resolve()),
                "maintenance_signature": "c" * 64,
            }
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_source_commit",
                    return_value="a" * 40,
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_snapshot_context",
                    return_value=context,
                ),
            ):
                self.assertTrue(
                    startup_cold_optimizations._write_snapshot_cache(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
                self.assertEqual(
                    {"campaign.json", "campaign_snapshot.json"},
                    {child.name for child in root.iterdir() if child.is_file()},
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

    def test_missing_cache_does_not_hash_campaign_or_snapshot_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_sha256_file",
                    side_effect=AssertionError("cache miss must not hash"),
                ),
            ):
                self.assertFalse(
                    startup_cold_optimizations._snapshot_cache_valid(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )

    def test_campaign_size_mismatch_does_not_hash_executable_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            hashed: list[Path] = []
            original = startup_cold_optimizations._sha256_file

            def track(path: Path) -> str:
                hashed.append(Path(path).expanduser().resolve(strict=False))
                return original(path)

            context = {
                "schema": startup_cold_optimizations.SNAPSHOT_CACHE_SCHEMA,
                "schema_version": startup_cold_optimizations.SNAPSHOT_CACHE_VERSION,
                "source_commit": "a" * 40,
                "runtime_executable": {
                    "path": "runtime",
                    "size": 1,
                    "sha256": "b" * 64,
                },
                "managed_home": str(home.resolve()),
                "campaign_path": str(campaign.resolve()),
                "snapshot_path": str(snapshot.resolve()),
                "maintenance_signature": "c" * 64,
            }
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_snapshot_context",
                    return_value=context,
                ),
            ):
                self.assertTrue(
                    startup_cold_optimizations._write_snapshot_cache(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
            campaign.write_text('{"turn":10}\n', encoding="utf-8")
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_source_commit",
                    return_value="a" * 40,
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_sha256_file",
                    side_effect=track,
                ),
            ):
                self.assertFalse(
                    startup_cold_optimizations._snapshot_cache_valid(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
            self.assertEqual([], hashed)

    def test_cache_metadata_write_does_not_block_the_caller(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def blocking_write(*_args, **_kwargs) -> bool:
            started.set()
            self.assertTrue(release.wait(timeout=2.0))
            return True

        with patch.object(
            startup_cold_optimizations,
            "_write_snapshot_cache",
            blocking_write,
        ):
            begun = time.perf_counter()
            startup_cold_optimizations._schedule_snapshot_cache_write(
                Path("campaign.json"),
                Path("campaign_snapshot.json"),
                environ=None,
                campaign_identity={"path": "campaign.json", "size": 1, "sha256": "a" * 64},
                snapshot_identity={"path": "campaign_snapshot.json", "size": 1, "sha256": "b" * 64},
            )
            waited = (time.perf_counter() - begun) * 1000.0
        self.assertLess(waited, 200.0)
        self.assertTrue(started.wait(timeout=2.0))
        release.set()
        for thread in list(startup_cold_optimizations._CACHE_WRITE_THREADS):
            thread.join(timeout=2.0)

    def test_async_cache_write_does_not_bless_post_publish_campaign_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            original_campaign = b'{"turn":1}\n'
            mutated_campaign = b'{"turn":2}\n'
            snapshot_bytes = b'{"snapshot":1}\n'
            campaign.write_bytes(original_campaign)
            snapshot.write_bytes(snapshot_bytes)
            published_campaign = startup_cold_optimizations._file_identity(campaign)
            published_snapshot = startup_cold_optimizations._file_identity(snapshot)
            original_atomic = startup_cold_optimizations._atomic_json
            started = threading.Event()
            release = threading.Event()

            def paused_atomic(path, payload):
                started.set()
                self.assertTrue(release.wait(timeout=2.0))
                return original_atomic(path, payload)

            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_source_commit",
                    return_value="a" * 40,
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_maintenance_signature",
                    return_value="c" * 64,
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_atomic_json",
                    paused_atomic,
                ),
            ):
                startup_cold_optimizations._schedule_snapshot_cache_write(
                    campaign,
                    snapshot,
                    environ=None,
                    campaign_identity=published_campaign,
                    snapshot_identity=published_snapshot,
                )
                self.assertTrue(started.wait(timeout=2.0))
                campaign.write_bytes(mutated_campaign)
                self.assertEqual(len(original_campaign), len(mutated_campaign))
                release.set()
                for thread in list(startup_cold_optimizations._CACHE_WRITE_THREADS):
                    thread.join(timeout=2.0)

            with patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}):
                cache = startup_cold_optimizations._snapshot_cache_path(
                    campaign,
                    snapshot,
                    environ=None,
                )
                if cache.is_file():
                    payload = json.loads(cache.read_text(encoding="utf-8"))
                    mutated_digest = hashlib.sha256(mutated_campaign).hexdigest()
                    self.assertNotEqual(
                        mutated_digest,
                        payload.get("campaign", {}).get("sha256"),
                    )
                with (
                    patch.object(
                        startup_cold_optimizations,
                        "_source_commit",
                        return_value="a" * 40,
                    ),
                    patch.object(
                        startup_cold_optimizations,
                        "_maintenance_signature",
                        return_value="c" * 64,
                    ),
                ):
                    self.assertFalse(
                        startup_cold_optimizations._snapshot_cache_valid(
                            campaign,
                            snapshot,
                            environ=None,
                        )
                    )

    def test_same_size_snapshot_byte_change_invalidates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
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
                "managed_home": str(home.resolve()),
                "campaign_path": str(campaign.resolve()),
                "snapshot_path": str(snapshot.resolve()),
                "maintenance_signature": "c" * 64,
            }
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_source_commit",
                    return_value="a" * 40,
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_snapshot_context",
                    return_value=context,
                ),
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
                snapshot.write_text('{"snapshot":2}\n', encoding="utf-8")
                self.assertEqual(
                    len('{"snapshot":1}\n'),
                    len(snapshot.read_text(encoding="utf-8")),
                )
                self.assertFalse(
                    startup_cold_optimizations._snapshot_cache_valid(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )

    def test_same_size_different_executable_bytes_invalidate_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            fake_exe = root / "GatesOfCodeX.exe"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            fake_exe.write_bytes(b"AAAA")
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_source_commit",
                    return_value="d" * 40,
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_maintenance_signature",
                    return_value="e" * 64,
                ),
                patch.object(
                    startup_cold_optimizations.sys,
                    "executable",
                    str(fake_exe),
                ),
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
                fake_exe.write_bytes(b"BBBB")
                self.assertEqual(4, fake_exe.stat().st_size)
                self.assertFalse(
                    startup_cold_optimizations._snapshot_cache_valid(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )

    def test_corrupt_or_incomplete_cache_metadata_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
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
                "managed_home": str(home),
                "campaign_path": str(campaign.resolve()),
                "snapshot_path": str(snapshot.resolve()),
                "maintenance_signature": "c" * 64,
            }
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_snapshot_context",
                    return_value=context,
                ),
            ):
                self.assertTrue(
                    startup_cold_optimizations._write_snapshot_cache(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
                cache = startup_cold_optimizations._snapshot_cache_path(
                    campaign,
                    snapshot,
                    environ=None,
                )
                payload = json.loads(cache.read_text(encoding="utf-8"))
                del payload["snapshot"]
                cache.write_text(json.dumps(payload), encoding="utf-8")
                self.assertFalse(
                    startup_cold_optimizations._snapshot_cache_valid(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
                cache.write_text("{not-json", encoding="utf-8")
                self.assertFalse(
                    startup_cold_optimizations._snapshot_cache_valid(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )

    def test_legacy_campaign_tree_cache_is_removed_on_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            leftover = root / startup_cold_optimizations.SNAPSHOT_CACHE_FILE_NAME
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            leftover.write_text("{}\n", encoding="utf-8")
            context = {
                "schema": startup_cold_optimizations.SNAPSHOT_CACHE_SCHEMA,
                "schema_version": startup_cold_optimizations.SNAPSHOT_CACHE_VERSION,
                "source_commit": "a" * 40,
                "runtime_executable": {
                    "path": "runtime",
                    "size": 1,
                    "sha256": "b" * 64,
                },
                "managed_home": str(home),
                "campaign_path": str(campaign.resolve()),
                "snapshot_path": str(snapshot.resolve()),
                "maintenance_signature": "c" * 64,
            }
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_snapshot_context",
                    return_value=context,
                ),
            ):
                self.assertTrue(
                    startup_cold_optimizations._write_snapshot_cache(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
            self.assertFalse(leftover.exists())

    def test_cache_miss_emits_split_snapshot_phases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "GATES_OF_CODEX_HOME": str(home),
                        fast_entrypoint.STARTUP_TELEMETRY_ENV: "1",
                        fast_entrypoint.STARTUP_EPOCH_ENV: "1000.000",
                    },
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_source_commit",
                    return_value="a" * 40,
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_maintenance_signature",
                    return_value="c" * 64,
                ),
                redirect_stdout(output),
            ):
                self.assertTrue(
                    startup_cold_optimizations._write_snapshot_cache(
                        campaign,
                        snapshot,
                        environ=None,
                    )
                )
            stages = []
            methods = []
            for line in output.getvalue().splitlines():
                if not line.startswith("GOC_STARTUP "):
                    continue
                payload = json.loads(line.split(" ", 1)[1])
                stages.append(payload["stage"])
                if payload["stage"] == "frontend_snapshot_executable_identity":
                    methods.append(payload.get("method"))
            self.assertEqual(
                [
                    "frontend_snapshot_executable_identity",
                    "frontend_snapshot_maintenance_signature",
                    "frontend_snapshot_campaign_hash",
                    "frontend_snapshot_snapshot_hash",
                    "frontend_snapshot_cache_publish",
                ],
                stages,
            )
            self.assertEqual(["sha256"], methods)

    def test_publish_snapshot_uses_installed_frontend_writer(self) -> None:
        source = (ROOT / "src/gates_of_codex/player_shell.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("frontend.write_frontend_snapshot(", source)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            campaign.write_text("{}\n", encoding="utf-8")
            called: list[Path] = []

            def fake_writer(state, path, *, campaign_path=None, environ=None):
                called.append(Path(path))
                Path(path).write_text('{"schema":"fast"}\n', encoding="utf-8")
                return Path(path)

            paths = types.SimpleNamespace(
                campaign=campaign,
                snapshot=snapshot,
                commands=commands,
            )
            with patch(
                "gates_of_codex.frontend.write_frontend_snapshot",
                fake_writer,
            ):
                written = player_shell.publish_snapshot(
                    object(),
                    paths,
                    environ=None,
                )
            self.assertEqual(snapshot, written)
            self.assertEqual([snapshot], called)
            self.assertEqual(
                {"commands": []},
                json.loads(commands.read_text(encoding="utf-8")),
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


    def test_write_cache_refuses_when_captured_pair_no_longer_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text('{"turn":1}\n', encoding="utf-8")
            snapshot.write_text('{"snapshot":1}\n', encoding="utf-8")
            captured_campaign = startup_cold_optimizations._file_identity(campaign)
            captured_snapshot = startup_cold_optimizations._file_identity(snapshot)
            campaign.write_text('{"turn":2}\n', encoding="utf-8")
            with (
                patch.dict(os.environ, {"GATES_OF_CODEX_HOME": str(home)}),
                patch.object(
                    startup_cold_optimizations,
                    "_source_commit",
                    return_value="a" * 40,
                ),
                patch.object(
                    startup_cold_optimizations,
                    "_maintenance_signature",
                    return_value="c" * 64,
                ),
            ):
                self.assertFalse(
                    startup_cold_optimizations._write_snapshot_cache(
                        campaign,
                        snapshot,
                        environ=None,
                        campaign_identity=captured_campaign,
                        snapshot_identity=captured_snapshot,
                    )
                )
                cache = startup_cold_optimizations._snapshot_cache_path(
                    campaign,
                    snapshot,
                    environ=None,
                )
                self.assertFalse(cache.exists())


class GodotImportFingerprintTests(unittest.TestCase):
    def test_generated_runtime_files_do_not_change_import_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            (project / "main.tscn").write_text("[gd_scene]\n", encoding="utf-8")
            (project / "scripts").mkdir()
            (project / "scripts" / "main.gd").write_text("extends Node\n", encoding="utf-8")
            baseline = fast_entrypoint._godot_project_fingerprint(project)
            self.assertIsNotNone(baseline)
            (project / ".godot").mkdir()
            (project / ".godot" / "global_script_class_cache.cfg").write_text(
                "cache\n",
                encoding="utf-8",
            )
            (project / "scripts" / "main.gd.uid").write_text("uid://abc\n", encoding="utf-8")
            (project / "campaign_snapshot.json").write_text("{}\n", encoding="utf-8")
            (project / "frontend_commands.json").write_text("{}\n", encoding="utf-8")
            (project / "home_earth3.png").write_bytes(b"png")
            (project / "main.tscn.import").write_text("remap\n", encoding="utf-8")
            self.assertEqual(baseline, fast_entrypoint._godot_project_fingerprint(project))
            (project / "scripts" / "main.gd").write_text("extends Node2D\n", encoding="utf-8")
            changed_script = fast_entrypoint._godot_project_fingerprint(project)
            self.assertNotEqual(baseline, changed_script)
            (project / "scripts" / "main.gd").write_text("extends Node\n", encoding="utf-8")
            (project / "main.tscn").write_text("[gd_scene load_steps=2]\n", encoding="utf-8")
            self.assertNotEqual(baseline, fast_entrypoint._godot_project_fingerprint(project))


class StartupReuseDiagnosisTests(unittest.TestCase):
    def test_diagnose_reports_missing_session_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / "campaign.json"
            snapshot = Path(temporary) / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            snapshot.write_text("{}\n", encoding="utf-8")
            with patch.object(
                persistent_backend,
                "_runtime_source_commit",
                return_value="a" * 40,
            ):
                state, reason = persistent_backend.diagnose_startup_reuse(
                    campaign,
                    snapshot,
                )
            self.assertIsNone(state)
            self.assertEqual("no_session_descriptor", reason)

    def test_fast_path_emits_exact_reuse_rejection_reason(self) -> None:
        source = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("diagnose_startup_reuse", source)
        self.assertNotIn('reason="daemon_or_fingerprint_miss"', source)


if __name__ == "__main__":
    unittest.main()
