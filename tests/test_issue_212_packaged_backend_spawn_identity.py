from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import startup_backend_spawn_identity
from gates_of_codex import startup_cold_optimizations as cold


class PackagedBackendSpawnIdentityTests(unittest.TestCase):
    def test_frozen_nonblocking_spawn_carries_exact_expected_source_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            player = root / "GatesOfCodeX.exe"
            campaign.write_text("{}\n", encoding="utf-8")
            snapshot.write_text("{}\n", encoding="utf-8")
            player.write_bytes(b"player")
            source_commit = "d" * 40
            fake_backend = types.SimpleNamespace(
                _runtime_source_commit=lambda: source_commit,
                _drop_session_descriptor=lambda _campaign: None,
                _ping=lambda _campaign: False,
            )

            original = cold._begin_backend_session_nonblocking
            installed = startup_backend_spawn_identity._INSTALLED
            startup_backend_spawn_identity._INSTALLED = False
            cold._BACKEND_STARTING.clear()
            try:
                startup_backend_spawn_identity.install_packaged_backend_spawn_identity()
                with (
                    patch.object(cold.sys, "frozen", True, create=True),
                    patch.object(cold.sys, "executable", str(player)),
                    patch.object(cold.subprocess, "Popen") as popen,
                ):
                    ready = cold._begin_backend_session_nonblocking(
                        fake_backend,
                        campaign,
                        snapshot,
                    )
                self.assertFalse(ready)
                popen.assert_called_once()
                command = list(popen.call_args.args[0])
                self.assertEqual("GatesOfCodeXLive.exe", Path(command[0]).name)
                self.assertEqual("session-backend", command[1])
                self.assertIn("--expected-source-commit", command)
                index = command.index("--expected-source-commit")
                self.assertEqual(source_commit, command[index + 1])
            finally:
                cold._begin_backend_session_nonblocking = original
                startup_backend_spawn_identity._INSTALLED = installed
                cold._BACKEND_STARTING.clear()

    def test_nonfrozen_spawn_delegates_to_existing_source_path(self) -> None:
        marker: list[tuple[object, Path, Path]] = []

        def original(backend, campaign, snapshot):
            marker.append((backend, campaign, snapshot))
            return True

        installed = startup_backend_spawn_identity._INSTALLED
        previous = cold._begin_backend_session_nonblocking
        startup_backend_spawn_identity._INSTALLED = False
        cold._begin_backend_session_nonblocking = original
        try:
            startup_backend_spawn_identity.install_packaged_backend_spawn_identity()
            backend = object()
            campaign = Path("campaign.json")
            snapshot = Path("campaign_snapshot.json")
            with patch.object(cold.sys, "frozen", False, create=True):
                self.assertTrue(
                    cold._begin_backend_session_nonblocking(
                        backend,
                        campaign,
                        snapshot,
                    )
                )
            self.assertEqual([(backend, campaign, snapshot)], marker)
        finally:
            cold._begin_backend_session_nonblocking = previous
            startup_backend_spawn_identity._INSTALLED = installed


if __name__ == "__main__":
    unittest.main()
