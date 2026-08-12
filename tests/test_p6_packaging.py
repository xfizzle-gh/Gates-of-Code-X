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

from gates_of_codex import packaging  # noqa: E402
from gates_of_codex.packaging import (  # noqa: E402
    PackagingError,
    backup_managed_campaign,
    package_identity,
    reset_test_campaign,
    resolve_source_commit,
    restore_managed_backup,
    write_source_commit_stamp,
)
from gates_of_codex.player_shell import (  # noqa: E402
    CAMPAIGN_FILE_NAME,
    SNAPSHOT_FILE_NAME,
    last_campaign_path,
    write_last_campaign,
)


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
        static_add_data = '--add-data "src\\gates_of_codex\\SOURCE_COMMIT;gates_of_codex"'
        installer_resolved_add_data = '--add-data "$SourceCommitPath;gates_of_codex"'
        self.assertIn(stamp_call, installer)
        self.assertLess(installer.index(stamp_call), installer.index(package_install))
        self.assertEqual(
            3,
            installer.count(static_add_data) + installer.count(installer_resolved_add_data),
        )
        self.assertEqual(1, installer.count(installer_resolved_add_data))
        self.assertIn(
            "$SourceCommitPath = (Resolve-Path -LiteralPath $StampPath).Path",
            installer,
        )
        self.assertIn(
            '--specpath $ProbeRoot --add-data "$SourceCommitPath;gates_of_codex"',
            installer,
        )
        self.assertNotIn(
            '--specpath $ProbeRoot --add-data "src\\gates_of_codex\\SOURCE_COMMIT;gates_of_codex"',
            installer,
        )
        self.assertIn("finally", installer)
        self.assertIn("Remove-Item -LiteralPath $StampPath -Force", installer)
        self.assertIn("$Snapshot.application.source_commit", installer)
        self.assertEqual(1, installer.count("pyi-archive_viewer.exe"))
        self.assertIn("[regex]::Escape($SourceCommit)", installer)
        self.assertIn(
            'foreach ($Entry in @("gates_of_codex\\SOURCE_COMMIT", "gates_of_codex/SOURCE_COMMIT"))',
            installer,
        )
        self.assertNotIn("[regex]::Match($Archive, 'gates_of_codex", installer)
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
            resolved_add_data = '--add-data "$sourceCommit;gates_of_codex"'
            self.assertEqual(
                3,
                workflow.count(static_add_data) + workflow.count(resolved_add_data),
                relative,
            )
            self.assertEqual(1, workflow.count(resolved_add_data), relative)
            self.assertIn(
                '$sourceCommit = (Resolve-Path -LiteralPath "src\\gates_of_codex\\SOURCE_COMMIT").Path',
                workflow,
                relative,
            )
            self.assertIn(
                '--specpath $probeRoot --add-data "$sourceCommit;gates_of_codex"',
                workflow,
                relative,
            )
            self.assertNotIn(
                '--specpath $probeRoot --add-data "src\\gates_of_codex\\SOURCE_COMMIT;gates_of_codex"',
                workflow,
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
            self.assertIn(
                'foreach ($entry in @("gates_of_codex\\SOURCE_COMMIT", "gates_of_codex/SOURCE_COMMIT"))',
                workflow,
                relative,
            )
            self.assertNotIn("[regex]::Match($archive, 'gates_of_codex", workflow, relative)
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
        payload = {
            "campaign_name": "Managed restore fixture",
            "current_faction": "nato",
            "factions": {"nato": {"faction": "nato"}},
            "provinces": {
                "fixture": {
                    "display_name": "Fixture",
                    "neighbors": [],
                    "owner": "nato",
                    "province_id": "fixture",
                }
            },
            "selected_faction": "nato",
            "turn_number": 1,
        }
        payload.update(json.loads(body))
        campaign.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        (campaign_dir / SNAPSHOT_FILE_NAME).write_text('{"schema":"gates-of-codex.frontend"}\n', encoding="utf-8")
        return campaign

    def _tree_bytes(self, directory: Path) -> dict[str, bytes]:
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }

    def _manifest(self, backup_directory: str | Path) -> tuple[Path, dict]:
        manifest = Path(backup_directory) / "backup.json"
        return manifest, json.loads(manifest.read_text(encoding="utf-8"))

    def _assert_restore_rejected_without_live_change(
        self,
        backup_directory: str | Path,
        campaign: Path,
        env: dict[str, str],
    ) -> None:
        before = self._tree_bytes(campaign.parent)
        with self.assertRaises(PackagingError):
            restore_managed_backup(
                backup_directory,
                expected_campaign=campaign,
                environ=env,
            )
        self.assertEqual(before, self._tree_bytes(campaign.parent))

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
            self.assertTrue(
                any(os.path.samefile(path, campaign) for path in restored)
            )
            for path in restored:
                self.assertTrue(
                    os.path.samefile(path, campaign.parent / path.name),
                    (path, campaign.parent / path.name),
                )
            payload = json.loads(campaign.read_text(encoding="utf-8"))
            self.assertEqual("original", payload["marker"])

    def test_restore_rejects_malformed_manifest_without_changing_live_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"marker":"backup"}')
            record = backup_managed_campaign(campaign, environ=env)
            campaign.write_text('{"marker":"live"}\n', encoding="utf-8")
            (Path(record.backup_directory) / "backup.json").write_text(
                "{broken", encoding="utf-8"
            )

            self._assert_restore_rejected_without_live_change(
                record.backup_directory, campaign, env
            )

    def test_restore_rejects_noncanonical_created_at_without_live_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"marker":"backup"}')
            record = backup_managed_campaign(campaign, environ=env)
            manifest, payload = self._manifest(record.backup_directory)
            payload["created_at_utc"] = "2026-01-01 23:00:00+00:00"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            campaign.write_text('{"marker":"live"}\n', encoding="utf-8")

            self._assert_restore_rejected_without_live_change(
                record.backup_directory, campaign, env
            )

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
            self._assert_restore_rejected_without_live_change(
                record.backup_directory, other, env
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
            self._assert_restore_rejected_without_live_change(
                record.backup_directory, campaign, env
            )

    def test_restore_rejects_unexpected_destination_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home)
            record = backup_managed_campaign(campaign, environ=env)
            manifest, payload = self._manifest(record.backup_directory)
            campaign_source = payload["files"].pop(str(campaign.resolve()))
            payload["files"][str(campaign.parent / "notes.txt")] = campaign_source
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            self._assert_restore_rejected_without_live_change(
                record.backup_directory, campaign, env
            )

    def test_restore_preflight_failure_removes_sibling_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home)
            record = backup_managed_campaign(campaign, environ=env)
            (campaign.parent / "notes.txt").write_text("unexpected\n", encoding="utf-8")

            with self.assertRaises(PackagingError):
                restore_managed_backup(
                    record.backup_directory,
                    expected_campaign=campaign,
                    environ=env,
                )

            self.assertEqual(
                [],
                list(campaign.parent.parent.glob(".earth3_v1.restore-*")),
            )

    def test_restore_rejects_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home)
            record = backup_managed_campaign(campaign, environ=env)
            _, payload = self._manifest(record.backup_directory)
            Path(payload["files"][str(campaign.resolve())]).unlink()

            self._assert_restore_rejected_without_live_change(
                record.backup_directory, campaign, env
            )

    def test_restore_rejects_source_outside_backup_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home)
            record = backup_managed_campaign(campaign, environ=env)
            manifest, payload = self._manifest(record.backup_directory)
            outside = Path(temporary) / "copied-campaign.json"
            outside.write_bytes(campaign.read_bytes())
            payload["files"][str(campaign.resolve())] = str(outside)
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            self._assert_restore_rejected_without_live_change(
                record.backup_directory, campaign, env
            )

    @unittest.skipUnless(os.name == "nt", "directory junctions are Windows-only")
    def test_restore_rejects_canonical_campaign_beyond_junction_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            external_campaigns = Path(temporary) / "external campaigns"
            external_campaigns.mkdir()
            junction = home / "campaigns"
            created = subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(junction),
                    str(external_campaigns),
                ],
                capture_output=True,
                text=True,
            )
            if created.returncode != 0:
                self.skipTest(f"junction creation unavailable: {created.stderr}")
            try:
                campaign = self._seed_campaign(home, '{"marker":"backup"}')
                canonical_campaign = campaign.resolve(strict=True)
                record = backup_managed_campaign(canonical_campaign, environ=env)
                campaign.write_text('{"marker":"live"}\n', encoding="utf-8")
                before = self._tree_bytes(campaign.parent)

                with self.assertRaises(PackagingError):
                    restore_managed_backup(
                        record.backup_directory,
                        expected_campaign=canonical_campaign,
                        environ=env,
                    )

                self.assertEqual(before, self._tree_bytes(campaign.parent))
            finally:
                if junction.exists():
                    junction.rmdir()

    def test_restore_rejects_duplicate_source_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home)
            record = backup_managed_campaign(campaign, environ=env)
            manifest, payload = self._manifest(record.backup_directory)
            campaign_source = Path(payload["files"][str(campaign.resolve())])
            aliased_source = (
                campaign_source.parent
                / ".."
                / campaign_source.parent.name
                / campaign_source.name
            )
            payload["files"][str(campaign.parent / SNAPSHOT_FILE_NAME)] = str(
                aliased_source
            )
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            self._assert_restore_rejected_without_live_change(
                record.backup_directory, campaign, env
            )

    def test_latest_backup_ignores_newer_unrelated_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"marker":"matching-backup"}')
            matching = backup_managed_campaign(campaign, environ=env, label="matching")
            other = home / "campaigns" / "other" / CAMPAIGN_FILE_NAME
            other.parent.mkdir(parents=True)
            other.write_bytes(campaign.read_bytes())
            unrelated = backup_managed_campaign(other, environ=env, label="unrelated")
            unrelated_manifest, payload = self._manifest(unrelated.backup_directory)
            payload["created_at_utc"] = "9999-12-31T23:59:59+00:00"
            unrelated_manifest.write_text(json.dumps(payload), encoding="utf-8")

            descriptor = packaging.latest_managed_backup(campaign, environ=env)

            self.assertIsNotNone(descriptor)
            assert descriptor is not None
            self.assertEqual(
                Path(matching.backup_directory).resolve(strict=False),
                Path(descriptor["backup_directory"]).resolve(strict=False),
            )
            campaign.write_text('{"marker":"live"}\n', encoding="utf-8")
            restored = restore_managed_backup(
                expected_campaign=campaign,
                environ=env,
            )
            self.assertTrue(restored)
            self.assertEqual(
                "matching-backup",
                json.loads(campaign.read_text(encoding="utf-8"))["marker"],
            )

    def test_latest_restore_rejects_when_only_unrelated_backup_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"marker":"live"}')
            other = home / "campaigns" / "other" / CAMPAIGN_FILE_NAME
            other.parent.mkdir(parents=True)
            other.write_bytes(campaign.read_bytes())
            backup_managed_campaign(other, environ=env, label="unrelated")
            before = self._tree_bytes(campaign.parent)

            with self.assertRaisesRegex(
                PackagingError, "No authenticated backup exists"
            ):
                restore_managed_backup(
                    expected_campaign=campaign,
                    environ=env,
                )

            self.assertEqual(before, self._tree_bytes(campaign.parent))

    def test_restore_publication_failure_rolls_back_byte_identical_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"turn":7,"marker":"backup"}')
            record = backup_managed_campaign(campaign, environ=env)
            campaign.write_text('{"turn":99,"marker":"live"}\n', encoding="utf-8")
            (campaign.parent / SNAPSHOT_FILE_NAME).write_bytes(b"live snapshot\r\n")
            before = self._tree_bytes(campaign.parent)
            real_replace = packaging._replace_directory
            calls = 0

            def fail_stage_publish(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected publication failure")
                real_replace(source, destination)

            with mock.patch(
                "gates_of_codex.packaging._replace_directory",
                side_effect=fail_stage_publish,
            ):
                with self.assertRaises(PackagingError):
                    restore_managed_backup(
                        record.backup_directory,
                        expected_campaign=campaign,
                        environ=env,
                    )
            self.assertEqual(before, self._tree_bytes(campaign.parent))

    def test_post_rename_validation_failure_restores_live_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"marker":"backup"}')
            record = backup_managed_campaign(campaign, environ=env)
            campaign.write_text('{"marker":"live"}\n', encoding="utf-8")
            before = self._tree_bytes(campaign.parent)
            real_require_directory = packaging._require_directory
            rollback_checks = 0

            def fail_first_rollback_check(path: Path, *, label: str):
                nonlocal rollback_checks
                if label == "restore rollback":
                    rollback_checks += 1
                    if rollback_checks == 1:
                        raise PackagingError("injected rollback validation failure")
                return real_require_directory(path, label=label)

            with mock.patch(
                "gates_of_codex.packaging._require_directory",
                side_effect=fail_first_rollback_check,
            ):
                with self.assertRaises(PackagingError):
                    restore_managed_backup(
                        record.backup_directory,
                        expected_campaign=campaign,
                        environ=env,
                    )

            self.assertTrue(campaign.parent.is_dir())
            self.assertEqual(before, self._tree_bytes(campaign.parent))

    def test_restore_rollback_failure_preserves_recovery_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"marker":"backup"}')
            record = backup_managed_campaign(campaign, environ=env)
            campaign.write_text('{"marker":"live"}\n', encoding="utf-8")
            before = self._tree_bytes(campaign.parent)
            rollback = campaign.parent.parent / ".earth3_v1.rollback-preserved"
            real_replace = packaging._replace_directory
            calls = 0

            def fail_publish_and_rollback(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls >= 2:
                    raise OSError(f"injected replacement failure {calls}")
                real_replace(source, destination)

            fake_uuid = mock.Mock(hex="preserved")
            with mock.patch(
                "gates_of_codex.packaging.uuid.uuid4", return_value=fake_uuid
            ), mock.patch(
                "gates_of_codex.packaging._replace_directory",
                side_effect=fail_publish_and_rollback,
            ):
                with self.assertRaises(PackagingError) as raised:
                    restore_managed_backup(
                        record.backup_directory,
                        expected_campaign=campaign,
                        environ=env,
                    )
            self.assertTrue(rollback.is_dir())
            retained = Path(
                str(raised.exception)
                .split("original tree retained at ", 1)[1]
                .splitlines()[0]
            )
            self.assertTrue(os.path.samefile(retained, rollback), (retained, rollback))
            self.assertEqual(before, self._tree_bytes(rollback))

    def test_stage_cleanup_failure_does_not_mask_preserved_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"marker":"backup"}')
            record = backup_managed_campaign(campaign, environ=env)
            campaign.write_text('{"marker":"live"}\n', encoding="utf-8")
            before = self._tree_bytes(campaign.parent)
            rollback = campaign.parent.parent / ".earth3_v1.rollback-preserved"
            real_replace = packaging._replace_directory
            real_remove = packaging._remove_sibling_directory
            calls = 0

            def fail_publish_and_rollback(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls >= 2:
                    raise OSError(f"injected replacement failure {calls}")
                real_replace(source, destination)

            def fail_stage_cleanup(path: Path, *, parent: Path, label: str) -> None:
                if label == "restore stage":
                    raise OSError("stage cleanup blocked")
                real_remove(path, parent=parent, label=label)

            fake_uuid = mock.Mock(hex="preserved")
            with mock.patch(
                "gates_of_codex.packaging.uuid.uuid4", return_value=fake_uuid
            ), mock.patch(
                "gates_of_codex.packaging._replace_directory",
                side_effect=fail_publish_and_rollback,
            ), mock.patch(
                "gates_of_codex.packaging._remove_sibling_directory",
                side_effect=fail_stage_cleanup,
            ):
                with self.assertRaises(PackagingError) as raised:
                    restore_managed_backup(
                        record.backup_directory,
                        expected_campaign=campaign,
                        environ=env,
                    )

            self.assertTrue(rollback.is_dir())
            retained = Path(
                str(raised.exception)
                .split("original tree retained at ", 1)[1]
                .splitlines()[0]
            )
            self.assertTrue(os.path.samefile(retained, rollback), (retained, rollback))
            self.assertEqual(before, self._tree_bytes(rollback))

    def test_reset_test_campaign_only_clears_managed_known_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env = self._managed_home(temporary)
            home = Path(env["GATES_OF_CODEX_HOME"])
            campaign = self._seed_campaign(home, '{"turn":3}')
            write_last_campaign(campaign, environ=env)
            report = reset_test_campaign(campaign, environ=env, create_backup=True)
            self.assertTrue(report["ok"])
            self.assertTrue(report["campaign_deleted"])
            self.assertEqual("new_campaign", report["next_player_state"])
            self.assertTrue(report["last_campaign_cleared"])
            self.assertFalse(campaign.exists())
            self.assertFalse(last_campaign_path(env).exists())
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