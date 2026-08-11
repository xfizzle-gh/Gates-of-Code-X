"""P6 packaging identity: version, source commit, and managed campaign roots.

Python remains the sole campaign authority. This module never invents campaign
state; it only derives package provenance and contains restore/reset to the
player-managed campaign tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from . import __version__ as PACKAGE_VERSION
from .acceptance import BackupRecord, backup_existing_files, restore_backup
from .player_shell import (
    CAMPAIGN_FILE_NAME,
    COMMANDS_FILE_NAME,
    SNAPSHOT_FILE_NAME,
    player_home,
    resolve_campaign_paths,
)


PROVENANCE_ENV = "GATES_OF_CODEX_SOURCE_COMMIT"
PROVENANCE_FILE_NAME = "SOURCE_COMMIT"
MANAGED_CAMPAIGNS_DIRNAME = "campaigns"
MANAGED_BACKUPS_DIRNAME = "backups"


class PackagingError(RuntimeError):
    """Raised when packaging provenance or managed-path containment fails."""


@dataclass(frozen=True, slots=True)
class PackageIdentity:
    application_name: str
    version: str
    source_commit: str
    source_commit_short: str
    package_root: str
    managed_home: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def application_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("gates-of-codex")
    except Exception:  # noqa: BLE001 - fall back to package constant
        return str(PACKAGE_VERSION)


def package_root(start: str | Path | None = None) -> Path:
    """Return the repository or installed package root used for provenance."""
    if start is not None:
        return Path(start).expanduser().resolve(strict=False)
    # Prefer the repository root (two parents above this module: src/gates_of_codex).
    here = Path(__file__).resolve()
    candidate = here.parents[2]
    if (candidate / "pyproject.toml").is_file() or (candidate / ".git").exists():
        return candidate
    return here.parents[1]


def resolve_source_commit(
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Derive the exact source commit for display and evidence.

    Order of authority:
    1. ``GATES_OF_CODEX_SOURCE_COMMIT`` when set to a 40-char hex digest
       (packaged installs stamp this at build time);
    2. ``SOURCE_COMMIT`` file beside the package root;
    3. ``git rev-parse HEAD`` when the package root is a git checkout;
    4. otherwise fail closed — packaging must not invent a commit.
    """
    env = os.environ if environ is None else environ
    stamped = str(env.get(PROVENANCE_ENV, "")).strip().lower()
    if stamped:
        if not _is_commit_sha(stamped):
            raise PackagingError(
                f"{PROVENANCE_ENV} must be a 40-character lowercase hex commit, "
                f"got {stamped!r}"
            )
        return stamped

    root_path = package_root(root)
    marker = root_path / PROVENANCE_FILE_NAME
    if marker.is_file():
        value = marker.read_text(encoding="utf-8-sig").strip().lower()
        if not _is_commit_sha(value):
            raise PackagingError(
                f"{marker} must contain a 40-character lowercase hex commit"
            )
        return value

    git_dir = root_path / ".git"
    if git_dir.exists():
        try:
            completed = subprocess.run(
                ["git", "-C", str(root_path), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PackagingError(
                f"Unable to resolve source commit from git at {root_path}: {exc}"
            ) from exc
        value = completed.stdout.strip().lower()
        if not _is_commit_sha(value):
            raise PackagingError(f"git rev-parse returned a non-commit value: {value!r}")
        return value

    raise PackagingError(
        "Package provenance is unavailable: set "
        f"{PROVENANCE_ENV}, ship a {PROVENANCE_FILE_NAME} file, or run from a git checkout"
    )


def package_identity(
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> PackageIdentity:
    commit = resolve_source_commit(root=root, environ=environ)
    home = player_home(environ)
    return PackageIdentity(
        application_name="Gates of CodeX",
        version=application_version(),
        source_commit=commit,
        source_commit_short=commit[:12],
        package_root=str(package_root(root)),
        managed_home=str(home),
    )


def write_source_commit_stamp(destination: str | Path, commit: str) -> Path:
    """Write a SOURCE_COMMIT stamp for packaged installs (build-time only)."""
    digest = str(commit).strip().lower()
    if not _is_commit_sha(digest):
        raise PackagingError(f"Cannot stamp non-commit value: {commit!r}")
    path = Path(destination).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest + "\n", encoding="utf-8")
    return path


def managed_campaigns_root(environ: Mapping[str, str] | None = None) -> Path:
    return (player_home(environ) / MANAGED_CAMPAIGNS_DIRNAME).resolve(strict=False)


def managed_backups_root(environ: Mapping[str, str] | None = None) -> Path:
    return (player_home(environ) / MANAGED_BACKUPS_DIRNAME).resolve(strict=False)


def assert_path_inside(path: str | Path, root: str | Path, *, label: str) -> Path:
    """Fail closed when ``path`` escapes the managed root."""
    target = Path(path).expanduser().resolve(strict=False)
    base = Path(root).expanduser().resolve(strict=False)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise PackagingError(
            f"{label} escapes managed directory {base}: {target}"
        ) from exc
    return target


def backup_managed_campaign(
    campaign_path: str | Path,
    *,
    backup_root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    label: str = "campaign",
) -> BackupRecord:
    """Back up a managed campaign directory's authority + derived files."""
    campaign = Path(campaign_path).expanduser().resolve(strict=False)
    if campaign.is_dir():
        directory = campaign
        campaign_file = directory / CAMPAIGN_FILE_NAME
    else:
        campaign_file = campaign
        directory = campaign_file.parent
    managed = managed_campaigns_root(environ)
    assert_path_inside(directory, managed, label="campaign directory")
    if not campaign_file.is_file():
        raise PackagingError(f"Campaign file not found: {campaign_file}")
    paths = [
        campaign_file,
        directory / SNAPSHOT_FILE_NAME,
        directory / COMMANDS_FILE_NAME,
    ]
    root = (
        Path(backup_root).expanduser().resolve(strict=False)
        if backup_root is not None
        else managed_backups_root(environ)
    )
    # Backups themselves must stay under the managed home tree.
    assert_path_inside(root, player_home(environ), label="backup root")
    return backup_existing_files(paths, backup_root=root, label=label)


def restore_managed_backup(
    backup: str | Path | BackupRecord,
    *,
    expected_campaign: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[Path]:
    """Restore a campaign backup only when every path stays managed."""
    if isinstance(backup, BackupRecord):
        record = backup
        backup_dir = Path(record.backup_directory)
    else:
        backup_dir = Path(backup).expanduser().resolve(strict=False)
        manifest = backup_dir / "backup.json" if backup_dir.is_dir() else backup_dir
        if not manifest.is_file():
            raise PackagingError(f"Backup manifest not found: {manifest}")
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
        record = BackupRecord(
            backup_directory=str(payload["backup_directory"]),
            files=dict(payload["files"]),
            created_at_utc=str(payload["created_at_utc"]),
        )
        backup_dir = Path(record.backup_directory)

    home = player_home(environ)
    assert_path_inside(backup_dir, home, label="backup directory")
    managed = managed_campaigns_root(environ)
    for original in record.files:
        destination = Path(original)
        assert_path_inside(destination, managed, label="restore destination")
        if expected_campaign is not None:
            expected = Path(expected_campaign).expanduser().resolve(strict=False)
            if expected.is_dir():
                expected_file = expected / CAMPAIGN_FILE_NAME
            else:
                expected_file = expected
            # Only the campaign authority file is required to match; snapshot/commands
            # ride alongside it in the same directory.
            if destination.name == CAMPAIGN_FILE_NAME and destination.resolve(
                strict=False
            ) != expected_file.resolve(strict=False):
                raise PackagingError(
                    f"Backup belongs to {destination}, not expected campaign "
                    f"{expected_file}"
                )
    return restore_backup(record)


def reset_test_campaign(
    campaign_path: str | Path | None = None,
    *,
    scenario_id: str = "earth3_v1",
    environ: Mapping[str, str] | None = None,
    create_backup: bool = True,
) -> dict[str, Any]:
    """Delete a managed test campaign directory after an optional backup.

    Refuses to touch anything outside ``<player home>/campaigns/``.
    """
    paths = resolve_campaign_paths(campaign_path, scenario_id=scenario_id, environ=environ)
    managed = managed_campaigns_root(environ)
    directory = assert_path_inside(paths.root, managed, label="campaign directory")
    backup_record = None
    if create_backup and paths.campaign.is_file():
        backup_record = backup_managed_campaign(
            paths.campaign, environ=environ, label="reset-test-campaign"
        )
    if directory.exists():
        # Remove only known product files first; then the directory if empty of
        # unexpected content, otherwise refuse to wipe unknown files.
        known = {
            paths.campaign.name,
            paths.snapshot.name,
            paths.commands.name,
        }
        leftovers = [
            child
            for child in directory.iterdir()
            if child.name not in known and child.name != ".gitkeep"
        ]
        if leftovers:
            raise PackagingError(
                "Refusing to reset campaign directory with unexpected files: "
                + ", ".join(sorted(item.name for item in leftovers[:8]))
            )
        for child in list(directory.iterdir()):
            if child.is_file():
                child.unlink()
        try:
            directory.rmdir()
        except OSError:
            pass
    return {
        "ok": True,
        "campaign_directory": str(directory),
        "backup_directory": (
            None if backup_record is None else backup_record.backup_directory
        ),
        "reset_at_utc": datetime.now(UTC).isoformat(),
    }


def packaging_application_fields(
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Fields merged into the Godot application identity block."""
    identity = package_identity(root=root, environ=environ)
    return {
        "version": identity.version,
        "source_commit": identity.source_commit,
        "source_commit_short": identity.source_commit_short,
        "package_root": identity.package_root,
    }


def _is_commit_sha(value: str) -> bool:
    if len(value) != 40:
        return False
    return all(character in "0123456789abcdef" for character in value)
