from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Iterator

from .expanded_nations_models import (
    ExpandedNationsError,
    MANIFEST_RELATIVE,
    all_managed_candidates,
    pretty_json,
    safe_target,
    sha256_bytes,
)
from .expanded_nations_transaction import (
    atomic_write,
    recover_interrupted_deactivation,
    replace_path,
    unlink_path,
)
from .expanded_nations_verify import load_manifest, verify_manifest_files

_COMPILE_SUSPEND_SCHEMA = "gates-of-codex.expanded-nations-compile-suspend"
_COMPILE_SUSPEND_VERSION = 1
_COMPILE_SUSPEND_SUFFIX = ".goc-compile-suspended"
_COMPILE_SUSPEND_RELATIVE = Path("live/expanded_nations/compile-suspend.json")


@contextmanager
def clean_compile_source_view(gates_root: str | Path) -> Iterator[None]:
    """Temporarily remove the verified active projection from compiler inputs.

    The faction compiler, catalog, effective-definition index, research index,
    and stack hasher all traverse the final Gates resource layer. Moving the
    active generated files to non-runtime suffixes guarantees that every one of
    those consumers sees the same clean source tree as Core mode. A journal is
    written before the first move so an interrupted process can recover the
    prior active projection on the next command.
    """

    root = Path(gates_root).expanduser().resolve()
    recover_interrupted_compile(root)
    manifest_path = root / MANIFEST_RELATIVE
    if not manifest_path.is_file():
        occupied = [path for path in all_managed_candidates(root) if path.is_file()]
        if occupied:
            raise ExpandedNationsError(
                "Expanded Nations compile refuses unmanaged activation-path files without a manifest: "
                + ", ".join(str(path) for path in occupied)
            )
        yield
        return

    manifest = load_manifest(manifest_path)
    verify_manifest_files(root, manifest)
    journal_path = root / _COMPILE_SUSPEND_RELATIVE
    if journal_path.exists():
        raise ExpandedNationsError(f"Compile-suspension journal already exists: {journal_path}")

    rows: list[dict[str, object]] = []
    for row in manifest["files"]:
        relative = str(row["relative_path"])
        target = safe_target(root, relative)
        suspended = _suspended_path(target)
        if suspended.exists():
            raise ExpandedNationsError(f"Stale compile-suspended file exists: {suspended}")
        rows.append(
            {
                "relative_path": relative,
                "sha256": str(row["sha256"]),
                "byte_count": int(row["byte_count"]),
            }
        )
    journal = {
        "schema": _COMPILE_SUSPEND_SCHEMA,
        "schema_version": _COMPILE_SUSPEND_VERSION,
        "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        "files": rows,
    }
    atomic_write(journal_path, pretty_json(journal).encode("utf-8"))

    try:
        for row in rows:
            target = safe_target(root, str(row["relative_path"]))
            replace_path(target, _suspended_path(target))
        yield
    finally:
        _restore_compile_suspension(root, journal_path, journal)


def recover_interrupted_compile(gates_root: str | Path) -> None:
    root = Path(gates_root).expanduser().resolve()
    recover_interrupted_deactivation(root)
    journal_path = root / _COMPILE_SUSPEND_RELATIVE
    if not journal_path.is_file():
        stray = [
            _suspended_path(path)
            for path in all_managed_candidates(root)
            if _suspended_path(path).exists()
        ]
        if stray:
            raise ExpandedNationsError(
                "Compile-suspended files exist without a recovery journal: "
                + ", ".join(str(path) for path in stray)
            )
        return
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpandedNationsError(f"Invalid compile-suspension journal: {journal_path}") from exc
    _validate_journal(journal)
    _restore_compile_suspension(root, journal_path, journal)


def _restore_compile_suspension(
    root: Path,
    journal_path: Path,
    journal: dict[str, object],
) -> None:
    _validate_journal(journal)
    manifest_path = root / MANIFEST_RELATIVE
    if not manifest_path.is_file():
        raise ExpandedNationsError(
            "Cannot recover compile suspension because the activation manifest is missing"
        )
    expected_manifest_hash = str(journal["manifest_sha256"])
    if sha256_bytes(manifest_path.read_bytes()) != expected_manifest_hash:
        raise ExpandedNationsError(
            "Cannot recover compile suspension because the activation manifest changed"
        )

    for row in journal["files"]:  # type: ignore[index]
        relative = str(row["relative_path"])
        target = safe_target(root, relative)
        suspended = _suspended_path(target)
        target_exists = target.is_file()
        suspended_exists = suspended.is_file()
        if target_exists and suspended_exists:
            raise ExpandedNationsError(
                f"Compile recovery found both active and suspended copies: {target}"
            )
        if not target_exists and suspended_exists:
            replace_path(suspended, target)
        elif not target_exists:
            raise ExpandedNationsError(f"Compile recovery cannot restore missing file: {target}")
        data = target.read_bytes()
        if sha256_bytes(data) != str(row["sha256"]) or len(data) != int(row["byte_count"]):
            raise ExpandedNationsError(f"Compile recovery restored unexpected bytes: {target}")

    verify_manifest_files(root, load_manifest(manifest_path))
    unlink_path(journal_path)


def _validate_journal(journal: object) -> None:
    if not isinstance(journal, dict):
        raise ExpandedNationsError("Compile-suspension journal is not an object")
    if (
        journal.get("schema") != _COMPILE_SUSPEND_SCHEMA
        or journal.get("schema_version") != _COMPILE_SUSPEND_VERSION
    ):
        raise ExpandedNationsError("Unsupported compile-suspension journal")
    rows = journal.get("files")
    if not isinstance(rows, list) or not rows:
        raise ExpandedNationsError("Compile-suspension journal has no files")
    for row in rows:
        if not isinstance(row, dict):
            raise ExpandedNationsError("Compile-suspension journal has an invalid file row")
        if not isinstance(row.get("relative_path"), str) or not row["relative_path"]:
            raise ExpandedNationsError("Compile-suspension journal has an invalid path")
        if not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64:
            raise ExpandedNationsError("Compile-suspension journal has an invalid checksum")
        if not isinstance(row.get("byte_count"), int) or int(row["byte_count"]) < 0:
            raise ExpandedNationsError("Compile-suspension journal has an invalid byte count")


def _suspended_path(path: Path) -> Path:
    return path.with_name(path.name + _COMPILE_SUSPEND_SUFFIX)
