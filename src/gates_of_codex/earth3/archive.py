"""Safe read-only access to the Earth3 province archive."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class Earth3ArchiveError(ValueError):
    pass


@dataclass(slots=True)
class Earth3Archive:
    path: Path
    _zip: zipfile.ZipFile
    _names: tuple[str, ...]
    _raw_by_norm: dict[str, str]

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> Earth3Archive:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def names(self) -> tuple[str, ...]:
        return self._names

    def read_text(self, member: str, *, encoding: str = "utf-8") -> str:
        data = self.read_bytes(member)
        return data.decode(encoding)

    def read_bytes(self, member: str) -> bytes:
        key = _normalize_member(member)
        if key not in self._raw_by_norm:
            raise Earth3ArchiveError(f"archive member not found: {member}")
        # Reject traversal even if present in central directory.
        _assert_safe_member(key)
        with self._zip.open(self._raw_by_norm[key], "r") as handle:
            return handle.read()

    def list_prefix(self, prefix: str) -> list[str]:
        norm_prefix = _normalize_member(prefix).rstrip("/") + "/"
        return sorted(name for name in self._names if name.startswith(norm_prefix))


def open_earth3_archive(path: str | Path) -> Earth3Archive:
    archive_path = Path(path)
    if not archive_path.is_file():
        raise Earth3ArchiveError(f"archive not found: {archive_path}")
    try:
        handle = zipfile.ZipFile(archive_path, "r")
    except zipfile.BadZipFile as exc:
        raise Earth3ArchiveError(f"invalid zip archive: {archive_path}") from exc

    names: list[str] = []
    raw_by_norm: dict[str, str] = {}
    for raw in handle.namelist():
        norm = _normalize_member(raw)
        if not norm or norm.endswith("/"):
            continue
        _assert_safe_member(norm)
        names.append(norm)
        raw_by_norm[norm] = raw
    names.sort()
    return Earth3Archive(
        path=archive_path,
        _zip=handle,
        _names=tuple(names),
        _raw_by_norm=raw_by_norm,
    )


def _normalize_member(name: str) -> str:
    text = name.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _assert_safe_member(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise Earth3ArchiveError(f"unsafe archive path rejected: {name}")
    if any(part.startswith("/") or ":" in part for part in path.parts):
        raise Earth3ArchiveError(f"unsafe archive path rejected: {name}")
