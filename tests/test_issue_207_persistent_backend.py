from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import persistent_backend


ROOT = Path(__file__).resolve().parents[1]


class PersistentBackendTransportTests(unittest.TestCase):
    def test_apply_invocation_resolves_campaign_snapshot_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            parsed = persistent_backend._apply_invocation(
                [
                    "apply-frontend",
                    str(campaign),
                    "--snapshot",
                    str(snapshot),
                    "--commands",
                    str(commands),
                ]
            )
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(campaign.resolve(), parsed[0])
            self.assertEqual(snapshot.resolve(), parsed[1])
            self.assertEqual(commands.resolve(), parsed[2])

    def test_forwarder_returns_exact_daemon_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            campaign.write_text("{}\n", encoding="utf-8")
            commands.write_text('{"commands":[{"op":"end_player_round"}]}\n', encoding="utf-8")

            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind(("127.0.0.1", 0))
            server.listen(2)
            port = int(server.getsockname()[1])
            token = "test-token"
            descriptor = {
                "schema": persistent_backend.SESSION_SCHEMA,
                "schema_version": persistent_backend.SESSION_SCHEMA_VERSION,
                "campaign_path": str(campaign.resolve()),
                "snapshot_path": str(snapshot.resolve()),
                "port": port,
                "token": token,
                "pid": 1,
            }
            persistent_backend._atomic_json(
                persistent_backend._session_path(campaign), descriptor
            )

            expected_stdout = '{"ok":true,"timings":{"load_ms":0.0}}'

            def serve() -> None:
                ping_connection, _ = server.accept()
                with ping_connection:
                    stream = ping_connection.makefile("rwb")
                    request = json.loads(stream.readline().decode("utf-8"))
                    self.assertEqual("ping", request["action"])
                    stream.write(b'{"handled":true,"exit_code":0,"stdout":"","ok":true}\n')
                    stream.flush()
                connection, _ = server.accept()
                with connection:
                    stream = connection.makefile("rwb")
                    request = json.loads(stream.readline().decode("utf-8"))
                    self.assertEqual(token, request["token"])
                    self.assertEqual("apply", request["action"])
                    stream.write(
                        (
                            json.dumps(
                                {
                                    "handled": True,
                                    "exit_code": 0,
                                    "stdout": expected_stdout,
                                    "ok": True,
                                },
                                separators=(",", ":"),
                            )
                            + "\n"
                        ).encode("utf-8")
                    )
                    stream.flush()
                server.close()

            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            result = persistent_backend.try_forward_apply_frontend(
                [
                    "apply-frontend",
                    str(campaign),
                    "--snapshot",
                    str(snapshot),
                    "--commands",
                    str(commands),
                ]
            )
            worker.join(timeout=2.0)
            self.assertEqual((0, expected_stdout), result)

    def test_lost_reply_after_dispatch_never_falls_back_to_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / "campaign.json"
            campaign.write_text("{}\n", encoding="utf-8")
            session = {
                "schema": persistent_backend.SESSION_SCHEMA,
                "schema_version": persistent_backend.SESSION_SCHEMA_VERSION,
                "campaign_path": str(campaign.resolve()),
                "port": 12345,
                "token": "token",
            }
            with (
                patch.object(persistent_backend, "_read_session", return_value=session),
                patch.object(
                    persistent_backend,
                    "_request",
                    side_effect=[{"ok": True}, None],
                ),
            ):
                result = persistent_backend.try_forward_apply_frontend(
                    ["apply-frontend", str(campaign)]
                )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(0, result[0])
            payload = json.loads(result[1])
            self.assertFalse(payload["ok"])
            self.assertIn("ambiguous", payload["results"][0]["detail"].lower())

    def test_fingerprint_detects_same_size_external_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            path.write_text('{"a":1}\n', encoding="utf-8")
            before = persistent_backend._fingerprint(path)
            path.write_text('{"a":2}\n', encoding="utf-8")
            after = persistent_backend._fingerprint(path)
            self.assertEqual(before[0], after[0])
            self.assertNotEqual(before[2], after[2])

    def test_daemon_scope_excludes_self_committing_operations(self) -> None:
        self.assertIn("end_player_round", persistent_backend.SUPPORTED_OPS)
        self.assertIn("issue_move_order", persistent_backend.SUPPORTED_OPS)
        self.assertIn("cancel_move_order", persistent_backend.SUPPORTED_OPS)
        self.assertIn("verify_result", persistent_backend.SUPPORTED_OPS)
        for op in ("handoff", "import_battle", "restore_backup", "reset_test_campaign"):
            self.assertNotIn(op, persistent_backend.SUPPORTED_OPS)

    def test_direct_cache_loader_leases_once_then_uses_canonical_loader(self) -> None:
        cached = object()
        canonical = object()
        calls: list[Path] = []

        def original_loader(path):
            calls.append(Path(path))
            return canonical

        loader = persistent_backend._direct_cache_loader(cached, original_loader)
        first = loader(Path("campaign.json"))
        second = loader(Path("campaign.json"))

        self.assertIs(cached, first)
        self.assertIs(canonical, second)
        self.assertEqual([Path("campaign.json")], calls)

    def test_cache_survival_requires_success_and_persistence_for_mutation(self) -> None:
        ok = {"ok": True}
        failed = {"ok": False}
        self.assertTrue(
            persistent_backend._cache_can_survive_report(
                ok,
                ["verify_result"],
                persisted=False,
            )
        )
        self.assertTrue(
            persistent_backend._cache_can_survive_report(
                ok,
                ["end_player_round"],
                persisted=True,
            )
        )
        self.assertFalse(
            persistent_backend._cache_can_survive_report(
                ok,
                ["end_player_round"],
                persisted=False,
            )
        )
        self.assertFalse(
            persistent_backend._cache_can_survive_report(
                failed,
                ["end_player_round"],
                persisted=True,
            )
        )

    def test_persistent_backend_uses_direct_lease_without_full_state_clone(self) -> None:
        source = (ROOT / "src/gates_of_codex/persistent_backend.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('socket.create_connection(("127.0.0.1", port)', source)
        self.assertIn("hashlib.sha256", source)
        self.assertIn("_direct_cache_loader", source)
        self.assertIn("_cache_can_survive_report", source)
        self.assertIn("_ambiguous_daemon_payload", source)
        self.assertNotIn("copy.deepcopy(", source)
        self.assertNotIn("import pickle", source)
        self.assertNotIn("import marshal", source)


class PersistentBackendRuntimeWiringTests(unittest.TestCase):
    def test_player_launch_starts_session_before_godot(self) -> None:
        source = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        launch_block = source.split("def launch_after_import(", 1)[1].split(
            "launch_after_import._goc_preimport_guard", 1
        )[0]
        self.assertIn("ensure_backend_session", launch_block)
        self.assertLess(
            launch_block.index("ensure_backend_session"),
            launch_block.index("return original_launch"),
        )

    def test_frozen_live_client_forwards_before_reauthenticating(self) -> None:
        source = (ROOT / "run_gates_of_codex_live.py").read_text(encoding="utf-8")
        main_block = source.split("def main(", 1)[1]
        self.assertLess(
            main_block.index("_try_persistent_forward(arguments)"),
            main_block.index("_authenticate_frozen_earth3()"),
        )

    def test_fast_entrypoint_routes_session_backend_before_application_cli(self) -> None:
        source = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        main_block = source.split("def main(", 1)[1].split("def player_main(", 1)[0]
        self.assertIn('arguments[:1] == ["session-backend"]', main_block)
        self.assertIn("install_runtime_contracts()", main_block)
        self.assertIn("run_session_backend(arguments[1:])", main_block)
        self.assertLess(
            main_block.index('arguments[:1] == ["session-backend"]'),
            main_block.index("application_main(arguments)"),
        )


if __name__ == "__main__":
    unittest.main()
