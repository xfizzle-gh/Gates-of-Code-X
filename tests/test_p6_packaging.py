"""P6 packaging, provenance, restore, and reset containment."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.packaging import (  # noqa: E402
    PackagingError,
    backup_managed_campaign,
    package_identity,
    reset_test_campaign,
    resolve_source_commit,
    restore_managed_backup,
    write_source_commit_stamp,
)
from gates_of_codex.player_shell import CAMPAIGN_FILE_NAME, SNAPSHOT_FILE_NAME  # noqa: E402


class PackagingProvenanceTests(unittest.TestCase):
    def test_env_stamp_is_authoritative_and_rejects_lies(self) -> None:
        commit = "a" * 40
        env = {**os.environ, "GATES_OF_CODEX_SOURCE_COMMIT": commit}
        self.assertEqual(commit, resolve_source_commit(environ=env))
        with self.assertRaises(PackagingError):
            resolve_source_commit(
                environ={**os.environ, "GATES_OF_CODEX_SOURCE_COMMIT": "not-a-commit"}
            )

    def test_source_commit_file_is_used_when_env_absent(self) -> None:
        commit = "b" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stamp = write_source_commit_stamp(root / "SOURCE_COMMIT", commit)
            self.assertTrue(stamp.is_file())
            env = {k: v for k, v in os.environ.items() if k != "GATES_OF_CODEX_SOURCE_COMMIT"}
            self.assertEqual(commit, resolve_source_commit(root=root, environ=env))

    def test_package_identity_carries_version_and_commit(self) -> None:
        commit = "c" * 40
        env = {
            **os.environ,
            "GATES_OF_CODEX_SOURCE_COMMIT": commit,
            "GATES_OF_CODEX_HOME": str(Path(tempfile.mkdtemp())),
        }
        identity = package_identity(environ=env)
        self.assertEqual("Gates of CodeX", identity.application_name)
        self.assertTrue(identity.version)
        self.assertEqual(commit, identity.source_commit)
        self.assertEqual(commit[:12], identity.source_commit_short)


class ManagedRestoreResetTests(unittest.TestCase):
    def _managed_home(self, temporary: str) -> dict[str, str]:
        home = Path(temporary) / "GatesOfCodeX"
        home.mkdir(parents=True, exist_ok=True)
        return {**os.environ, "GATES_OF_CODEX_HOME": str(home), "LOCALAPPDATA": str(Path(temporary))}

    def _seed_campaign(self, home: Path, body: str = '{"turn":1}') -> Path:
        campaign_dir = home / "campaigns" / "earth3_v1"
        campaign_dir.mkdir(parents=True, exist_ok=True)
        campaign = campaign_dir / CAMPAIGN_FILE_NAME
        campaign.write_text(body + "\n", encoding="utf-8")
        (campaign_dir / SNAPSHOT_FILE_NAME).write_text('{"schema":"gates-of-codex.frontend"}\n', encoding="utf-8")
        return campaign

    def test_backup_and_restore_round_trip_is_contained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"turn":7,"marker":"original"}')
            record = backup_managed_campaign(campaign, environ=env)
            self.assertTrue(Path(record.backup_directory).is_dir())
            campaign.write_text('{"turn":99,"marker":"mutated"}\n', encoding="utf-8")
            restored = restore_managed_backup(
                record.backup_directory,
                expected_campaign=campaign,
                environ=env,
            )
            self.assertTrue(any(path == campaign for path in restored))
            payload = json.loads(campaign.read_text(encoding="utf-8"))
            self.assertEqual("original", payload["marker"])

    def test_restore_refuses_unrelated_campaign_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign_a = self._seed_campaign(home, '{"id":"a"}')
            other_dir = home / "campaigns" / "other"
            other_dir.mkdir(parents=True, exist_ok=True)
            other = other_dir / CAMPAIGN_FILE_NAME
            other.write_text('{"id":"b"}\n', encoding="utf-8")
            record = backup_managed_campaign(campaign_a, environ=env)
            with self.assertRaises(PackagingError):
                restore_managed_backup(
                    record.backup_directory,
                    expected_campaign=other,
                    environ=env,
                )

    def test_restore_refuses_paths_outside_managed_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home)
            record = backup_managed_campaign(campaign, environ=env)
            # Tamper the backup manifest to point outside managed campaigns.
            manifest = Path(record.backup_directory) / "backup.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            outside = Path(temporary) / "escape" / CAMPAIGN_FILE_NAME
            payload["files"] = {str(outside): next(iter(payload["files"].values()))}
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(PackagingError):
                restore_managed_backup(record.backup_directory, environ=env)

    def test_reset_test_campaign_only_clears_managed_known_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"turn":3}')
            report = reset_test_campaign(campaign, environ=env, create_backup=True)
            self.assertTrue(report["ok"])
            self.assertFalse(campaign.exists())
            self.assertTrue(Path(report["backup_directory"]).is_dir())

    def test_reset_refuses_unexpected_files_and_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home)
            (campaign.parent / "notes.txt").write_text("nope\n", encoding="utf-8")
            with self.assertRaises(PackagingError):
                reset_test_campaign(campaign, environ=env, create_backup=False)
            outside = Path(temporary) / "not-managed" / CAMPAIGN_FILE_NAME
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(PackagingError):
                reset_test_campaign(outside, environ=env, create_backup=False)


if __name__ == "__main__":
    unittest.main()
