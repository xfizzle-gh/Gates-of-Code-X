"""Player-facing launch and continuation shell.

This module replaces the developer sequence of ``new`` → ``export-frontend`` →
manual Godot launch → manual snapshot replacement with a single player action.

Authority rules enforced here:

* The Python campaign file is the only authoritative campaign state. The Godot
  snapshot is always regenerated from it and is never read back as authority.
* Production New Campaign builds ``earth3_v1`` on ``earth3_europe_mediterranean``.
  There is no fallback to a GoE-derived map; legacy scenarios require explicit
  ``--scenario`` selection.
* Missing or invalid stack, game, or profile inputs fail closed with an
  actionable message instead of being replaced by a discovered substitute.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .frontend import write_frontend_snapshot
from .models import CampaignState, Faction
from .scenario import DEFAULT_SCENARIO_ID, build_scenario, get_scenario
from .starter import set_player_faction
from .state_io import load_campaign, save_campaign


FACTION_CHOICES = ("nato", "ukr", "rusa", "prc")

#: Difficulty identifiers accepted by the player shell. P4 records the choice on
#: the campaign; balance consumption of the value is deliberately out of scope.
DIFFICULTY_CHOICES = ("easy", "normal", "hard")

CAMPAIGN_FILE_NAME = "campaign.json"
SNAPSHOT_FILE_NAME = "campaign_snapshot.json"
COMMANDS_FILE_NAME = "frontend_commands.json"
LAST_CAMPAIGN_FILE_NAME = "last_campaign.json"

#: Campaign-metadata key holding launcher-owned paths. Gameplay authority stays
#: on the canonical campaign fields (game/profile directory, difficulty, faction,
#: fog, ``stack_config``, ``preferred_map``); only launcher paths live here.
PLAYER_LAUNCH_KEY = "player_launch"

LAST_CAMPAIGN_SCHEMA = "gates-of-codex.player-last-campaign"
LAST_CAMPAIGN_SCHEMA_VERSION = 1

HOME_ENVIRONMENT_VARIABLE = "GATES_OF_CODEX_HOME"
GODOT_ENVIRONMENT_VARIABLE = "GATES_OF_CODEX_GODOT"

GODOT_EXECUTABLE_CANDIDATES = (
    "godot",
    "godot4",
    "Godot",
    "Godot_v4.7-stable_win64.exe",
    "Godot_v4.7-stable_linux.x86_64",
)


class PlayerShellError(RuntimeError):
    """Raised when a player launch request cannot be satisfied safely."""


@dataclass(frozen=True, slots=True)
class CampaignPaths:
    root: Path
    campaign: Path
    snapshot: Path
    commands: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "campaign": str(self.campaign),
            "snapshot": str(self.snapshot),
            "commands": str(self.commands),
        }


@dataclass(slots=True)
class PlayResult:
    mode: str
    campaign_path: str
    snapshot_path: str
    commands_path: str
    scenario_id: str
    map_id: str
    selected_faction: str
    difficulty: str
    fog_of_war: str
    turn_number: int
    launched: bool = False
    godot_executable: str = ""
    godot_project: str = ""
    stack_layers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Player directories
# ---------------------------------------------------------------------------


def player_home(environ: Mapping[str, str] | None = None) -> Path:
    """Return the predictable per-user Gates of CodeX directory."""
    env = os.environ if environ is None else environ
    override = str(env.get(HOME_ENVIRONMENT_VARIABLE, "")).strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        local = str(env.get("LOCALAPPDATA", "")).strip()
        if local:
            return Path(local) / "GatesOfCodeX"
        return Path.home() / "AppData" / "Local" / "GatesOfCodeX"
    xdg = str(env.get("XDG_DATA_HOME", "")).strip()
    if xdg:
        return Path(xdg) / "gates-of-codex"
    return Path.home() / ".local" / "share" / "gates-of-codex"


def resolve_campaign_paths(
    campaign: str | Path | None,
    *,
    scenario_id: str = DEFAULT_SCENARIO_ID,
    environ: Mapping[str, str] | None = None,
) -> CampaignPaths:
    """Resolve the campaign directory and its derived file paths.

    ``campaign`` may name the campaign file itself (``*.json``) or the directory
    that holds it. Without an explicit value the predictable per-user location
    ``<player home>/campaigns/<scenario id>`` is used.
    """
    if campaign is None or not str(campaign).strip():
        root = player_home(environ) / "campaigns" / scenario_id
        campaign_file = root / CAMPAIGN_FILE_NAME
    else:
        raw = Path(str(campaign).strip()).expanduser()
        if raw.suffix.lower() == ".json":
            campaign_file = raw
            root = raw.parent
        else:
            root = raw
            campaign_file = raw / CAMPAIGN_FILE_NAME
    # ``resolve`` keeps Windows drive-relative and mixed-separator input stable
    # without requiring the directory to exist yet.
    root = Path(os.path.abspath(str(root)))
    campaign_file = Path(os.path.abspath(str(campaign_file)))
    if campaign_file.parent != root:
        root = campaign_file.parent
    return CampaignPaths(
        root=root,
        campaign=campaign_file,
        snapshot=root / SNAPSHOT_FILE_NAME,
        commands=root / COMMANDS_FILE_NAME,
    )


def last_campaign_path(environ: Mapping[str, str] | None = None) -> Path:
    return player_home(environ) / LAST_CAMPAIGN_FILE_NAME


def read_last_campaign(environ: Mapping[str, str] | None = None) -> Path | None:
    """Return the most recently launched campaign file, if one was recorded.

    The pointer is a launcher preference only. It never carries gameplay state
    and a missing or malformed pointer simply means "no remembered campaign".
    """
    source = last_campaign_path(environ)
    if not source.is_file():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("schema", "")) != LAST_CAMPAIGN_SCHEMA:
        return None
    value = str(payload.get("campaign_path", "")).strip()
    return Path(value) if value else None


def write_last_campaign(
    campaign: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    destination = last_campaign_path(environ)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            {
                "schema": LAST_CAMPAIGN_SCHEMA,
                "schema_version": LAST_CAMPAIGN_SCHEMA_VERSION,
                "campaign_path": str(Path(campaign)),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    _atomic_write_text(destination, payload)
    return destination


def _atomic_write_text(destination: Path, payload: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _require_directory(value: str | None, *, label: str) -> str:
    """Resolve a required directory or fail; never substitute another path."""
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text).expanduser()
    if not candidate.is_dir():
        raise PlayerShellError(
            f"{label} is not an existing directory: {candidate}"
        )
    return str(candidate.resolve())


def validate_stack(
    stack_config: str | Path | None,
    *,
    game_directory: str | None = None,
    profile_directory: str | None = None,
    required: bool,
) -> list[str]:
    """Validate the intended active mod stack and return its resolved layers."""
    if not stack_config:
        if required:
            raise PlayerShellError(
                "--stack-config is required: the production Earth3 campaign is "
                "built from the exact validated active mod stack"
            )
        return []
    source = Path(str(stack_config)).expanduser()
    if not source.is_file():
        raise PlayerShellError(f"Stack config not found: {source}")
    from .modstack import load_stack_config, stack_to_strings

    try:
        layers = load_stack_config(source)
    except (OSError, ValueError, FileNotFoundError) as exc:
        raise PlayerShellError(f"Invalid stack config {source}: {exc}") from exc
    resolved = stack_to_strings(layers)
    if game_directory:
        from .stack_acceptance import validate_mod_stack

        report = validate_mod_stack(
            game_directory,
            layers[-1],
            stack_config=source,
            profile_directory=profile_directory or None,
        )
        if not report.ok:
            failures = "; ".join(
                f"{check.name}: {check.detail}"
                for check in report.checks
                if not check.ok
            )
            raise PlayerShellError(
                f"Mod stack validation failed for {source}: {failures or 'unknown failure'}"
            )
    return resolved


# ---------------------------------------------------------------------------
# Godot strategic application
# ---------------------------------------------------------------------------


def godot_project_directory(explicit: str | Path | None = None) -> Path:
    """Locate the Godot strategic application project directory."""
    if explicit:
        candidate = Path(str(explicit)).expanduser()
        if (candidate / "project.godot").is_file():
            return candidate.resolve()
        raise PlayerShellError(
            f"Godot project directory has no project.godot: {candidate}"
        )
    from .operational_position import default_asset_search_roots

    for root in default_asset_search_roots():
        for relative in (Path("godot"), Path()):
            candidate = root / relative
            if (candidate / "project.godot").is_file():
                return candidate.resolve()
    raise PlayerShellError(
        "Could not locate the Godot strategic application (project.godot). "
        "Pass --godot-project to name it explicitly."
    )


def find_godot_executable(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the Godot editor/runtime executable, failing closed."""
    env = os.environ if environ is None else environ
    if explicit:
        candidate = Path(str(explicit)).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        located = shutil.which(str(explicit))
        if located:
            return Path(located).resolve()
        raise PlayerShellError(f"Godot executable not found: {candidate}")
    configured = str(env.get(GODOT_ENVIRONMENT_VARIABLE, "")).strip()
    if configured:
        return find_godot_executable(configured, environ=env)
    for name in GODOT_EXECUTABLE_CANDIDATES:
        located = shutil.which(name)
        if located:
            return Path(located).resolve()
    raise PlayerShellError(
        "Could not locate a Godot 4 executable. Set "
        f"{GODOT_ENVIRONMENT_VARIABLE} or pass --godot with the full path."
    )


def launch_strategic_application(
    *,
    snapshot: Path,
    godot_executable: Path,
    project_directory: Path,
) -> subprocess.Popen:
    """Start the Godot strategic application against a generated snapshot."""
    arguments = [
        str(godot_executable),
        "--path",
        str(project_directory),
        "--",
        f"--snapshot={snapshot}",
    ]
    return subprocess.Popen(arguments, cwd=str(project_directory))


# ---------------------------------------------------------------------------
# Launch settings persistence
# ---------------------------------------------------------------------------


def persist_launch_settings(
    state: CampaignState,
    *,
    paths: CampaignPaths,
    stack_config: str | None,
    game_directory: str | None,
    profile_directory: str | None,
    tactical_map: str | None,
    godot_executable: str | None,
    godot_project: str | None,
) -> None:
    """Record launch inputs on the single authoritative campaign file.

    Canonical gameplay fields keep their existing homes; only launcher-owned
    paths are added under ``player_launch``.
    """
    if game_directory:
        state.game_directory = game_directory
    if profile_directory:
        state.profile_directory = profile_directory
    if stack_config:
        state.map_metadata["stack_config"] = stack_config
    if tactical_map:
        state.map_metadata["preferred_map"] = tactical_map
    existing = state.map_metadata.get(PLAYER_LAUNCH_KEY)
    record = dict(existing) if isinstance(existing, dict) else {}
    record.update(
        {
            "schema_version": 1,
            "campaign_path": str(paths.campaign),
            "snapshot_path": str(paths.snapshot),
            "commands_path": str(paths.commands),
        }
    )
    if godot_executable:
        record["godot_executable"] = godot_executable
    if godot_project:
        record["godot_project"] = godot_project
    state.map_metadata[PLAYER_LAUNCH_KEY] = record


def launch_settings(state: CampaignState) -> dict[str, Any]:
    """Return the merged launch settings persisted on a campaign."""
    record = state.map_metadata.get(PLAYER_LAUNCH_KEY)
    merged: dict[str, Any] = dict(record) if isinstance(record, dict) else {}
    merged.update(
        {
            "scenario_id": str(state.map_metadata.get("scenario_id", "")),
            "stack_config": str(state.map_metadata.get("stack_config", "")),
            "tactical_map": str(state.map_metadata.get("preferred_map", "")),
            "game_directory": state.game_directory,
            "profile_directory": state.profile_directory,
            "faction": state.selected_faction.value,
            "difficulty": state.difficulty,
            "fog_of_war": "on" if state.fog_of_war_enabled else "off",
        }
    )
    return merged


# ---------------------------------------------------------------------------
# Campaign creation and continuation
# ---------------------------------------------------------------------------


def _check_faction(scenario_id: str, faction: str) -> None:
    if scenario_id == DEFAULT_SCENARIO_ID and faction != Faction.NATO.value:
        raise PlayerShellError(
            "Earth3 P2 human seat is fixed to the usa actor on the NATO tactical side"
        )


def _apply_faction(state: CampaignState, scenario_id: str, faction: str) -> None:
    _check_faction(scenario_id, faction)
    set_player_faction(state, Faction(faction))


def create_new_campaign(
    *,
    paths: CampaignPaths,
    scenario_id: str = DEFAULT_SCENARIO_ID,
    faction: str = Faction.NATO.value,
    difficulty: str = "normal",
    fog_of_war: str = "off",
    stack_config: str | None = None,
    game_directory: str | None = None,
    profile_directory: str | None = None,
    tactical_map: str | None = None,
    godot_executable: str | None = None,
    godot_project: str | None = None,
    force: bool = False,
    resolved_catalog: Mapping[str, Any] | None = None,
) -> CampaignState:
    """Create and persist a new authoritative campaign.

    ``resolved_catalog`` is the same already-supported P2 catalog-authority
    injection accepted by ``build_earth3_v1_campaign``. The player CLI never
    supplies it; production always resolves the catalog from the validated stack.
    """
    definition = get_scenario(scenario_id)
    if paths.campaign.exists() and not force:
        raise PlayerShellError(
            f"Campaign already exists: {paths.campaign}. Use --continue to resume "
            "it, or --force-new to replace it."
        )
    # Reject an illegal seat before paying for scenario construction.
    _check_faction(definition.scenario_id, faction)
    builder_options: dict[str, Any] = {}
    if definition.scenario_id == DEFAULT_SCENARIO_ID:
        if resolved_catalog is not None:
            builder_options["resolved_catalog"] = resolved_catalog
        else:
            builder_options["stack_config"] = stack_config
    state = build_scenario(scenario_id, **builder_options)
    if state.map_id != definition.map_id:
        raise PlayerShellError(
            f"Scenario {scenario_id} produced map {state.map_id!r}; "
            f"expected {definition.map_id!r}"
        )
    _apply_faction(state, definition.scenario_id, faction)
    state.difficulty = difficulty
    state.fog_of_war_enabled = fog_of_war == "on"
    persist_launch_settings(
        state,
        paths=paths,
        stack_config=stack_config,
        game_directory=game_directory,
        profile_directory=profile_directory,
        tactical_map=tactical_map,
        godot_executable=godot_executable,
        godot_project=godot_project,
    )
    paths.root.mkdir(parents=True, exist_ok=True)
    save_campaign(state, paths.campaign)
    return state


def continue_campaign(
    *,
    paths: CampaignPaths,
    faction: str | None = None,
    difficulty: str | None = None,
    fog_of_war: str | None = None,
    stack_config: str | None = None,
    game_directory: str | None = None,
    profile_directory: str | None = None,
    tactical_map: str | None = None,
    godot_executable: str | None = None,
    godot_project: str | None = None,
) -> CampaignState:
    """Reopen the existing authoritative campaign in place."""
    if not paths.campaign.is_file():
        raise PlayerShellError(
            f"No campaign to continue at {paths.campaign}. Start one with --new."
        )
    state = load_campaign(paths.campaign)
    scenario_id = str(state.map_metadata.get("scenario_id", "")) or DEFAULT_SCENARIO_ID
    if faction:
        _apply_faction(state, scenario_id, faction)
    if difficulty:
        state.difficulty = difficulty
    if fog_of_war:
        state.fog_of_war_enabled = fog_of_war == "on"
    persist_launch_settings(
        state,
        paths=paths,
        stack_config=stack_config,
        game_directory=game_directory,
        profile_directory=profile_directory,
        tactical_map=tactical_map,
        godot_executable=godot_executable,
        godot_project=godot_project,
    )
    save_campaign(state, paths.campaign)
    return state


def publish_snapshot(state: CampaignState, paths: CampaignPaths) -> Path:
    """Regenerate the frontend snapshot from authoritative campaign state."""
    from .frontend_commands import clear_commands

    written = write_frontend_snapshot(state, paths.snapshot, campaign_path=paths.campaign)
    # A launch must never inherit a stale queue from an interrupted session.
    clear_commands(paths.commands)
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_play_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gates-of-codex play",
        description="Launch or continue a playable Gates of CodeX campaign.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--new", action="store_true", help="Create a new campaign")
    mode.add_argument(
        "--continue",
        dest="continue_campaign",
        action="store_true",
        help="Continue the existing campaign",
    )
    parser.add_argument("--campaign", help="Campaign directory or campaign JSON file")
    parser.add_argument("--faction", choices=FACTION_CHOICES)
    parser.add_argument("--difficulty", choices=DIFFICULTY_CHOICES)
    parser.add_argument("--fog-of-war", choices=["on", "off"])
    parser.add_argument("--stack-config", help="Validated active mod-stack config")
    parser.add_argument("--game", help="Gates of Hell install directory")
    parser.add_argument("--profile", help="Gates of Hell profile directory")
    parser.add_argument("--tactical-map", help="Preferred tactical map id")
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO_ID,
        help="Scenario id; legacy scenarios require explicit selection",
    )
    parser.add_argument("--godot", help="Godot 4 executable used for the strategic app")
    parser.add_argument("--godot-project", help="Godot project directory")
    parser.add_argument(
        "--force-new",
        action="store_true",
        help="Replace an existing campaign at the resolved path",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Prepare campaign and snapshot without starting Godot",
    )
    parser.add_argument("--json", action="store_true", help="Print the machine-readable result")
    return parser


def _persisted_stack_config(campaign: Path) -> str:
    """Read the recorded stack config without paying for a full campaign load."""
    if not campaign.is_file():
        return ""
    try:
        payload = json.loads(campaign.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        # A malformed campaign is reported by the authoritative loader, not here.
        return ""
    metadata = payload.get("map_metadata") if isinstance(payload, dict) else None
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("stack_config", "") or "")


def run_play(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    resolved_catalog: Mapping[str, Any] | None = None,
) -> PlayResult:
    scenario_id = str(args.scenario or DEFAULT_SCENARIO_ID)
    definition = get_scenario(scenario_id)
    is_new = bool(args.new)

    campaign_argument = args.campaign
    if not is_new and not campaign_argument:
        remembered = read_last_campaign(environ)
        if remembered is None:
            raise PlayerShellError(
                "No campaign to continue. Pass --campaign or start one with --new."
            )
        campaign_argument = str(remembered)

    paths = resolve_campaign_paths(
        campaign_argument, scenario_id=scenario_id, environ=environ
    )

    game_directory = _require_directory(args.game, label="--game")
    profile_directory = _require_directory(args.profile, label="--profile")

    persisted_stack = "" if is_new else _persisted_stack_config(paths.campaign)
    stack_config_argument = str(args.stack_config or "").strip() or persisted_stack
    stack_layers = validate_stack(
        stack_config_argument or None,
        game_directory=game_directory or None,
        profile_directory=profile_directory or None,
        # Only production Earth3 creation strictly requires the stack: it
        # materializes rosters from the exact active stack.
        required=is_new and definition.scenario_id == DEFAULT_SCENARIO_ID
        and resolved_catalog is None,
    )
    stack_config = (
        str(Path(stack_config_argument).expanduser().resolve())
        if stack_config_argument
        else ""
    )

    godot_executable = ""
    godot_project = ""
    if not args.no_launch:
        godot_executable = str(find_godot_executable(args.godot, environ=environ))
        godot_project = str(godot_project_directory(args.godot_project))
    elif args.godot or args.godot_project:
        if args.godot:
            godot_executable = str(find_godot_executable(args.godot, environ=environ))
        if args.godot_project:
            godot_project = str(godot_project_directory(args.godot_project))

    common = {
        "stack_config": stack_config or None,
        "game_directory": game_directory or None,
        "profile_directory": profile_directory or None,
        "tactical_map": str(args.tactical_map or "").strip() or None,
        "godot_executable": godot_executable or None,
        "godot_project": godot_project or None,
    }

    if is_new:
        state = create_new_campaign(
            paths=paths,
            scenario_id=scenario_id,
            faction=str(args.faction or Faction.NATO.value),
            difficulty=str(args.difficulty or "normal"),
            fog_of_war=str(args.fog_of_war or "off"),
            force=bool(args.force_new),
            resolved_catalog=resolved_catalog,
            **common,
        )
        mode = "new"
    else:
        state = continue_campaign(
            paths=paths,
            faction=args.faction,
            difficulty=args.difficulty,
            fog_of_war=args.fog_of_war,
            **common,
        )
        mode = "continue"

    snapshot = publish_snapshot(state, paths)
    write_last_campaign(paths.campaign, environ=environ)

    result = PlayResult(
        mode=mode,
        campaign_path=str(paths.campaign),
        snapshot_path=str(snapshot),
        commands_path=str(paths.commands),
        scenario_id=str(state.map_metadata.get("scenario_id", scenario_id)),
        map_id=state.map_id,
        selected_faction=state.selected_faction.value,
        difficulty=state.difficulty,
        fog_of_war="on" if state.fog_of_war_enabled else "off",
        turn_number=state.turn_number,
        godot_executable=godot_executable,
        godot_project=godot_project,
        stack_layers=list(stack_layers),
    )
    if not args.no_launch:
        launch_strategic_application(
            snapshot=snapshot,
            godot_executable=Path(godot_executable),
            project_directory=Path(godot_project),
        )
        result.launched = True
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = build_play_parser().parse_args(list(argv or []))
    try:
        result = run_play(args)
    except PlayerShellError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(result.snapshot_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
