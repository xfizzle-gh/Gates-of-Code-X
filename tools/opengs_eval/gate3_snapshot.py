#!/usr/bin/env python3
"""Cross-platform immutable tree capture for the isolated Gate 3 package."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable


def _read_regular_bytes(path: Path, relative: str, error_type: type[Exception]) -> bytes:
    """Read one regular file without treating mutable filesystem metadata as authority."""
    try:
        path_before = path.lstat()
    except OSError as exc:
        raise error_type(f"cannot inspect snapshot file {relative}: {exc}") from exc
    if stat.S_ISLNK(path_before.st_mode) or not stat.S_ISREG(path_before.st_mode):
        raise error_type(f"snapshot contains nonregular entry: {relative}")

    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise error_type(f"cannot capture snapshot file {relative}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise error_type(f"snapshot contains nonregular entry: {relative}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        data = b"".join(chunks)
        if not stat.S_ISREG(after.st_mode):
            raise error_type(f"snapshot file type changed during capture: {relative}")
        if before.st_size != after.st_size or after.st_size != len(data):
            raise error_type(f"snapshot file size changed during capture: {relative}")
    finally:
        os.close(fd)

    try:
        path_after = path.lstat()
    except OSError as exc:
        raise error_type(f"snapshot file disappeared during capture: {relative}: {exc}") from exc
    if stat.S_ISLNK(path_after.st_mode) or not stat.S_ISREG(path_after.st_mode):
        raise error_type(f"snapshot file path changed to a nonregular entry: {relative}")
    if path_after.st_size != len(data):
        raise error_type(f"snapshot file path size changed during capture: {relative}")
    return data


def _capture_once(root: Path, error_type: type[Exception]) -> tuple[dict[str, bytes], set[str]]:
    if not root.is_dir() or root.is_symlink():
        raise error_type(f"snapshot root must be a regular directory: {root}")
    files: dict[str, bytes] = {}
    directories: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError as exc:
            raise error_type(f"cannot scan snapshot directory {current}: {exc}") from exc
        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise error_type(f"cannot inspect snapshot entry {relative}: {exc}") from exc
            if stat.S_ISLNK(info.st_mode):
                raise error_type(f"snapshot contains symlink: {relative}")
            if stat.S_ISDIR(info.st_mode):
                directories.add(relative)
                child_directories.append(path)
            elif stat.S_ISREG(info.st_mode):
                files[relative] = _read_regular_bytes(path, relative, error_type)
            else:
                raise error_type(f"snapshot contains nonregular entry: {relative}")
        # Reverse because the stack is LIFO; this keeps traversal lexical without
        # relying on the platform's native directory iteration order.
        stack.extend(reversed(child_directories))
    return files, directories


def install_stable_capture(package: Any) -> tuple[Callable[[Path], Any], Callable[[Path, Callable[[Path], None]], Any]]:
    """Install a two-capture byte contract into ``gate3_package``.

    Device IDs, inode values, directory mtimes, and file mtimes are deliberately
    excluded from authority. Two complete captures must instead agree on every
    path, entry type, directory membership, and file byte. The returned snapshot
    is detached immutable data and is the only authority used for inspection and
    publication.
    """

    def capture_tree_with_hook(
        root: Path,
        between_captures: Callable[[Path], None] | None = None,
    ) -> Any:
        root = Path(root)
        first_files, first_directories = _capture_once(root, package.Gate3Error)
        if between_captures is not None:
            between_captures(root)
        second_files, second_directories = _capture_once(root, package.Gate3Error)

        if first_directories != second_directories:
            raise package.Gate3Error(
                "snapshot directory membership changed during capture: "
                f"removed={sorted(first_directories - second_directories)} "
                f"added={sorted(second_directories - first_directories)}"
            )
        first_paths = set(first_files)
        second_paths = set(second_files)
        if first_paths != second_paths:
            raise package.Gate3Error(
                "snapshot file membership changed during capture: "
                f"removed={sorted(first_paths - second_paths)} "
                f"added={sorted(second_paths - first_paths)}"
            )
        for relative in sorted(first_paths):
            if first_files[relative] != second_files[relative]:
                raise package.Gate3Error(
                    f"snapshot file bytes changed during capture: {relative}"
                )

        return package.TreeSnapshot(
            files=MappingProxyType(dict(first_files)),
            sha256=MappingProxyType(
                {
                    relative: package.sha256_bytes(data)
                    for relative, data in first_files.items()
                }
            ),
            directories=frozenset(first_directories),
        )

    def capture_tree(root: Path) -> Any:
        return capture_tree_with_hook(root)

    package.capture_tree = capture_tree
    return capture_tree, capture_tree_with_hook


__all__ = ["install_stable_capture"]
