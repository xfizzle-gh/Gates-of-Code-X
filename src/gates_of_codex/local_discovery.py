from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


GOH_WORKSHOP_APP_ID = "400750"
WEST81_WORKSHOP_ID = "2897299509"
CODEX_WORKSHOP_ID = "3261086933"
CODEX_AI_OVERHAUL_WORKSHOP_ID = "3636883799"

STACK_LAYER_ENVIRONMENTS = (
    ("GOH_VANILLA_ROOT", "Gates of Hell"),
    ("WEST81_ROOT", "West81"),
    ("CODEX_ROOT", "Code:X"),
    ("CODEX_AI_OVERHAUL_ROOT", "Code:X AI Overhaul"),
    ("GATES_CODEX_ROOT", "Gates of Code:X"),
)

LAST_CAMPAIGN_SCHEMA = "gates-of-codex.player-last-campaign"


@dataclass(frozen=True, slots=True)
class LaunchPathDiscovery:
    campaign_file: str
    continue_campaign_file: str
    stack_config: str
    game_directory: str
    profile_directory: str
    godot_executable: str
    godot_project: str
    environment: tuple[tuple[str, str], ...]
    missing: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing

    def status_message(self) -> str:
        if self.ready:
            return "Local install detected. Stack, profile, Godot, and project are ready."
        return "Auto-detect incomplete. Missing: %s" % ", ".join(self.missing)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _resolved_existing_dir(value: object) -> Path | None:
    text = _clean(value)
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_dir():
        return None
    return candidate.resolve()


def _resolved_existing_file(value: object) -> Path | None:
    text = _clean(value)
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_file():
        return None
    return candidate.resolve()


def _append_unique(paths: list[Path], candidate: Path | None) -> None:
    if candidate is None:
        return
    resolved = candidate.resolve(strict=False)
    if resolved not in paths:
        paths.append(resolved)


def _repo_root(environ: Mapping[str, str], explicit: str | Path | None) -> Path | None:
    if explicit is not None:
        candidate = _resolved_existing_dir(explicit)
        if candidate is not None and (candidate / "config" / "mod-stack.windows.json").is_file():
            return candidate
        return None

    candidates: list[Path] = []
    _append_unique(candidates, _resolved_existing_dir(environ.get("GATES_CODEX_ROOT")))

    cwd = Path.cwd().resolve(strict=False)
    for candidate in (cwd, *cwd.parents):
        _append_unique(candidates, candidate if candidate.is_dir() else None)

    source = Path(__file__).resolve(strict=False)
    for candidate in source.parents:
        _append_unique(candidates, candidate if candidate.is_dir() else None)

    for candidate in candidates:
        if (candidate / "config" / "mod-stack.windows.json").is_file():
            return candidate
    return None


def _steam_library_paths_from_vdf(steam_root: Path) -> list[Path]:
    source = steam_root / "steamapps" / "libraryfolders.vdf"
    if not source.is_file():
        return []
    try:
        text = source.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []

    values: list[str] = []
    values.extend(re.findall(r'"path"\s*"([^"]+)"', text, flags=re.IGNORECASE))
    values.extend(re.findall(r'"\d+"\s*"([^"]+)"', text))
    discovered: list[Path] = []
    for value in values:
        candidate = Path(value.replace("\\\\", "\\")).expanduser()
        if candidate.is_dir():
            _append_unique(discovered, candidate)
    return discovered


def _steam_library_roots(
    environ: Mapping[str, str],
    explicit: Sequence[str | Path] | None,
) -> list[Path]:
    roots: list[Path] = []
    if explicit is not None:
        for value in explicit:
            _append_unique(roots, _resolved_existing_dir(value))
    else:
        game = _resolved_existing_dir(environ.get("GOH_VANILLA_ROOT"))
        if game is not None and len(game.parents) >= 3:
            _append_unique(roots, game.parents[2])

        for key in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            base = _resolved_existing_dir(environ.get(key))
            if base is not None:
                _append_unique(roots, _resolved_existing_dir(base / "Steam"))

        if os.name == "nt":
            for drive in "CDEFGHIJ":
                for suffix in ("Steam", "SteamLibrary"):
                    _append_unique(
                        roots,
                        _resolved_existing_dir(Path(f"{drive}:\\") / suffix),
                    )

    index = 0
    while index < len(roots):
        for library in _steam_library_paths_from_vdf(roots[index]):
            _append_unique(roots, library)
        index += 1
    return roots


def _campaign_pointer_path(player_root: Path) -> Path:
    return player_root / "last_campaign.json"


def _player_root(
    environ: Mapping[str, str],
    local_app_data: str | Path | None,
) -> Path:
    explicit = _clean(local_app_data)
    if explicit:
        return Path(explicit).expanduser().resolve(strict=False) / "GatesOfCodeX"
    configured = _clean(environ.get("LOCALAPPDATA"))
    if configured:
        return Path(configured).expanduser().resolve(strict=False) / "GatesOfCodeX"
    if os.name == "nt":
        return (Path.home() / "AppData" / "Local" / "GatesOfCodeX").resolve(strict=False)
    xdg = _clean(environ.get("XDG_DATA_HOME"))
    if xdg:
        return Path(xdg).expanduser().resolve(strict=False) / "gates-of-codex"
    return (Path.home() / ".local" / "share" / "gates-of-codex").resolve(strict=False)


def default_campaign_path(
    scenario_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    local_app_data: str | Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    return _player_root(env, local_app_data) / "campaigns" / scenario_id / "campaign.json"


def _read_last_campaign(player_root: Path) -> Path | None:
    pointer = _campaign_pointer_path(player_root)
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != LAST_CAMPAIGN_SCHEMA:
        return None
    candidate = _resolved_existing_file(payload.get("campaign_path"))
    return candidate


def _read_campaign_launch_hints(campaign: Path | None) -> dict[str, str]:
    if campaign is None:
        return {}
    try:
        payload = json.loads(campaign.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}

    result: dict[str, str] = {}
    for key in ("game_directory", "profile_directory"):
        value = _clean(payload.get(key))
        if value:
            result[key] = value

    metadata = payload.get("map_metadata")
    if isinstance(metadata, dict):
        stack_config = _clean(metadata.get("stack_config"))
        if stack_config:
            result["stack_config"] = stack_config
        launch = metadata.get("player_launch")
        if isinstance(launch, dict):
            for key in ("godot_executable", "godot_project"):
                value = _clean(launch.get(key))
                if value:
                    result[key] = value
    return result


def _find_game_directory(
    environ: Mapping[str, str],
    steam_roots: Sequence[Path],
    hints: Mapping[str, str],
) -> Path | None:
    for value in (environ.get("GOH_VANILLA_ROOT"), hints.get("game_directory")):
        candidate = _resolved_existing_dir(value)
        if candidate is not None:
            return candidate
    for root in steam_roots:
        candidate = root / "steamapps" / "common" / "Call to Arms - Gates of Hell"
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _find_workshop_layer(
    environ: Mapping[str, str],
    env_name: str,
    workshop_id: str,
    steam_roots: Sequence[Path],
) -> Path | None:
    configured = _resolved_existing_dir(environ.get(env_name))
    if configured is not None:
        return configured
    for root in steam_roots:
        candidate = root / "steamapps" / "workshop" / "content" / GOH_WORKSHOP_APP_ID / workshop_id
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _find_profile_directory(
    environ: Mapping[str, str],
    local_app_data: str | Path | None,
    hints: Mapping[str, str],
) -> Path | None:
    hinted = _resolved_existing_dir(hints.get("profile_directory"))
    if hinted is not None:
        return hinted

    if local_app_data is not None:
        local_root = Path(local_app_data).expanduser()
    else:
        configured = _clean(environ.get("LOCALAPPDATA"))
        local_root = Path(configured).expanduser() if configured else Path.home() / "AppData" / "Local"
    profiles_root = local_root / "digitalmindsoft" / "gates of hell" / "profiles"
    if not profiles_root.is_dir():
        return None
    candidates = [path for path in profiles_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=_safe_mtime).resolve()


def _godot_roots(
    environ: Mapping[str, str],
    explicit: Sequence[str | Path] | None,
) -> list[Path]:
    roots: list[Path] = []
    if explicit is not None:
        for value in explicit:
            path = Path(value).expanduser()
            if path.is_file():
                _append_unique(roots, path.parent)
            elif path.is_dir():
                _append_unique(roots, path)
        return roots

    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = _resolved_existing_dir(environ.get(key))
        if base is not None:
            _append_unique(roots, _resolved_existing_dir(base / "Godot Engine"))

    if os.name == "nt":
        for drive in "CDEFGHIJ":
            for suffix in ("Program Files\\Godot Engine", "Program Files (x86)\\Godot Engine"):
                _append_unique(
                    roots,
                    _resolved_existing_dir(Path(f"{drive}:\\") / suffix),
                )
    return roots


def _find_godot_executable(
    environ: Mapping[str, str],
    hints: Mapping[str, str],
    search_roots: Sequence[Path],
    *,
    allow_path_lookup: bool,
) -> Path | None:
    for value in (environ.get("GATES_OF_CODEX_GODOT"), hints.get("godot_executable")):
        candidate = _resolved_existing_file(value)
        if candidate is not None:
            return candidate

    if allow_path_lookup:
        for name in (
            "Godot_v4.7-stable_win64.exe",
            "Godot_v4.7-stable_linux.x86_64",
            "godot",
            "godot4",
            "Godot",
        ):
            located = shutil.which(name)
            if located:
                candidate = _resolved_existing_file(located)
                if candidate is not None:
                    return candidate

    candidates: list[Path] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        candidates.extend(path for path in root.glob("Godot_v4.7*.exe") if path.is_file())
        candidates.extend(path for path in root.glob("Godot*.exe") if path.is_file())

    unique: list[Path] = []
    for candidate in candidates:
        _append_unique(unique, candidate)
    if not unique:
        return None
    return max(
        unique,
        key=lambda path: (
            "4.7" in path.name,
            "console" not in path.name.lower(),
            _safe_mtime(path),
        ),
    ).resolve()


def detect_launch_paths(
    scenario_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    repo_root: str | Path | None = None,
    steam_roots: Sequence[str | Path] | None = None,
    local_app_data: str | Path | None = None,
    godot_search_roots: Sequence[str | Path] | None = None,
) -> LaunchPathDiscovery:
    env = os.environ if environ is None else environ
    repository = _repo_root(env, repo_root)
    player_root = _player_root(env, local_app_data)
    last_campaign = _read_last_campaign(player_root)
    hints = _read_campaign_launch_hints(last_campaign)
    libraries = _steam_library_roots(env, steam_roots)

    game = _find_game_directory(env, libraries, hints)
    west81 = _find_workshop_layer(env, "WEST81_ROOT", WEST81_WORKSHOP_ID, libraries)
    codex = _find_workshop_layer(env, "CODEX_ROOT", CODEX_WORKSHOP_ID, libraries)
    ai_overhaul = _find_workshop_layer(
        env,
        "CODEX_AI_OVERHAUL_ROOT",
        CODEX_AI_OVERHAUL_WORKSHOP_ID,
        libraries,
    )
    profile = _find_profile_directory(env, local_app_data, hints)

    stack_config = None
    if repository is not None:
        stack_candidate = repository / "config" / "mod-stack.windows.json"
        if stack_candidate.is_file():
            stack_config = stack_candidate.resolve()
    if stack_config is None:
        stack_config = _resolved_existing_file(hints.get("stack_config"))

    godot_project = None
    if repository is not None:
        project_candidate = repository / "godot"
        if (project_candidate / "project.godot").is_file():
            godot_project = project_candidate.resolve()
    if godot_project is None:
        hinted_project = _resolved_existing_dir(hints.get("godot_project"))
        if hinted_project is not None and (hinted_project / "project.godot").is_file():
            godot_project = hinted_project

    godot = _find_godot_executable(
        env,
        hints,
        _godot_roots(env, godot_search_roots),
        allow_path_lookup=godot_search_roots is None,
    )

    environment: list[tuple[str, str]] = []
    detected_layers = {
        "GOH_VANILLA_ROOT": game,
        "WEST81_ROOT": west81,
        "CODEX_ROOT": codex,
        "CODEX_AI_OVERHAUL_ROOT": ai_overhaul,
        "GATES_CODEX_ROOT": repository,
    }
    missing: list[str] = []
    for env_name, label in STACK_LAYER_ENVIRONMENTS:
        value = detected_layers.get(env_name)
        if value is None:
            missing.append(label)
        else:
            environment.append((env_name, str(value)))

    if godot is not None:
        environment.append(("GATES_OF_CODEX_GODOT", str(godot)))

    if stack_config is None:
        missing.append("stack config")
    if profile is None:
        missing.append("GoH profile")
    if godot is None:
        missing.append("Godot 4.7")
    if godot_project is None:
        missing.append("Godot project")

    return LaunchPathDiscovery(
        campaign_file=str(default_campaign_path(
            scenario_id,
            environ=env,
            local_app_data=local_app_data,
        )),
        continue_campaign_file=str(last_campaign) if last_campaign is not None else "",
        stack_config=str(stack_config) if stack_config is not None else "",
        game_directory=str(game) if game is not None else "",
        profile_directory=str(profile) if profile is not None else "",
        godot_executable=str(godot) if godot is not None else "",
        godot_project=str(godot_project) if godot_project is not None else "",
        environment=tuple(environment),
        missing=tuple(missing),
    )
