from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .expanded_nations_models import (
    ExpandedNationsError,
    GENERATED_MARKER,
    MANIFEST_RELATIVE,
    all_managed_candidates,
    safe_target,
)
from .expanded_nations_verify import (
    load_manifest,
    verify_actor_projection_files,
    verify_manifest_files,
    verify_projection_artifacts,
)

_DEACTIVATE_SUFFIX = ".goc-deactivate"
_STAGE_SUFFIX = ".goc-stage"


def install_projection(
    root: Path,
    outputs: Mapping[Path, bytes],
    manifest_bytes: bytes,
    *,
    post_commit_verify: Callable[[], Any] | None = None,
) -> None:
    recover_interrupted_deactivation(root)
    verify_projection_artifacts(outputs, json.loads(manifest_bytes.decode("utf-8-sig")))
    manifest_path = root / MANIFEST_RELATIVE
    previous_manifest_bytes: bytes | None = None
    previous_files: dict[Path, bytes] = {}
    if manifest_path.is_file():
        previous_manifest_bytes = manifest_path.read_bytes()
        previous_manifest = load_manifest(manifest_path)
        verify_manifest_files(root, previous_manifest)
        for row in previous_manifest["files"]:
            relative = Path(str(row["relative_path"]))
            previous_files[relative] = safe_target(root, relative.as_posix()).read_bytes()
    else:
        occupied = [path for path in all_managed_candidates(root) if path.is_file()]
        if occupied:
            raise ExpandedNationsError(
                "Expanded Nations activation refuses to overwrite unmanaged final-layer files: "
                + ", ".join(str(path) for path in occupied)
            )
    for relative in outputs:
        target = safe_target(root, relative.as_posix())
        if target.is_file() and relative not in previous_files:
            raise ExpandedNationsError(
                f"Expanded Nations activation refuses to overwrite an unmanaged destination: {target}"
            )

    staged: dict[Path, Path] = {}
    manifest_stage: Path | None = None
    try:
        for relative, data in sorted(outputs.items(), key=lambda item: item[0].as_posix()):
            target = safe_target(root, relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = target.with_name(target.name + _STAGE_SUFFIX)
            if stage.exists():
                raise ExpandedNationsError(f"Stale activation stage exists: {stage}")
            stage.write_bytes(data)
            staged[target] = stage
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_stage = manifest_path.with_name(manifest_path.name + _STAGE_SUFFIX)
        if manifest_stage.exists():
            raise ExpandedNationsError(f"Stale activation stage exists: {manifest_stage}")
        manifest_stage.write_bytes(manifest_bytes)
        for target, stage in sorted(staged.items(), key=lambda item: str(item[0])):
            replace_path(stage, target)
        for stale in sorted(set(previous_files) - set(outputs), key=lambda path: path.as_posix()):
            unlink_path(safe_target(root, stale.as_posix()))
        replace_path(manifest_stage, manifest_path)
        if post_commit_verify is not None:
            post_commit_verify()
    except Exception as exc:
        rollback_errors: list[str] = []
        for stage in [*staged.values(), manifest_stage]:
            if stage is not None and stage.exists():
                try:
                    unlink_path(stage)
                except Exception as rollback_exc:
                    rollback_errors.append(f"stage cleanup {stage}: {rollback_exc}")
        for relative in sorted(set(outputs) | set(previous_files), key=lambda path: path.as_posix()):
            target = safe_target(root, relative.as_posix())
            try:
                if relative in previous_files:
                    atomic_write(target, previous_files[relative])
                elif target.exists():
                    unlink_path(target)
            except Exception as rollback_exc:
                rollback_errors.append(f"file rollback {target}: {rollback_exc}")
        try:
            if previous_manifest_bytes is None:
                if manifest_path.exists():
                    unlink_path(manifest_path)
            else:
                atomic_write(manifest_path, previous_manifest_bytes)
        except Exception as rollback_exc:
            rollback_errors.append(f"manifest rollback {manifest_path}: {rollback_exc}")
        if rollback_errors:
            raise ExpandedNationsError(
                f"Projection installation failed ({exc}); rollback also failed: "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def deactivate_actor_projection(gates_root: str | Path) -> bool:
    root = Path(gates_root).expanduser().resolve()
    recover_interrupted_deactivation(root)
    manifest_path = root / MANIFEST_RELATIVE
    if not manifest_path.is_file():
        unexpected = [
            path for path in all_managed_candidates(root)
            if path.is_file() and GENERATED_MARKER in path.read_text(encoding="utf-8-sig", errors="replace")
        ]
        if unexpected:
            raise ExpandedNationsError(
                "Managed-looking Expanded Nations files exist without an activation manifest: "
                + ", ".join(str(path) for path in unexpected)
            )
        return False

    manifest = verify_actor_projection_files(root)
    relatives = [Path(str(row["relative_path"])) for row in manifest["files"]]
    managed_paths = [safe_target(root, relative.as_posix()) for relative in relatives]
    manifest_backup = backup_path(manifest_path)
    file_backups = [backup_path(path) for path in managed_paths]
    try:
        for path, backup in zip(managed_paths, file_backups, strict=True):
            write_backup(path, backup)
        write_backup(manifest_path, manifest_backup)
        for path in managed_paths:
            unlink_path(path)
        unlink_path(manifest_path)
        unlink_path(manifest_backup)
    except Exception:
        recover_interrupted_deactivation(root)
        raise

    for backup in file_backups:
        if not backup.exists():
            continue
        try:
            unlink_path(backup)
        except Exception:
            recover_interrupted_deactivation(root)
            if backup.exists():
                raise
    prune_empty_directories(root, relatives)
    return True


def recover_interrupted_deactivation(root: Path) -> None:
    manifest_path = root / MANIFEST_RELATIVE
    manifest_backup = backup_path(manifest_path)
    pairs = [(path, backup_path(path)) for path in all_managed_candidates(root)]
    for stage in [backup_stage_path(path) for path in [manifest_path, *all_managed_candidates(root)]]:
        if stage.exists():
            unlink_path(stage)
    existing = [(path, backup) for path, backup in pairs if backup.exists()]
    if not manifest_backup.exists() and not existing:
        return

    if manifest_backup.exists():
        manifest_bytes = manifest_backup.read_bytes()
        if manifest_path.exists() and manifest_path.read_bytes() != manifest_bytes:
            raise ExpandedNationsError("Interrupted deactivation manifest conflicts with active manifest")
        if not manifest_path.exists():
            atomic_write(manifest_path, manifest_bytes)
        manifest = load_manifest(manifest_path)
        for row in manifest["files"]:
            target = safe_target(root, str(row["relative_path"]))
            backup = backup_path(target)
            if target.exists():
                if backup.exists() and target.read_bytes() != backup.read_bytes():
                    raise ExpandedNationsError(f"Interrupted deactivation backup conflicts with {target}")
            elif backup.exists():
                atomic_write(target, backup.read_bytes())
            else:
                raise ExpandedNationsError(f"Interrupted deactivation cannot restore {target}")
        verify_manifest_files(root, manifest)
        for _, backup in pairs:
            if backup.exists():
                unlink_path(backup)
        unlink_path(manifest_backup)
        return

    if manifest_path.exists():
        manifest = load_manifest(manifest_path)
        managed = {safe_target(root, str(row["relative_path"])) for row in manifest["files"]}
        for target, backup in existing:
            if target not in managed:
                raise ExpandedNationsError(f"Unexpected deactivation backup: {backup}")
            if target.exists():
                if target.read_bytes() != backup.read_bytes():
                    raise ExpandedNationsError(f"Deactivation backup conflicts with {target}")
            else:
                atomic_write(target, backup.read_bytes())
            unlink_path(backup)
        verify_manifest_files(root, manifest)
        return

    for _, backup in existing:
        unlink_path(backup)


def write_backup(source: Path, backup: Path) -> None:
    if backup.exists():
        raise ExpandedNationsError(f"Deactivation backup already exists: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    stage = backup_stage_path(source)
    if stage.exists():
        raise ExpandedNationsError(f"Deactivation backup stage already exists: {stage}")
    stage.write_bytes(source.read_bytes())
    replace_path(stage, backup)


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + _DEACTIVATE_SUFFIX)


def backup_stage_path(path: Path) -> Path:
    backup = backup_path(path)
    return backup.with_name(backup.name + _STAGE_SUFFIX)


def atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(target.name + ".goc-restore")
    if stage.exists():
        unlink_path(stage)
    stage.write_bytes(data)
    replace_path(stage, target)


def replace_path(source: Path, target: Path) -> None:
    os.replace(source, target)


def unlink_path(path: Path) -> None:
    path.unlink()


def prune_empty_directories(root: Path, relatives: Sequence[Path]) -> None:
    stop = root.resolve()
    for relative in relatives:
        current = (root / relative).parent
        while current != stop and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
