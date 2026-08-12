from __future__ import annotations

"""Measured command-cycle wrapper for the P8 responsiveness lane (#207).

The frontend command contract remains file-backed and authoritative. This module
adds phase timings around the existing implementation while removing redundant
presentation work where the command result already contains enough information
for Godot to update its live view safely.

Fast paths are intentionally narrow:

* ``verify_result`` is read-only, so it does not rewrite the campaign or publish
  a frontend snapshot.
* ``issue_move_order`` / ``cancel_move_order`` still load, mutate, ledger, and
  save the authoritative campaign, but skip rebuilding the multi-megabyte
  frontend snapshot. Godot patches only the returned move-order field in memory.
* runtime campaign saves preserve the exact normalization/validation/atomic
  publication contract of ``state_io.save_campaign`` but use deterministic
  compact JSON. Pretty whitespace is not authority, and removing it reduces both
  write volume and the next command's cold-read volume on production Earth3.
* operational movement presentation resolves the authenticated graph once per
  before/after projection instead of once per formation. The graph authority is
  still authenticated on every projection; only repeated presentation lookups
  inside that same projection reuse the already-authenticated payload.

All other mutating commands retain the existing load -> mutate -> save -> full
snapshot publication path.
"""

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from . import frontend as _frontend
from . import frontend_commands as _commands


_SNAPSHOT_PATCH_OPS = frozenset({"issue_move_order", "cancel_move_order"})

_TIMING_KEYS = (
    "load_ms",
    "mutate_ms",
    "save_ms",
    "snapshot_ms",
    "total_ms",
    "campaign_bytes",
    "snapshot_bytes",
    "read_only_fast_path",
    "snapshot_fast_path",
    "compact_save_path",
)


def _requested_commands(
    commands: list[dict[str, Any]] | None,
    commands_path: str | Path | None,
) -> list[dict[str, Any]]:
    if commands is not None:
        return [dict(item) for item in commands]
    if commands_path is None:
        return []
    return _commands.read_commands(commands_path)


def _verify_only(commands: list[dict[str, Any]]) -> bool:
    if not commands:
        return False
    return all(
        str(item.get("op", "")).strip().lower() in _commands.READ_ONLY_OPS
        for item in commands
    )


def _snapshot_patch_only(commands: list[dict[str, Any]]) -> bool:
    if not commands:
        return False
    return all(
        str(item.get("op", "")).strip().lower() in _SNAPSHOT_PATCH_OPS
        for item in commands
    )


def _size(path: str | Path | None) -> int:
    if path is None:
        return 0
    candidate = Path(path)
    try:
        return int(candidate.stat().st_size)
    except OSError:
        return 0


def _milliseconds(seconds: float) -> float:
    return round(max(0.0, seconds) * 1000.0, 3)


def _compact_save_campaign(
    state,
    path: str | Path,
    *,
    observation_context=None,
) -> Path:
    """Runtime-equivalent ``save_campaign`` with deterministic compact JSON.

    Keep every authoritative normalization, observation refresh, validation, and
    atomic replace step from ``state_io.save_campaign``. Only insignificant JSON
    whitespace changes. Keys remain sorted and UTF-8 remains unescaped.
    """

    from .force_migration import ensure_strategic_formations
    from .observation import ensure_s11_schema, refresh_all_observer_knowledge
    from .operational_capture import ensure_site_control_state
    from .operational_movement import ensure_move_orders
    from .operational_position import ensure_operational_positions
    from .operational_supply import refresh_operational_supply
    from .strategic import ensure_strategic_layer

    ensure_strategic_layer(state)
    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    ensure_move_orders(state)
    ensure_site_control_state(state)
    refresh_operational_supply(state, consume_grace=False)
    ensure_s11_schema(state)
    refresh_all_observer_knowledge(state, observation_context)
    state.validate()

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        state.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
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
    return destination


def _bulk_formation_presentation_rows(state) -> dict[str, dict[str, Any]]:
    """Build movement-presentation rows with one graph authentication.

    ``frontend_commands._formation_presentation_rows`` historically called
    ``resolve_display_pixel`` once for every strategic formation. On authenticated
    Earth3 each call re-authenticates the fixed P3 files, so the before/after
    movement presentation pass multiplied that cost by the formation count.

    This helper authenticates the exact same graph once for this projection and
    then resolves every formation from that payload. There is no persistent or
    cross-command graph cache and no change to the authority loader itself.
    """

    from .operational_movement import move_order_to_dict
    from .operational_position import (
        _pixel_from_position,
        load_operational_graph_for_state,
        position_to_dict,
    )

    graph = load_operational_graph_for_state(state)
    rows: dict[str, dict[str, Any]] = {}
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        pixel = None
        if force.position is not None and graph is not None:
            pixel = _pixel_from_position(force.position, graph)
        if pixel is None:
            province = state.provinces.get(force.province_id)
            if province is not None:
                pixel = [int(round(province.x)), int(round(province.y))]
        order = move_order_to_dict(force.move_order) or {}
        rows[force.strategic_formation_id] = {
            "position": position_to_dict(force.position),
            "pixel": pixel,
            "path_node_ids": list(order.get("path_node_ids") or []),
            "path_edge_ids": list(order.get("path_edge_ids") or []),
        }
    return rows


def measured_apply_frontend_commands(
    campaign_path: str | Path,
    *,
    commands: list[dict[str, Any]] | None = None,
    commands_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the existing command engine and attach phase telemetry.

    The existing command engine remains responsible for validation, mutation,
    exactly-once ledger handling, persistence, and result construction. This
    wrapper substitutes proven presentation no-ops, the semantically equivalent
    compact runtime writer, and a bounded bulk presentation projection.
    """

    requested = _requested_commands(commands, commands_path)
    read_only_fast_path = _verify_only(requested)
    snapshot_fast_path = _snapshot_patch_only(requested)

    original_load = _commands.load_campaign
    original_save = _commands.save_campaign
    original_snapshot = _frontend.write_frontend_snapshot
    original_presentation_rows = _commands._formation_presentation_rows

    phase_seconds = {
        "load": 0.0,
        "save": 0.0,
        "snapshot": 0.0,
    }

    def timed_load(path):
        started = time.perf_counter()
        try:
            return original_load(path)
        finally:
            phase_seconds["load"] += time.perf_counter() - started

    def timed_save(state, path, *, observation_context=None):
        if read_only_fast_path:
            return Path(path)
        started = time.perf_counter()
        try:
            return _compact_save_campaign(
                state,
                path,
                observation_context=observation_context,
            )
        finally:
            phase_seconds["save"] += time.perf_counter() - started

    def timed_snapshot(
        state,
        path,
        *,
        campaign_path=None,
        environ=None,
    ):
        if read_only_fast_path or snapshot_fast_path:
            # The previous snapshot remains valid on disk. For move-order draft
            # changes, Godot consumes the authoritative move_order returned in
            # the command result and updates only that live presentation field.
            return Path(path)
        started = time.perf_counter()
        try:
            return original_snapshot(
                state,
                path,
                campaign_path=campaign_path,
                environ=environ,
            )
        finally:
            phase_seconds["snapshot"] += time.perf_counter() - started

    _commands.load_campaign = timed_load
    _commands.save_campaign = timed_save
    _commands._formation_presentation_rows = _bulk_formation_presentation_rows
    _frontend.write_frontend_snapshot = timed_snapshot

    started_total = time.perf_counter()
    try:
        report = _ORIGINAL_APPLY(
            campaign_path,
            commands=requested,
            commands_path=commands_path,
            snapshot_path=snapshot_path,
        )
    finally:
        total_seconds = time.perf_counter() - started_total
        _commands.load_campaign = original_load
        _commands.save_campaign = original_save
        _commands._formation_presentation_rows = original_presentation_rows
        _frontend.write_frontend_snapshot = original_snapshot

    measured_seconds = (
        phase_seconds["load"]
        + phase_seconds["save"]
        + phase_seconds["snapshot"]
    )
    mutate_seconds = max(0.0, total_seconds - measured_seconds)

    result = dict(report)
    result["timings"] = {
        "load_ms": _milliseconds(phase_seconds["load"]),
        "mutate_ms": _milliseconds(mutate_seconds),
        "save_ms": _milliseconds(phase_seconds["save"]),
        "snapshot_ms": _milliseconds(phase_seconds["snapshot"]),
        "total_ms": _milliseconds(total_seconds),
        "campaign_bytes": _size(campaign_path),
        "snapshot_bytes": _size(snapshot_path),
        "read_only_fast_path": bool(read_only_fast_path),
        "snapshot_fast_path": bool(snapshot_fast_path),
        "compact_save_path": not read_only_fast_path,
    }
    return result


_ORIGINAL_APPLY = _commands.apply_frontend_commands


def install_command_cycle_perf_path() -> None:
    """Install the measured wrapper once for CLI and frozen runtime paths."""

    current = _commands.apply_frontend_commands
    if bool(getattr(current, "_goc_issue_207_measured", False)):
        return
    measured_apply_frontend_commands._goc_issue_207_measured = True  # type: ignore[attr-defined]
    _commands.apply_frontend_commands = measured_apply_frontend_commands


def timing_keys() -> tuple[str, ...]:
    """Stable telemetry field names for tests/tooling; values are wall-clock."""

    return _TIMING_KEYS