from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .faction_wiring_compiler import FactionWiringCompiler
from .launcher import launch_game
from .modstack import load_stack_config, normalize_stack
from .expanded_nations_actor_sources import (
    normalize_actor_purchase_ids,
    project_actor_units,
)
from .expanded_nations_compile import clean_compile_source_view
from .expanded_nations_models import (
    ACTIVATION_SCHEMA,
    ACTIVATION_VERSION,
    MANIFEST_RELATIVE,
    OPPONENT_UNITS_RELATIVE,
    RESEARCH_RELATIVE,
    ROSTER_RELATIVE,
    SUPPORTED_TACTICAL_SIDES,
    UNITS_RELATIVE,
    ActivationResult,
    ExpandedNationsError,
    ManagedFile,
    pretty_json,
    select_actor,
    sha256_bytes,
    validate_payload,
)
from .expanded_nations_opponent_render import project_opponent_units
from .expanded_nations_presentation import project_actor_presentation
from .expanded_nations_render import (
    project_research_nodes,
    projection_signature,
    render_opponent_units_file,
    render_research_file,
    render_roster_file,
    render_units_file,
)
from .expanded_nations_storage import (
    deactivate_actor_projection,
    install_projection,
    verify_actor_projection,
    verify_projection_artifacts,
)

__all__ = [
    "ACTIVATION_SCHEMA",
    "ACTIVATION_VERSION",
    "OPPONENT_UNITS_RELATIVE",
    "RESEARCH_RELATIVE",
    "ROSTER_RELATIVE",
    "UNITS_RELATIVE",
    "ActivationResult",
    "ExpandedNationsError",
    "activate_actor_projection",
    "activate_from_stack_config",
    "compile_resolved_factions",
    "deactivate_actor_projection",
    "launch_expanded_nation",
    "verify_actor_projection",
]


def compile_resolved_factions(
    stack_config: str | Path,
) -> tuple[list[Path], dict[str, Any]]:
    roots = load_stack_config(stack_config)
    if not roots:
        raise ExpandedNationsError(
            "Expanded Nations compilation requires an ordered mod stack"
        )
    with clean_compile_source_view(roots[-1]):
        payload = FactionWiringCompiler(roots).compile()
    validate_payload(payload)
    return roots, payload


def activate_from_stack_config(
    stack_config: str | Path,
    actor_id: str,
    *,
    gates_root: str | Path | None = None,
) -> ActivationResult:
    roots, payload = compile_resolved_factions(stack_config)
    return activate_actor_projection(
        payload,
        roots,
        actor_id,
        gates_root=gates_root,
    )


def activate_actor_projection(
    payload: Mapping[str, Any],
    resource_stack: Iterable[str | Path],
    actor_id: str,
    *,
    gates_root: str | Path | None = None,
) -> ActivationResult:
    """Generate one actor-specific native roster and research projection."""

    validate_payload(payload)
    roots = normalize_stack(resource_stack)
    if not roots:
        raise ExpandedNationsError(
            "Expanded Nations activation requires an ordered mod stack"
        )
    final_root = (
        Path(gates_root).expanduser().resolve()
        if gates_root
        else roots[-1]
    )
    if final_root != roots[-1]:
        raise ExpandedNationsError(
            f"Gates root must be the final stack layer: "
            f"expected {roots[-1]}, got {final_root}"
        )
    if not final_root.is_dir():
        raise FileNotFoundError(f"Gates root does not exist: {final_root}")

    actor = select_actor(payload, actor_id)
    side = str(actor["tactical_side"])
    if side not in SUPPORTED_TACTICAL_SIDES:
        raise ExpandedNationsError(
            f"Actor {actor_id} has unsupported tactical side {side}"
        )

    projected_units, projected_body = project_actor_units(
        actor,
        roots,
        final_root,
    )
    if len(projected_units) != int(actor["unit_count"]):
        raise ExpandedNationsError(
            f"Actor {actor_id} projected {len(projected_units)} units, "
            f"expected {actor['unit_count']}"
        )
    native_actor = normalize_actor_purchase_ids(actor, projected_units)
    opponent_units, opponent_body = project_opponent_units(side, roots)
    projected_research = project_research_nodes(native_actor)
    presentation_outputs = project_actor_presentation(native_actor, roots)

    outputs: dict[Path, bytes] = {
        ROSTER_RELATIVE: render_roster_file(native_actor).encode("utf-8"),
        UNITS_RELATIVE: render_units_file(
            native_actor,
            projected_units,
            projected_body,
        ).encode("utf-8"),
        OPPONENT_UNITS_RELATIVE: render_opponent_units_file(
            native_actor,
            opponent_units,
            opponent_body,
        ).encode("utf-8"),
        RESEARCH_RELATIVE[side]: render_research_file(
            native_actor,
            projected_research,
        ).encode("utf-8"),
        **presentation_outputs,
    }
    signature = projection_signature(
        native_actor,
        payload,
        outputs,
        projected_units,
    )
    managed = tuple(
        ManagedFile(relative.as_posix(), sha256_bytes(data), len(data))
        for relative, data in sorted(
            outputs.items(),
            key=lambda item: item[0].as_posix(),
        )
    )
    manifest_payload = {
        "schema": ACTIVATION_SCHEMA,
        "schema_version": ACTIVATION_VERSION,
        "actor_id": native_actor["actor_id"],
        "display_name": native_actor["display_name"],
        "tactical_side": side,
        "playable": bool(native_actor["playable"]),
        "unit_count": len(projected_units),
        "opponent_entry_count": len(opponent_units),
        "research_node_count": len(projected_research),
        "wiring_signature": payload["wiring_signature"],
        "stack_signature": payload["stack_signature"],
        "projection_signature": signature,
        "files": [asdict(item) for item in managed],
        "units": [asdict(item) for item in projected_units],
        "opponent_units": [asdict(item) for item in opponent_units],
        "research_nodes": [asdict(item) for item in projected_research],
        "presentation_files": [
            path.as_posix()
            for path in sorted(
                presentation_outputs,
                key=lambda item: item.as_posix(),
            )
        ],
    }
    verify_projection_artifacts(outputs, manifest_payload)
    install_projection(
        final_root,
        outputs,
        pretty_json(manifest_payload).encode("utf-8"),
        post_commit_verify=lambda: verify_actor_projection(final_root),
    )
    return ActivationResult(
        actor_id=str(native_actor["actor_id"]),
        display_name=str(native_actor["display_name"]),
        tactical_side=side,
        unit_count=len(projected_units),
        research_node_count=len(projected_research),
        wiring_signature=str(payload["wiring_signature"]),
        projection_signature=signature,
        manifest_path=str(final_root / MANIFEST_RELATIVE),
        files=managed,
    )


def launch_expanded_nation(
    stack_config: str | Path,
    actor_id: str,
    game_directory: str | Path,
    *,
    gates_root: str | Path | None = None,
    extra_args: Sequence[str] | None = None,
) -> ActivationResult:
    result = activate_from_stack_config(
        stack_config,
        actor_id,
        gates_root=gates_root,
    )
    launch_game(game_directory, list(extra_args or ()))
    return result
