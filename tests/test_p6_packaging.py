"""P6 packaging, provenance, restore, and reset containment."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
    def test_adjacent_package_stamp_wins_without_git_or_environment(self) -> None:
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "gates_of_codex"
            package.mkdir()
            write_source_commit_stamp(package / "SOURCE_COMMIT", commit)
            with mock.patch("gates_of_codex.packaging.subprocess.run") as run:
                self.assertEqual(commit, resolve_source_commit(root=package, environ={}))
                run.assert_not_called()

    def test_adjacent_package_stamp_overrides_source_test_environment(self) -> None:
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "gates_of_codex"
            package.mkdir()
            write_source_commit_stamp(package / "SOURCE_COMMIT", commit)
            self.assertEqual(
                commit,
                resolve_source_commit(
                    root=package,
                    environ={"GATES_OF_CODEX_SOURCE_COMMIT": "f" * 40},
                ),
            )

    def test_installed_package_missing_or_malformed_stamp_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "gates_of_codex"
            package.mkdir()
            with self.assertRaises(PackagingError):
                resolve_source_commit(root=package, environ={})
            (package / "SOURCE_COMMIT").write_text("dirty\n", encoding="ascii")
            with self.assertRaises(PackagingError):
                resolve_source_commit(root=package, environ={})

    def test_installed_package_cannot_use_source_test_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "gates_of_codex"
            package.mkdir()
            with self.assertRaises(PackagingError):
                resolve_source_commit(
                    root=package,
                    environ={"GATES_OF_CODEX_SOURCE_COMMIT": "e" * 40},
                )

    def test_source_checkout_without_stamp_uses_git(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                "[project]\nname='probe'\n", encoding="utf-8"
            )
            (root / ".git").mkdir()
            completed = subprocess.CompletedProcess([], 0, stdout="b" * 40 + "\n")
            with mock.patch(
                "gates_of_codex.packaging.subprocess.run", return_value=completed
            ):
                self.assertEqual("b" * 40, resolve_source_commit(root=root, environ={}))

    @unittest.skipUnless(sys.platform == "win32", "PowerShell provenance helper is Windows-only")
    def test_stamp_helper_rejects_dirty_tracked_working_tree(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            self.skipTest("PowerShell is required for the provenance helper smoke")
        script = ROOT / "tools" / "stamp_package_provenance.ps1"
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "fixture repo"
            package = repository / "src" / "gates_of_codex"
            package.mkdir(parents=True)
            tracked = repository / "tracked.txt"
            tracked.write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Task One"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "config",
                    "user.email",
                    "task-one@example.invalid",
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "add", "tracked.txt"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-m", "fixture"],
                check=True,
                capture_output=True,
            )
            invocation = [
                shell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Root",
                str(repository),
            ]
            clean = subprocess.run(invocation, capture_output=True, text=True)
            self.assertEqual(0, clean.returncode, clean.stderr)
            expected = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(
                expected + "\n",
                (package / "SOURCE_COMMIT").read_text(encoding="ascii"),
            )
            tracked.write_text("dirty\n", encoding="utf-8")
            dirty = subprocess.run(invocation, capture_output=True, text=True)
            self.assertNotEqual(0, dirty.returncode)
            self.assertIn("tracked working tree is dirty", dirty.stderr + dirty.stdout)

    def test_installer_and_workflows_stamp_before_install_and_freeze(self) -> None:
        installer = (ROOT / "tools" / "install_gates_of_codex.ps1").read_text(
            encoding="utf-8-sig"
        )
        stamp_call = "& $StampScript -Root $Root"
        package_install = "-m pip install --upgrade $Root"
        self.assertIn(stamp_call, installer)
        self.assertLess(installer.index(stamp_call), installer.index(package_install))
        self.assertEqual(
            3,
            installer.count(
                '--add-data "src\\gates_of_codex\\SOURCE_COMMIT;gates_of_codex"'
            ),
        )
        self.assertIn("finally", installer)
        self.assertIn("Remove-Item -LiteralPath $StampPath -Force", installer)
        self.assertIn("$Snapshot.application.source_commit", installer)
        self.assertEqual(1, installer.count("pyi-archive_viewer.exe"))
        self.assertIn("[regex]::Escape($SourceCommit)", installer)
        self.assertIn("GatesOfCodeXProvenanceProbe", installer)
        self.assertIn("Frozen runtime provenance mismatch", installer)

        expected_job_counts = {
            Path(".github/workflows/gates-of-codex.yml"): 6,
            Path(".github/workflows/release.yml"): 1,
        }
        for relative, expected_jobs in expected_job_counts.items():
            workflow = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("tools\\stamp_package_provenance.ps1", workflow, relative)
            self.assertEqual(
                expected_jobs,
                workflow.count("- name: Stamp package provenance"),
                relative,
            )
            self.assertEqual(expected_jobs, workflow.count("id: provenance"), relative)
            self.assertIn("steps.provenance.outputs.commit", workflow, relative)
            self.assertEqual(
                3,
                workflow.count(
                    '--add-data "src\\gates_of_codex\\SOURCE_COMMIT;gates_of_codex"'
                ),
                relative,
            )
            self.assertIn("if: always()", workflow, relative)
            self.assertIn(
                "Remove-Item -LiteralPath src\\gates_of_codex\\SOURCE_COMMIT -Force",
                workflow,
                relative,
            )
            self.assertEqual(
                expected_jobs,
                workflow.count("- name: Cleanup package provenance"),
                relative,
            )
            self.assertIn("package_identity().source_commit", workflow, relative)
            self.assertIn("pyi-archive_viewer -l", workflow, relative)
            self.assertIn("[regex]::Escape($expectedCommit)", workflow, relative)
            self.assertIn("GatesOfCodeXProvenanceProbe", workflow, relative)
            self.assertIn("Frozen runtime provenance mismatch", workflow, relative)

    def test_installed_wheel_uses_embedded_stamp_outside_source_checkout(self) -> None:
        try:
            __import__("build")
        except ImportError:
            self.skipTest("the 'build' module is required for installed-wheel provenance smoke")
        commit = "d" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "fixture"
            fixture.mkdir()
            shutil.copy2(ROOT / "pyproject.toml", fixture / "pyproject.toml")
            shutil.copy2(ROOT / "README.md", fixture / "README.md")
            shutil.copytree(ROOT / "src", fixture / "src")
            write_source_commit_stamp(
                fixture / "src" / "gates_of_codex" / "SOURCE_COMMIT", commit
            )
            wheelhouse = root / "wheelhouse"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--wheel",
                    "--no-isolation",
                    "--outdir",
                    str(wheelhouse),
                    str(fixture),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            wheel = next(wheelhouse.glob("*.whl"))
            environment = root / "venv"
            subprocess.run(
                [sys.executable, "-m", "venv", str(environment)],
                check=True,
                capture_output=True,
                text=True,
            )
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run(
                [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
                check=True,
                capture_output=True,
                text=True,
            )
            outside = root / "outside source"
            outside.mkdir()
            env = dict(os.environ)
            env.pop("GATES_OF_CODEX_SOURCE_COMMIT", None)
            env.pop("PYTHONPATH", None)
            env["PATH"] = str(python.parent)
            completed = subprocess.run(
                [
                    str(python),
                    "-I",
                    "-c",
                    (
                        "from gates_of_codex.packaging import package_identity; "
                        "print(package_identity().source_commit)"
                    ),
                ],
                cwd=outside,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(commit, completed.stdout.strip())

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
