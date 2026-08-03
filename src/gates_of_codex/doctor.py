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


def diagnose(code_x_directory: str | Path | None = None) -> DoctorReport:
    locator = CodeXLocator()
    games = locator.find_game_directories()
    codex = [Path(code_x_directory)] if code_x_directory else locator.find_codex_directories(games[0] if games else None)
    profiles = locator.find_profiles()
    counts: dict[str, int] = {}
    errors: list[str] = []
    if codex:
        try:
            catalog = CodeXCatalogScanner().scan(codex[0])
            for faction in ("nato", "ukr", "rusa", "prc"):
                counts[faction] = len(catalog.by_faction(faction))
                if counts[faction] == 0:
                    errors.append(f"No {faction} units found")
        except Exception as exc:
            errors.append(str(exc))
    else:
        errors.append("Code:X installation not found")
    if not games:
        errors.append("Gates of Hell installation not found")
    return DoctorReport(games, codex, profiles, counts, errors)
