from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import persistent_backend


class PersistentBackendBuildIdentityTests(unittest.TestCase):
    def test_previous_build_daemon_is_rejected_before_ping_or_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            campaign.write_text("{}\n", encoding="utf-8")
            commands.write_text(
                '{"commands":[{"op":"end_player_round"}]}\n',
                encoding="utf-8",
            )

            old_commit = "a" * 40
            current_commit = "b" * 40
            descriptor = {
                "schema": persistent_backend.SESSION_SCHEMA,
                "schema_version": persistent_backend.SESSION_SCHEMA_VERSION,
                "source_commit": old_commit,
                "campaign_path": str(campaign.resolve()),
                "snapshot_path": str(snapshot.resolve()),
                "port": 12345,
                "token": "old-build-token",
                "pid": 1234,
            }
            session_path = persistent_backend._session_path(campaign)
            persistent_backend._atomic_json(session_path, descriptor)

            with (
                patch.object(
                    persistent_backend,
                    "_runtime_source_commit",
                    return_value=current_commit,
                ),
                patch.object(persistent_backend, "_request") as request,
            ):
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

            self.assertIsNone(result)
            request.assert_not_called()
            self.assertFalse(session_path.exists())

    def test_session_protocol_carries_current_build_identity(self) -> None:
        current_commit = "c" * 40
        session = {"port": 12345, "token": "token"}
        captured: dict[str, object] = {}

        class FakeStream:
            def write(self, raw: bytes) -> None:
                captured.update(json.loads(raw.decode("utf-8")))

            def flush(self) -> None:
                pass

            def readline(self, _limit: int) -> bytes:
                return b'{"ok":true}\n'

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def settimeout(self, _timeout: float) -> None:
                pass

            def makefile(self, _mode: str) -> FakeStream:
                return FakeStream()

        with (
            patch.object(
                persistent_backend,
                "_runtime_source_commit",
                return_value=current_commit,
            ),
            patch.object(
                persistent_backend.socket,
                "create_connection",
                return_value=FakeConnection(),
            ),
        ):
            response = persistent_backend._request(session, {"action": "ping"})

        self.assertEqual({"ok": True}, response)
        self.assertEqual(current_commit, captured["source_commit"])
        self.assertEqual("token", captured["token"])


if __name__ == "__main__":
    unittest.main()
