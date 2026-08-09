from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from .expanded_nations import (
    activate_actor_projection,
    compile_resolved_factions,
    deactivate_actor_projection,
    verify_actor_projection,
)
from .expanded_nations_models import (
    MANIFEST_RELATIVE,
    ExpandedNationsError,
    all_managed_candidates,
    pretty_json,
    validate_payload,
)
from .modstack import normalize_stack

MATRIX_SCHEMA = "gates-of-codex.expanded-nations-projection-matrix"
MATRIX_VERSION = 3


def build_projection_matrix(
    payload: Mapping[str, Any],
    resource_stack: Iterable[str | Path],
    *,
    gates_root: str | Path | None = None,
    source_head: str = "",
) -> dict[str, Any]:
    """Exercise every playable actor against the exact installed source stack.

    Matrix generation is intentionally Core-only. Each actor is activated,
    semantically verified, recorded, and restored to Core before the next actor.
    This prevents generated overlays from becoming source authority and leaves the
    user's installation in canonical Core mode even when a later actor fails.
    """

    validate_payload(payload)
    roots = normalize_stack(resource_stack)
    if not roots:
        raise ExpandedNationsError("Projection matrix requires an ordered mod stack")
    final_root = Path(gates_root).expanduser().resolve() if gates_root else roots[-1]
    if final_root != roots[-1]:
        raise ExpandedNationsError(
            f"Gates root must be the final stack layer: expected {roots[-1]}, got {final_root}"
        )
    if not final_root.is_dir():
        raise FileNotFoundError(f"Gates root does not exist: {final_root}")

    manifest_path = final_root / MANIFEST_RELATIVE
    if manifest_path.exists():
        verify_actor_projection(final_root)
        raise ExpandedNationsError(
            "Projection matrix generation requires Core mode; restore Core before running the matrix"
        )
    occupied = [path for path in all_managed_candidates(final_root) if path.exists()]
    if occupied:
        raise ExpandedNationsError(
            "Projection matrix refuses unmanaged generated-path occupants: "
            + ", ".join(str(path) for path in occupied)
        )

    playable = sorted(
        (row for row in payload["actors"] if bool(row.get("playable"))),
        key=lambda row: str(row["actor_id"]),
    )
    rows: dict[str, dict[str, Any]] = {}
    try:
        for actor in playable:
            actor_id = str(actor["actor_id"])
            result = activate_actor_projection(
                payload,
                roots,
                actor_id,
                gates_root=final_root,
            )
            manifest = verify_actor_projection(final_root)
            if manifest.get("projection_signature") != result.projection_signature:
                raise ExpandedNationsError(
                    f"Projection matrix signature mismatch after activation: {actor_id}"
                )
            rows[actor_id] = {
                "display_name": result.display_name,
                "tactical_side": result.tactical_side,
                "unit_count": result.unit_count,
                "opponent_entry_count": int(manifest["opponent_entry_count"]),
                "research_node_count": result.research_node_count,
                "projection_signature": result.projection_signature,
                "managed_files": {
                    item.relative_path: item.sha256
                    for item in sorted(result.files, key=lambda item: item.relative_path)
                },
            }
            if not deactivate_actor_projection(final_root):
                raise ExpandedNationsError(
                    f"Projection matrix failed to restore Core after actor {actor_id}"
                )
    finally:
        if manifest_path.exists():
            deactivate_actor_projection(final_root)

    leftovers = [path for path in all_managed_candidates(final_root) if path.exists()]
    if leftovers:
        raise ExpandedNationsError(
            "Projection matrix left generated artifacts after Core restoration: "
            + ", ".join(str(path) for path in leftovers)
        )

    return {
        "schema": MATRIX_SCHEMA,
        "schema_version": MATRIX_VERSION,
        "evidence_state": "complete",
        "source_head": source_head,
        "playable_actor_count": len(playable),
        "wiring_signature": str(payload["wiring_signature"]),
        "stack_signature": str(payload["stack_signature"]),
        "manifest_sha256": str(payload.get("manifest_sha256", "")),
        "actors": rows,
    }


def generate_projection_matrix_from_stack_config(
    stack_config: str | Path,
    *,
    gates_root: str | Path | None = None,
    source_head: str = "",
) -> dict[str, Any]:
    roots, payload = compile_resolved_factions(stack_config)
    final_root = Path(gates_root).expanduser().resolve() if gates_root else roots[-1]
    _verify_git_exact_head(final_root, source_head)
    return build_projection_matrix(
        payload,
        roots,
        gates_root=gates_root,
        source_head=source_head,
    )


def _verify_git_exact_head(root: Path, expected_head: str) -> None:
    if not expected_head:
        raise ExpandedNationsError("Projection matrix requires an exact source head")
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if head.returncode != 0:
        raise ExpandedNationsError(
            "Projection matrix could not verify the Gates Git head: "
            + head.stderr.strip()
        )
    actual_head = head.stdout.strip()
    if actual_head != expected_head:
        raise ExpandedNationsError(
            f"Projection matrix source-head mismatch: expected {expected_head}, got {actual_head}"
        )
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise ExpandedNationsError(
            "Projection matrix could not verify the Gates working tree: "
            + status.stderr.strip()
        )
    if status.stdout.strip():
        raise ExpandedNationsError(
            "Projection matrix requires a completely clean Gates working tree before generation"
        )


def render_projection_matrix_markdown(matrix: Mapping[str, Any]) -> str:
    if matrix.get("schema") != MATRIX_SCHEMA or matrix.get("schema_version") != MATRIX_VERSION:
        raise ExpandedNationsError("Unsupported projection matrix evidence")
    if matrix.get("evidence_state") != "complete":
        raise ExpandedNationsError("Projection matrix evidence is not complete")
    actors = matrix.get("actors")
    if not isinstance(actors, dict) or len(actors) != int(matrix.get("playable_actor_count", -1)):
        raise ExpandedNationsError("Projection matrix actor count is inconsistent")

    lines = [
        "# Expanded Nations projection matrix",
        "",
        "This matrix was generated from the exact installed five-layer stack by activating,",
        "semantically verifying, and restoring Core mode for every playable actor.",
        "",
        f"- Source head: `{matrix.get('source_head') or 'not recorded'}`",
        f"- Wiring signature: `{matrix.get('wiring_signature', '')}`",
        f"- Stack signature: `{matrix.get('stack_signature', '')}`",
        f"- Playable actors: {matrix.get('playable_actor_count', 0)}",
        "",
        "| Actor | Tactical side | Actor units | Preserved opponent entries | Research nodes | Projection signature |",
        "|---|---|---:|---:|---:|---|",
    ]
    for actor_id, row in sorted(actors.items()):
        lines.append(
            f"| {actor_id} | {row['tactical_side']} | {row['unit_count']} | "
            f"{row['opponent_entry_count']} | {row['research_node_count']} | "
            f"`{row['projection_signature']}` |"
        )
    lines.extend(
        [
            "",
            "This is deterministic implementation-side source and projection validation.",
            "It is not native Gates of Hell gameplay acceptance or merge approval.",
            "",
        ]
    )
    return "\n".join(lines)


def write_projection_matrix_evidence(
    matrix: Mapping[str, Any],
    *,
    json_output: str | Path,
    markdown_output: str | Path,
) -> None:
    json_path = Path(json_output)
    markdown_path = Path(markdown_output)
    json_bytes = pretty_json(matrix).encode("utf-8")
    markdown_bytes = render_projection_matrix_markdown(matrix).encode("utf-8")
    staged: list[tuple[Path, Path]] = []
    try:
        for target, data in ((json_path, json_bytes), (markdown_path, markdown_bytes)):
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(data)
            staged.append((target, temporary))
        for target, temporary in staged:
            os.replace(temporary, target)
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)


def invalidated_projection_evidence(
    *,
    invalidated_by_head: str,
    reason: str,
    invalidated_actor_ids: Iterable[str],
) -> dict[str, Any]:
    return {
        "schema": MATRIX_SCHEMA,
        "schema_version": MATRIX_VERSION,
        "evidence_state": "invalidated",
        "invalidated_by_head": invalidated_by_head,
        "invalidation_reason": reason,
        "invalidated_actor_ids": sorted(set(invalidated_actor_ids)),
        "playable_actor_count": 21,
        "actors": {},
    }


def load_projection_matrix(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if payload.get("schema") != MATRIX_SCHEMA or payload.get("schema_version") != MATRIX_VERSION:
        raise ExpandedNationsError(f"Unsupported projection matrix file: {path}")
    state = payload.get("evidence_state")
    if state == "complete":
        actors = payload.get("actors")
        if not isinstance(actors, dict) or len(actors) != int(payload.get("playable_actor_count", -1)):
            raise ExpandedNationsError("Complete projection matrix has inconsistent actor rows")
        for actor_id, row in actors.items():
            required = {
                "display_name",
                "tactical_side",
                "unit_count",
                "opponent_entry_count",
                "research_node_count",
                "projection_signature",
                "managed_files",
            }
            if set(row) != required or not row["projection_signature"]:
                raise ExpandedNationsError(
                    f"Complete projection matrix row is malformed: {actor_id}"
                )
    elif state == "invalidated":
        if payload.get("actors") != {} or not payload.get("invalidation_reason"):
            raise ExpandedNationsError("Invalidated projection evidence must not retain actor signatures")
    else:
        raise ExpandedNationsError("Projection matrix evidence_state is invalid")
    return payload
