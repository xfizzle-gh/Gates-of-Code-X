"""P6 player-runtime contracts for explicit GoH handoff configuration.

P5 deliberately refuses to guess a Conquest status template when a profile has
multiple ordinary saves or Gates-generated saves belonging to another strategic
campaign. P6 owner-native acceptance uses the same fail-closed authority. This
module adds a player-facing explicit template input and makes the button labelled
"Launch Battle in GoH" actually request a game launch, without weakening P5's
template selection or dependency identity rules.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any


_TEMPLATE_SAVE: ContextVar[str] = ContextVar(
    "gates_of_codex_p6_template_save",
    default="",
)


def validate_status_template(value: str | Path | None) -> str:
    """Return one canonical valid Conquest template path or fail closed."""
    text = str(value or "").strip()
    if not text:
        return ""

    from .bridge.archive import CampaignSaveArchive
    from .player_shell import PlayerShellError

    candidate = Path(text).expanduser()
    if not candidate.is_file():
        raise PlayerShellError(
            f"--template-save is not an existing Conquest save: {candidate}"
        )
    resolved = candidate.resolve()
    try:
        CampaignSaveArchive().validate(resolved)
    except (OSError, ValueError) as exc:
        raise PlayerShellError(
            f"--template-save is not a valid Conquest save: {resolved}: {exc}"
        ) from exc
    return str(resolved)


def append_template_launch_args(block: dict[str, Any], template_save: str) -> dict[str, Any]:
    """Persist an explicit template through Godot New/Continue replay args."""
    result = dict(block)
    template = str(template_save or "").strip()
    for key in ("new_args", "continue_args"):
        values = list(result.get(key, []) or [])
        if template and "--template-save" not in values:
            values.extend(["--template-save", template])
        result[key] = values
    return result


def handoff_with_player_launch(raw: dict[str, Any]) -> dict[str, Any]:
    """Default the player-facing handoff to launch GoH, preserving explicit false."""
    effective = dict(raw)
    effective.setdefault("launch", True)
    return effective


def install_p6_handoff_runtime_contracts() -> None:
    """Install idempotent player-shell/frontend handoff adapters."""
    from . import frontend, frontend_commands, player_shell

    current_parser = player_shell.build_play_parser
    if not getattr(current_parser, "_goc_p6_template_arg", False):
        original_parser = current_parser

        def build_play_parser_with_template():
            parser = original_parser()
            if not any(action.dest == "template_save" for action in parser._actions):
                parser.add_argument(
                    "--template-save",
                    help=(
                        "Explicit valid Conquest save used only as the saveinfo "
                        "template for tactical handoff"
                    ),
                )
            return parser

        build_play_parser_with_template._goc_p6_template_arg = True  # type: ignore[attr-defined]
        player_shell.build_play_parser = build_play_parser_with_template

    current_run = player_shell.run_play
    if not getattr(current_run, "_goc_p6_template_context", False):
        original_run = current_run

        def run_play_with_template(args, *positional, **kwargs):
            raw = getattr(args, "template_save", None)
            template = validate_status_template(raw) if raw else ""
            token = _TEMPLATE_SAVE.set(template)
            try:
                return original_run(args, *positional, **kwargs)
            finally:
                _TEMPLATE_SAVE.reset(token)

        run_play_with_template._goc_p6_template_context = True  # type: ignore[attr-defined]
        player_shell.run_play = run_play_with_template

    current_persist = player_shell.persist_launch_settings
    if not getattr(current_persist, "_goc_p6_template_persist", False):
        original_persist = current_persist

        def persist_launch_settings_with_template(state, *positional, **kwargs):
            result = original_persist(state, *positional, **kwargs)
            template = _TEMPLATE_SAVE.get().strip()
            if template:
                state.map_metadata["status_template_path"] = template
            return result

        persist_launch_settings_with_template._goc_p6_template_persist = True  # type: ignore[attr-defined]
        player_shell.persist_launch_settings = persist_launch_settings_with_template

    current_play_block = frontend._player_launch_block
    if not getattr(current_play_block, "_goc_p6_template_replay", False):
        original_play_block = current_play_block

        def player_launch_block_with_template(state, campaign_path):
            block = original_play_block(state, campaign_path)
            template = str(state.map_metadata.get("status_template_path", "") or "").strip()
            return append_template_launch_args(block, template)

        player_launch_block_with_template._goc_p6_template_replay = True  # type: ignore[attr-defined]
        frontend._player_launch_block = player_launch_block_with_template

    current_handoff = frontend_commands._apply_handoff
    if not getattr(current_handoff, "_goc_p6_player_launch", False):
        original_handoff = current_handoff

        def apply_handoff_with_player_launch(campaign, state, raw):
            return original_handoff(
                campaign,
                state,
                handoff_with_player_launch(raw),
            )

        apply_handoff_with_player_launch._goc_p6_player_launch = True  # type: ignore[attr-defined]
        frontend_commands._apply_handoff = apply_handoff_with_player_launch
