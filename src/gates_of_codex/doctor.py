from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .codex.catalog import CodeXCatalogScanner
from .codex.locator import CodeXLocator


@dataclass(frozen=True, slots=True)
class DoctorReport:
    game_directories: list[Path]
    code_x_directories: list[Path]
    profile_directories: list[Path]
    unit_counts: dict[str, int]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return bool(self.game_directories and self.code_x_directories) and not self.errors


def _explicit_directory(value: str | Path | None, label: str, errors: list[str]) -> list[Path] | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    try:
        path = path.resolve()
    except OSError:
        pass
    if not path.is_dir():
        errors.append(f"{label} directory does not exist: {path}")
        return []
    return [path]


def diagnose(
    code_x_directory: str | Path | None = None,
    game_directory: str | Path | None = None,
    profile_directory: str | Path | None = None,
) -> DoctorReport:
    locator = CodeXLocator()
    errors: list[str] = []

    games = _explicit_directory(game_directory, "Gates of Hell", errors)
    if games is None:
        games = locator.find_game_directories()

    codex = _explicit_directory(code_x_directory, "Code:X", errors)
    if codex is None:
        codex = locator.find_codex_directories(games[0] if games else None)

    profiles = _explicit_directory(profile_directory, "Profile", errors)
    if profiles is None:
        profiles = locator.find_profiles()

    counts: dict[str, int] = {}
    if codex:
        try:
            catalog = CodeXCatalogScanner().scan(codex[0])
            for faction in ("nato", "ukr", "rusa", "prc"):
                counts[faction] = len(catalog.by_faction(faction))
                if counts[faction] == 0:
                    errors.append(f"No {faction} units found")
        except Exception as exc:
            errors.append(str(exc))
    elif not any(message.startswith("Code:X directory") for message in errors):
        errors.append("Code:X installation not found")

    if not games and not any(message.startswith("Gates of Hell directory") for message in errors):
        errors.append("Gates of Hell installation not found")

    return DoctorReport(games, codex, profiles, counts, errors)
