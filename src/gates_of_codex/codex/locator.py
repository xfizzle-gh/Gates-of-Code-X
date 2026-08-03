from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodeXInstallation:
    game_directory: Path
    code_x_directory: Path
    profile_directory: Path | None = None


class CodeXLocator:
    GAME_APP_ID = "400750"

    def steam_roots(self) -> list[Path]:
        candidates: list[Path] = []
        for value in (
            os.environ.get("STEAM_PATH"),
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
            str(Path.home() / ".steam/steam"),
            str(Path.home() / ".local/share/Steam"),
        ):
            if value:
                path = Path(value)
                if path.is_dir() and path not in candidates:
                    candidates.append(path)
        return candidates

    def steam_libraries(self) -> list[Path]:
        libraries: list[Path] = []
        for root in self.steam_roots():
            if root not in libraries:
                libraries.append(root)
            vdf = root / "steamapps/libraryfolders.vdf"
            if not vdf.is_file():
                continue
            text = vdf.read_text(encoding="utf-8-sig", errors="replace")
            for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                path = Path(match.group(1).replace("\\\\", "\\"))
                if path.is_dir() and path not in libraries:
                    libraries.append(path)
        return libraries

    def find_game_directories(self) -> list[Path]:
        names = ("Call to Arms - Gates of Hell", "Call to Arms - Gates of Hell Ostfront")
        found: list[Path] = []
        for library in self.steam_libraries():
            for name in names:
                path = library / "steamapps/common" / name
                if path.is_dir() and path not in found:
                    found.append(path)
        return found

    @staticmethod
    def _is_codex(path: Path) -> bool:
        mod_info = path / "mod.info"
        if not mod_info.is_file():
            return False
        text = mod_info.read_text(encoding="utf-8-sig", errors="replace").lower()
        return "code:x" in text or "codex" in text

    def find_codex_directories(self, game_directory: Path | None = None) -> list[Path]:
        found: list[Path] = []
        roots: list[Path] = []
        for library in self.steam_libraries():
            workshop = library / "steamapps/workshop/content" / self.GAME_APP_ID
            if workshop.is_dir():
                roots.extend(path for path in workshop.iterdir() if path.is_dir())
        for game in ([game_directory] if game_directory else self.find_game_directories()):
            if game:
                local = game / "mods"
                if local.is_dir():
                    roots.extend(path for path in local.iterdir() if path.is_dir())
        for path in roots:
            if self._is_codex(path) and path not in found:
                found.append(path)
        return found

    def find_profiles(self) -> list[Path]:
        candidates = [
            Path.home() / "Documents/My Games/gates of hell/profiles",
            Path.home() / "Documents/My Games/Call to Arms - Gates of Hell/profiles",
        ]
        return [path for path in candidates if path.is_dir()]

    def discover(self) -> list[CodeXInstallation]:
        results: list[CodeXInstallation] = []
        profiles = self.find_profiles()
        for game in self.find_game_directories():
            for codex in self.find_codex_directories(game):
                results.append(CodeXInstallation(game, codex, profiles[0] if profiles else None))
        return results
