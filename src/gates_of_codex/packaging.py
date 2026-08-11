"""P6 packaging identity: version, source commit, and managed campaign roots.

Python remains the sole campaign authority. This module never invents campaign
state; it only derives package provenance and contains restore/reset to the
player-managed campaign tree.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from . import __version__ as PACKAGE_VERSION
from .acceptance import BackupRecord, backup_existing_files
from .player_shell import (
    CAMPAIGN_FILE_NAME,
    COMMANDS_FILE_NAME,
    SNAPSHOT_FILE_NAME,
    clear_last_campaign_if_matches,
    player_home,
    resolve_campaign_paths,
)
from .state_io import load_campaign


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


@dataclass(frozen=True, slots=True)
class ManagedRestorePlan:
    backup_directory: Path
    campaign_directory: Path
    campaign_file: Path
    staged_files: tuple[tuple[Path, str], ...]
    created_at_utc: str


def application_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("gates-of-codex")
    except Exception:  # noqa: BLE001 - fall back to package constant
        return str(PACKAGE_VERSION)


def package_root(start: str | Path | None = None) -> Path:
    """Return the repository or installed package root used for provenance."""
    if start is not None:
        return Path(start)
    # A source module resolves to the checkout; installed and frozen modules
    # resolve to the package directory containing the embedded stamp.
    here = Path(__file__).resolve()
    candidate = here.parents[2]
    if _is_source_checkout(candidate):
        return candidate
    return here.parent


def _is_source_checkout(root: Path) -> bool:
    return (root / "pyproject.toml").is_file() and (root / ".git").exists()


def resolve_source_commit(
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Derive the exact source commit for display and evidence.

    Packaged installs and frozen applications require an adjacent
    ``SOURCE_COMMIT``. Source checkouts may use the environment as a test seam,
    then fall back to ``git rev-parse HEAD``.
    """
    root_path = package_root(root)
    marker = root_path / PROVENANCE_FILE_NAME
    if marker.is_file():
        value = marker.read_text(encoding="utf-8-sig").strip().lower()
        if not _is_commit_sha(value):
            raise PackagingError(
                f"{marker} must contain a 40-character lowercase hex commit"
            )
        return value

    if not _is_source_checkout(root_path):
        raise PackagingError(
            f"Installed package is missing embedded {PROVENANCE_FILE_NAME}: {root_path}"
        )
    test_value = str(
        (os.environ if environ is None else environ).get(PROVENANCE_ENV, "")
    ).strip().lower()
    if test_value:
        if not _is_commit_sha(test_value):
            raise PackagingError(
                f"{PROVENANCE_ENV} must be a 40-character lowercase hex commit"
            )
        return test_value
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


_BACKUP_MANIFEST_NAME = "backup.json"
_KNOWN_CAMPAIGN_FILES = (
    CAMPAIGN_FILE_NAME,
    SNAPSHOT_FILE_NAME,
    COMMANDS_FILE_NAME,
)


def _absolute_path(value: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(value))))


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _lstat_without_reparse(path: Path, *, label: str) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise PackagingError(f"{label} is unavailable: {path}: {exc}") from exc
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    if stat.S_ISLNK(metadata.st_mode) or (reparse_flag and attributes & reparse_flag):
        raise PackagingError(f"{label} must not be a symlink or reparse point: {path}")
    return metadata


def _assert_no_reparse_components(path: Path, *, label: str) -> None:
    """Reject an existing symlink/junction anywhere in an input spelling."""
    current = _absolute_path(path)
    chain: list[Path] = []
    while current != current.parent:
        chain.append(current)
        current = current.parent
    chain.append(current)
    for component in reversed(chain):
        if _path_lexists(component):
            _lstat_without_reparse(component, label=label)


def _require_directory(path: Path, *, label: str) -> os.stat_result:
    metadata = _lstat_without_reparse(path, label=label)
    if not stat.S_ISDIR(metadata.st_mode):
        raise PackagingError(f"{label} must be a directory: {path}")
    return metadata


def _require_regular_file(path: Path, *, label: str) -> os.stat_result:
    metadata = _lstat_without_reparse(path, label=label)
    if not stat.S_ISREG(metadata.st_mode):
        raise PackagingError(f"{label} must be a regular file: {path}")
    return metadata


def _read_regular_bytes(path: Path, *, label: str) -> bytes:
    before = _require_regular_file(path, label=label)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise PackagingError(f"Unable to read {label}: {path}: {exc}") from exc
    after = _require_regular_file(path, label=label)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or len(payload) != after.st_size:
        raise PackagingError(f"{label} changed while it was being read: {path}")
    return payload


def _strict_json_object(raw: str, *, manifest: Path) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise PackagingError(
                    f"Backup manifest contains duplicate JSON key {key!r}: {manifest}"
                )
            value[key] = item
        return value

    try:
        payload = json.loads(raw, object_pairs_hook=pairs_hook)
    except PackagingError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PackagingError(f"Backup manifest is malformed: {manifest}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PackagingError(f"Backup manifest must be a JSON object: {manifest}")
    return payload


def _canonical_campaign_file(
    campaign_path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    lexical_managed_root = player_home(environ) / MANAGED_CAMPAIGNS_DIRNAME
    _assert_no_reparse_components(
        lexical_managed_root, label="managed campaigns root"
    )
    raw = Path(campaign_path).expanduser()
    raw_file = raw if raw.suffix.lower() == ".json" else raw / CAMPAIGN_FILE_NAME
    _assert_no_reparse_components(raw_file.parent, label="live campaign directory")
    if _path_lexists(_absolute_path(raw_file)):
        _lstat_without_reparse(_absolute_path(raw_file), label="live campaign file")
    campaign = raw_file.resolve(strict=False)
    if campaign.name != CAMPAIGN_FILE_NAME:
        raise PackagingError(
            f"Managed campaign file must be named {CAMPAIGN_FILE_NAME}: {campaign}"
        )
    assert_path_inside(
        campaign.parent,
        lexical_managed_root.resolve(strict=False),
        label="campaign directory",
    )
    return campaign


def _validated_created_at(value: Any, *, manifest: Path) -> str:
    created = value if isinstance(value, str) else ""
    if not created:
        raise PackagingError(f"Backup manifest has invalid created_at_utc: {manifest}")
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PackagingError(
            f"Backup manifest has invalid created_at_utc: {manifest}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise PackagingError(f"Backup manifest created_at_utc is not UTC: {manifest}")
    if created != parsed.isoformat():
        raise PackagingError(
            f"Backup manifest created_at_utc is not canonical: {manifest}"
        )
    return created


def _build_restore_plan(
    backup: str | Path | BackupRecord,
    *,
    expected_campaign: str | Path,
    environ: Mapping[str, str] | None = None,
) -> ManagedRestorePlan:
    selected = backup.backup_directory if isinstance(backup, BackupRecord) else backup
    raw_selected = _absolute_path(selected)
    if raw_selected.name == _BACKUP_MANIFEST_NAME:
        manifest = raw_selected
        raw_backup_directory = raw_selected.parent
    else:
        raw_backup_directory = raw_selected
        manifest = raw_backup_directory / _BACKUP_MANIFEST_NAME

    _assert_no_reparse_components(
        raw_backup_directory, label="backup directory"
    )
    _require_directory(raw_backup_directory, label="backup directory")
    _require_regular_file(manifest, label="backup manifest")
    backup_directory = raw_backup_directory.resolve(strict=True)
    assert_path_inside(
        backup_directory, player_home(environ), label="backup directory"
    )
    raw_manifest = _read_regular_bytes(manifest, label="backup manifest")
    try:
        manifest_text = raw_manifest.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise PackagingError(f"Backup manifest is not strict UTF-8: {manifest}") from exc
    payload = _strict_json_object(manifest_text, manifest=manifest)
    expected_keys = {"backup_directory", "files", "created_at_utc"}
    if set(payload) != expected_keys:
        raise PackagingError(
            f"Backup manifest fields must be exactly {sorted(expected_keys)}: {manifest}"
        )

    declared_text = payload["backup_directory"]
    if not isinstance(declared_text, str) or not declared_text.strip():
        raise PackagingError(f"Backup manifest has invalid backup_directory: {manifest}")
    declared = _absolute_path(declared_text)
    _assert_no_reparse_components(declared, label="declared backup directory")
    _require_directory(declared, label="declared backup directory")
    if declared.resolve(strict=True) != backup_directory:
        raise PackagingError(
            f"Backup manifest directory does not match its parent: {declared} != "
            f"{backup_directory}"
        )

    campaign_file = _canonical_campaign_file(
        expected_campaign, environ=environ
    )
    campaign_directory = campaign_file.parent
    _require_directory(campaign_directory, label="live campaign directory")

    files = payload["files"]
    if not isinstance(files, dict):
        raise PackagingError(f"Backup manifest files must be an object: {manifest}")
    staged_files: list[tuple[Path, str]] = []
    seen_destinations: set[str] = set()
    seen_sources: set[Path] = set()
    for destination_text, source_text in files.items():
        if not isinstance(destination_text, str) or not isinstance(source_text, str):
            raise PackagingError(f"Backup manifest paths must be strings: {manifest}")
        destination = _absolute_path(destination_text).resolve(strict=False)
        destination_name = destination.name
        if destination_name not in _KNOWN_CAMPAIGN_FILES:
            raise PackagingError(
                f"Backup manifest contains unexpected destination: {destination}"
            )
        expected_destination = (
            campaign_directory / destination_name
        ).resolve(strict=False)
        if destination != expected_destination:
            raise PackagingError(
                f"Backup destination is not in the expected campaign directory: "
                f"{destination}"
            )
        if destination_name in seen_destinations:
            raise PackagingError(
                f"Backup manifest aliases destination {destination_name}: {manifest}"
            )
        seen_destinations.add(destination_name)

        raw_source = _absolute_path(source_text)
        _assert_no_reparse_components(raw_source, label="backup source")
        _require_regular_file(raw_source, label="backup source")
        source = raw_source.resolve(strict=True)
        if source.parent != backup_directory:
            raise PackagingError(
                f"Backup source is not a direct child of {backup_directory}: {source}"
            )
        if source in seen_sources:
            raise PackagingError(f"Backup manifest aliases source file: {source}")
        seen_sources.add(source)
        staged_files.append((source, destination_name))

    if sum(name == CAMPAIGN_FILE_NAME for _, name in staged_files) != 1:
        raise PackagingError(
            f"Backup manifest must contain exactly one {CAMPAIGN_FILE_NAME}: {manifest}"
        )
    return ManagedRestorePlan(
        backup_directory=backup_directory,
        campaign_directory=campaign_directory,
        campaign_file=campaign_file,
        staged_files=tuple(staged_files),
        created_at_utc=_validated_created_at(payload["created_at_utc"], manifest=manifest),
    )


def latest_managed_backup(
    campaign_path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    campaign = _canonical_campaign_file(campaign_path, environ=environ)
    candidates: list[tuple[str, str, ManagedRestorePlan]] = []
    root = managed_backups_root(environ)
    if not root.is_dir():
        return None
    for child in root.iterdir():
        try:
            plan = _build_restore_plan(
                child, expected_campaign=campaign, environ=environ
            )
        except (OSError, ValueError, KeyError, PackagingError, json.JSONDecodeError):
            continue
        candidates.append((plan.created_at_utc, child.name, plan))
    if not candidates:
        return None
    plan = max(candidates, key=lambda row: (row[0], row[1]))[2]
    return {
        "backup_directory": str(plan.backup_directory),
        "campaign_path": str(plan.campaign_file),
        "created_at_utc": plan.created_at_utc,
    }


def _capture_known_tree(directory: Path) -> tuple[tuple[str, bytes], ...]:
    _require_directory(directory, label="campaign tree")
    captured: list[tuple[str, bytes]] = []
    try:
        children = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise PackagingError(f"Unable to enumerate campaign tree {directory}: {exc}") from exc
    for child in children:
        if child.name not in _KNOWN_CAMPAIGN_FILES:
            raise PackagingError(
                f"Campaign tree contains unexpected entry: {child.name}"
            )
        captured.append(
            (child.name, _read_regular_bytes(child, label="campaign tree file"))
        )
    return tuple(captured)


def _assert_tree_matches_plan(stage: Path, plan: ManagedRestorePlan) -> None:
    actual = _capture_known_tree(stage)
    expected = tuple(
        sorted(
            (
                name,
                _read_regular_bytes(source, label="backup source"),
            )
            for source, name in plan.staged_files
        )
    )
    if actual != expected:
        raise PackagingError("Staged restore bytes do not match authenticated backup")


def _replace_directory(source: Path, destination: Path) -> None:
    source.replace(destination)


def _remove_sibling_directory(path: Path, *, parent: Path, label: str) -> None:
    raw = _absolute_path(path)
    expected_parent = _absolute_path(parent)
    if raw.parent != expected_parent:
        raise PackagingError(
            f"Refusing to remove {label} outside campaign parent {expected_parent}: {raw}"
        )
    _assert_no_reparse_components(expected_parent, label="campaign parent")
    _require_directory(expected_parent, label="campaign parent")
    _require_directory(raw, label=label)
    shutil.rmtree(raw)


def restore_managed_backup(
    backup: str | Path | BackupRecord | None = None,
    *,
    expected_campaign: str | Path,
    environ: Mapping[str, str] | None = None,
) -> list[Path]:
    """Validate, stage, and atomically publish a whole managed campaign tree."""
    selected: str | Path | BackupRecord | None = backup
    if selected is None:
        descriptor = latest_managed_backup(expected_campaign, environ=environ)
        if descriptor is None:
            raise PackagingError("No authenticated backup exists for this campaign")
        selected = descriptor["backup_directory"]
    plan = _build_restore_plan(
        selected, expected_campaign=expected_campaign, environ=environ
    )
    live = plan.campaign_directory
    try:
        stage = Path(
            tempfile.mkdtemp(prefix=f".{live.name}.restore-", dir=live.parent)
        )
    except OSError as exc:
        raise PackagingError(f"Unable to create restore stage beside {live}: {exc}") from exc
    rollback = live.parent / f".{live.name}.rollback-{uuid.uuid4().hex}"
    primary_error: Exception | None = None
    try:
        _require_directory(stage, label="restore stage")
        if _path_lexists(rollback):
            raise PackagingError(f"Restore rollback path already exists: {rollback}")
        live_before = _capture_known_tree(live)
        try:
            for source, name in plan.staged_files:
                shutil.copy2(source, stage / name)
            load_campaign(stage / CAMPAIGN_FILE_NAME)
            _assert_tree_matches_plan(stage, plan)
        except PackagingError:
            raise
        except Exception as exc:
            raise PackagingError(f"Restore staging failed: {exc}") from exc

        try:
            _replace_directory(live, rollback)
        except Exception as exc:
            raise PackagingError(f"Unable to preserve live campaign: {exc}") from exc
        try:
            _require_directory(rollback, label="restore rollback")
            _replace_directory(stage, live)
        except Exception as publish_error:
            try:
                _require_directory(rollback, label="restore rollback")
                _replace_directory(rollback, live)
            except Exception as rollback_error:
                raise PackagingError(
                    f"Restore publication failed: {publish_error}; rollback failed: "
                    f"{rollback_error}; original tree retained at {rollback}"
                ) from rollback_error
            if _capture_known_tree(live) != live_before:
                raise PackagingError(
                    "Restore publication failed and rollback bytes differ"
                ) from publish_error
            raise PackagingError(
                f"Restore publication failed: {publish_error}"
            ) from publish_error
        _remove_sibling_directory(
            rollback, parent=live.parent, label="restore rollback"
        )
        return [
            (live / name).resolve(strict=False)
            for name in _KNOWN_CAMPAIGN_FILES
            if (live / name).is_file()
        ]
    except Exception as exc:
        primary_error = exc
        raise
    finally:
        if _path_lexists(stage):
            try:
                _remove_sibling_directory(
                    stage, parent=live.parent, label="restore stage"
                )
            except Exception as cleanup_error:
                if primary_error is None:
                    raise PackagingError(
                        f"Unable to remove restore stage {stage}: {cleanup_error}"
                    ) from cleanup_error
                primary_error.add_note(
                    f"Restore stage cleanup also failed at {stage}: {cleanup_error}"
                )


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
        except OSError as exc:
            raise PackagingError(
                f"Unable to remove managed campaign directory {directory}: {exc}"
            ) from exc
    campaign_deleted = not directory.exists()
    if not campaign_deleted:
        raise PackagingError(f"Managed campaign directory still exists: {directory}")
    last_campaign_cleared = clear_last_campaign_if_matches(
        paths.campaign, environ=environ
    )
    return {
        "ok": True,
        "campaign_directory": str(directory),
        "backup_directory": (
            None if backup_record is None else backup_record.backup_directory
        ),
        "campaign_deleted": True,
        "next_player_state": "new_campaign",
        "last_campaign_cleared": last_campaign_cleared,
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
