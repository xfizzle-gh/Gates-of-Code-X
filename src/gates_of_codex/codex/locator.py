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
    GAME_DIRECTORY_NAMES = (
        "Call to Arms - Gates of Hell",
        "Call to Arms - Gates of Hell Ostfront",
    )

    @staticmethod
    def _append_directory(values: list[Path], candidate: str | Path | None) -> None:
        if not candidate:
            return
        path = Path(os.path.expandvars(str(candidate))).expanduser()
        try:
            path = path.resolve()
        except OSError:
            pass
        if path.is_dir() and path not in values:
            values.append(path)

    @staticmethod
    def _steam_root_from_path(path: Path) -> Path | None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        for candidate in (resolved, *resolved.parents):
            if candidate.name.lower() == "steamapps":
                return candidate.parent
        return None

    @staticmethod
    def _registry_steam_roots() -> list[Path]:
        try:
            import winreg
        except ImportError:
            return []

        roots: list[Path] = []
        lookups = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        )
        for hive, key_name, value_name in lookups:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, value_name)
                path = Path(os.path.expandvars(str(value))).expanduser()
                if path.is_dir() and path not in roots:
                    roots.append(path)
            except OSError:
                continue
        return roots

    def steam_roots(self) -> list[Path]:
        candidates: list[Path] = []
        inferred_paths = (Path.cwd(), Path(__file__).resolve())
        for source in inferred_paths:
            self._append_directory(candidates, self._steam_root_from_path(source))
        for path in self._registry_steam_roots():
            self._append_directory(candidates, path)
        for value in (
            os.environ.get("STEAM_PATH"),
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
            Path.home() / ".steam/steam",
            Path.home() / ".local/share/Steam",
        ):
            self._append_directory(candidates, value)
        return candidates

    def steam_libraries(self) -> list[Path]:
        libraries: list[Path] = []
        for root in self.steam_roots():
            self._append_directory(libraries, root)
            vdf = root / "steamapps/libraryfolders.vdf"
            if not vdf.is_file():
                continue
            text = vdf.read_text(encoding="utf-8-sig", errors="replace")
            for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                self._append_directory(libraries, match.group(1).replace("\\\\", "\\"))
        return libraries

    @staticmethod
    def _manifest_install_directory(library: Path) -> Path | None:
        manifest = library / "steamapps" / f"appmanifest_{CodeXLocator.GAME_APP_ID}.acf"
        if not manifest.is_file():
            return None
        text = manifest.read_text(encoding="utf-8-sig", errors="replace")
        match = re.search(r'"installdir"\s+"([^"]+)"', text, flags=re.IGNORECASE)
        if not match:
            return None
        path = library / "steamapps/common" / match.group(1)
        return path if path.is_dir() else None

    def find_game_directories(self) -> list[Path]:
        found: list[Path] = []
        for library in self.steam_libraries():
            self._append_directory(found, self._manifest_install_directory(library))
            for name in self.GAME_DIRECTORY_NAMES:
                self._append_directory(found, library / "steamapps/common" / name)
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
            if self._is_codex(path):
                self._append_directory(found, path)
        return found

    @staticmethod
    def _windows_documents_directories() -> list[Path]:
        values: list[Path] = []
        for environment_name in ("OneDrive", "OneDriveConsumer", "USERPROFILE"):
            base = os.environ.get(environment_name)
            if base:
                candidate = Path(base) / "Documents"
                if candidate.is_dir() and candidate not in values:
                    values.append(candidate)
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "Personal")
            candidate = Path(os.path.expandvars(str(value))).expanduser()
            if candidate.is_dir() and candidate not in values:
                values.append(candidate)
        except (ImportError, OSError):
            pass
        return values

    def find_profiles(self) -> list[Path]:
        documents: list[Path] = []
        self._append_directory(documents, Path.home() / "Documents")
        for path in self._windows_documents_directories():
            self._append_directory(documents, path)

        candidates: list[Path] = []
        for root in documents:
            for relative in (
                Path("My Games/gates of hell/profiles"),
                Path("My Games/Call to Arms - Gates of Hell/profiles"),
            ):
                self._append_directory(candidates, root / relative)
        return candidates

    def discover(self) -> list[CodeXInstallation]:
        results: list[CodeXInstallation] = []
        profiles = self.find_profiles()
        for game in self.find_game_directories():
            for codex in self.find_codex_directories(game):
                results.append(CodeXInstallation(game, codex, profiles[0] if profiles else None))
        return results
