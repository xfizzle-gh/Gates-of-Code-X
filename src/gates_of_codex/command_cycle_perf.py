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
* ``end_player_round`` still performs the full authoritative save, but publishes
  a bounded runtime patch instead of rebuilding/re-writing the static Earth3
  frontend snapshot. Godot validates the patch into a candidate copy before
  atomically replacing its live dynamic state.
* runtime campaign saves preserve the exact normalization/validation/atomic
  publication contract of ``state_io.save_campaign`` but use deterministic
  compact JSON. Pretty whitespace is not authority, and removing it reduces both
  write volume and the next command's cold-read volume on production Earth3.
* schema-11 runtime saves serialize the already-validated dataclass graph
  directly instead of first materializing ``dataclasses.asdict``'s second deep
  copy of the entire campaign. Legacy schemas retain ``CampaignState.to_dict``
  so their historical field-pruning contract is unchanged.
* operational movement presentation resolves the authenticated graph once per
  before/after projection instead of once per formation.
* one frontend command uses one authenticated P3 graph snapshot. The first P3
  authority request still performs the full fail-closed fixed-file authentication;
  later requests during that same atomic command reuse a detached copy. The cache
  is discarded and the authority loader restored before the command returns, so
  the next command authenticates again.

Other mutating commands retain the existing load -> mutate -> save -> full
snapshot publication path.
"""

import copy
import json
import tempfile
import time
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from . import frontend as _frontend
from . import frontend_commands as _commands


_SNAPSHOT_PATCH_OPS = frozenset({"issue_move_order", "cancel_move_order"})
_RUNTIME_PATCH_OPS = frozenset({"end_player_round", "auto_resolve"})
_LIVE_MOVE_BATCH = ("issue_move_order", "commit_move_orders")

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


def _command_ops(commands: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("op", "")).strip().lower() for item in commands]


def _is_live_move_batch(commands: list[dict[str, Any]]) -> bool:
    return _command_ops(commands) == list(_LIVE_MOVE_BATCH)


def _snapshot_patch_only(commands: list[dict[str, Any]]) -> bool:
    if not commands:
        return False
    return all(op in _SNAPSHOT_PATCH_OPS for op in _command_ops(commands))


def _runtime_patch_only(commands: list[dict[str, Any]]) -> bool:
    if _is_live_move_batch(commands):
        return True
    if not commands:
        return False
    return all(op in _RUNTIME_PATCH_OPS for op in _command_ops(commands))


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


def _runtime_json_default(value: Any) -> Any:
    """Expose dataclass fields without recursively cloning their payloads."""

    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    raise TypeError(
        f"Object of type {value.__class__.__name__} is not JSON serializable"
    )


def _runtime_state_json(state) -> str:
    """Return byte-equivalent compact JSON semantics without schema-11 asdict."""

    source = state if int(getattr(state, "schema_version", 0)) >= 11 else state.to_dict()
    return json.dumps(
        source,
        default=_runtime_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _timed_save_step(
    timings: dict[str, float] | None,
    name: str,
    action: Callable[[], Any],
) -> Any:
    started = time.perf_counter()
    try:
        return action()
    finally:
        if timings is not None:
            timings[name] = timings.get(name, 0.0) + (time.perf_counter() - started)


def _profiled_campaign_validation(
    state,
    timings: dict[str, float] | None,
) -> None:
    """Run the exact validator while exposing its dominant nested authorities.

    This is instrumentation only. The same CampaignState.validate() executes and
    every imported authority validator remains in force. Wrappers are restored in
    a finally block before the command returns.
    """

    from . import earth3_bootstrap as _earth3_bootstrap
    from . import earth3_fixture_authority as _earth3_fixture_authority
    from . import observation as _observation

    original_bootstrap_validate = _earth3_bootstrap.validate_earth3_bootstrap_campaign_state
    original_load_bootstrap = _earth3_bootstrap.load_earth3_bootstrap
    original_operational_validate = _earth3_fixture_authority.validate_earth3_operational_authority
    original_observation_validate = _observation.validate_s11_observer_authority
    nested: dict[str, float] = {}

    def timed_load_bootstrap(*, authority_root=None):
        return _timed_save_step(
            nested,
            "validate_bootstrap_bundle",
            lambda: original_load_bootstrap(authority_root=authority_root),
        )

    def timed_operational_validate(candidate_state):
        return _timed_save_step(
            nested,
            "validate_operational_authority",
            lambda: original_operational_validate(candidate_state),
        )

    def timed_bootstrap_validate(candidate_state):
        return _timed_save_step(
            nested,
            "validate_earth3_bootstrap",
            lambda: original_bootstrap_validate(candidate_state),
        )

    def timed_observation_validate(candidate_state):
        return _timed_save_step(
            nested,
            "validate_s11_authority",
            lambda: original_observation_validate(candidate_state),
        )

    _earth3_bootstrap.load_earth3_bootstrap = timed_load_bootstrap
    _earth3_fixture_authority.validate_earth3_operational_authority = timed_operational_validate
    _earth3_bootstrap.validate_earth3_bootstrap_campaign_state = timed_bootstrap_validate
    _observation.validate_s11_observer_authority = timed_observation_validate
    started = time.perf_counter()
    try:
        state.validate()
    finally:
        total = time.perf_counter() - started
        _earth3_bootstrap.load_earth3_bootstrap = original_load_bootstrap
        _earth3_fixture_authority.validate_earth3_operational_authority = original_operational_validate
        _earth3_bootstrap.validate_earth3_bootstrap_campaign_state = original_bootstrap_validate
        _observation.validate_s11_observer_authority = original_observation_validate
        if timings is not None:
            for name, seconds in nested.items():
                timings[name] = timings.get(name, 0.0) + seconds
            top_level_nested = (
                nested.get("validate_earth3_bootstrap", 0.0)
                + nested.get("validate_s11_authority", 0.0)
            )
            timings["validate_base"] = timings.get("validate_base", 0.0) + max(
                0.0, total - top_level_nested
            )


def _ensure_runtime_operational_positions(state) -> Any:
    """Normalize positions only when the save path can actually repair them.

    For an authenticated Earth3 P3 campaign, ``ensure_operational_positions`` is
    deliberately validate-only: it immediately runs
    ``validate_earth3_p3_campaign_extension`` and returns without mutating the
    campaign. The final ``state.validate()`` in this same authoritative save runs
    ``validate_earth3_bootstrap_campaign_state``, which invokes that exact P3
    extension validator again after all save-time normalizers have completed.

    Repeating the earlier validate-only pass cost roughly one native second per
    save. Skip only that duplicate P3 pass. Non-P3 and migratable campaigns still
    execute ``ensure_operational_positions(state)`` normally.
    """

    from .earth3_operational import P3_AUTHORITY_METADATA_KEY
    from .operational_position import ensure_operational_positions

    metadata = getattr(state, "map_metadata", {})
    if isinstance(metadata, dict) and P3_AUTHORITY_METADATA_KEY in metadata:
        return None
    return ensure_operational_positions(state)


def _compact_save_campaign(
    state,
    path: str | Path,
    *,
    observation_context=None,
    subphase_seconds: dict[str, float] | None = None,
) -> Path:
    """Runtime-equivalent ``save_campaign`` with deterministic compact JSON.

    Keep every authoritative normalization, observation refresh, validation, and
    atomic replace step from ``state_io.save_campaign``. The save subphases are
    timed independently so #207 optimization is based on native evidence rather
    than aggregate guesses.
    """

    from .observation import ensure_s11_schema, refresh_all_observer_knowledge
    from .operational_capture import ensure_site_control_state
    from .operational_movement import ensure_move_orders
    from .operational_supply import refresh_operational_supply
    from .strategic import ensure_strategic_layer

    # ensure_strategic_layer already invokes ensure_strategic_formations. Do not
    # run the same full formation normalization a second time during every save.
    _timed_save_step(subphase_seconds, "strategic", lambda: ensure_strategic_layer(state))
    _timed_save_step(
        subphase_seconds,
        "positions",
        lambda: _ensure_runtime_operational_positions(state),
    )
    _timed_save_step(subphase_seconds, "orders", lambda: ensure_move_orders(state))
    _timed_save_step(subphase_seconds, "site_control", lambda: ensure_site_control_state(state))
    _timed_save_step(
        subphase_seconds,
        "supply",
        lambda: refresh_operational_supply(state, consume_grace=False),
    )
    _timed_save_step(subphase_seconds, "s11_schema", lambda: ensure_s11_schema(state))
    _timed_save_step(
        subphase_seconds,
        "observer_refresh",
        lambda: refresh_all_observer_knowledge(state, observation_context),
    )
    _timed_save_step(
        subphase_seconds,
        "validate",
        lambda: _profiled_campaign_validation(state, subphase_seconds),
    )

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _timed_save_step(
        subphase_seconds,
        "encode",
        lambda: _runtime_state_json(state) + "\n",
    )

    def write_atomic() -> None:
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

    _timed_save_step(subphase_seconds, "write", write_atomic)
    return destination


def _bulk_formation_presentation_rows(state) -> dict[str, dict[str, Any]]:
    """Build movement-presentation rows with one graph authentication."""

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
    """Run the existing command engine and attach phase telemetry."""

    from . import earth3_operational as _earth3_operational
    from .frontend_runtime_patch import (
        build_frontend_runtime_patch,
        persist_runtime_patched_snapshot,
    )

    requested = _requested_commands(commands, commands_path)
    read_only_fast_path = _verify_only(requested)
    snapshot_fast_path = _snapshot_patch_only(requested)
    runtime_patch_fast_path = _runtime_patch_only(requested)

    original_load = _commands.load_campaign
    original_save = _commands.save_campaign
    original_snapshot = _frontend.write_frontend_snapshot
    original_presentation_rows = _commands._formation_presentation_rows
    original_p3_auth = _earth3_operational.load_authenticated_p3_graph

    phase_seconds = {
        "load": 0.0,
        "save": 0.0,
        "snapshot": 0.0,
    }
    save_subphase_seconds: dict[str, float] = {}
    p3_auth_cache: dict[str, dict[str, Any]] = {}
    p3_auth_stats = {"loads": 0, "hits": 0}
    runtime_patch: dict[str, Any] | None = None

    def scoped_p3_auth(*, repository_root=None):
        cache_key = (
            "<default>"
            if repository_root is None
            else str(Path(repository_root).expanduser().resolve(strict=False))
        )
        cached = p3_auth_cache.get(cache_key)
        if cached is not None:
            p3_auth_stats["hits"] += 1
            return copy.deepcopy(cached)
        graph = original_p3_auth(repository_root=repository_root)
        p3_auth_stats["loads"] += 1
        p3_auth_cache[cache_key] = copy.deepcopy(graph)
        return copy.deepcopy(graph)

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
                subphase_seconds=save_subphase_seconds,
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
        nonlocal runtime_patch
        if read_only_fast_path or snapshot_fast_path:
            return Path(path)
        if runtime_patch_fast_path:
            started = time.perf_counter()
            try:
                runtime_patch = build_frontend_runtime_patch(
                    state,
                    campaign_path=campaign_path,
                    snapshot_path=path,
                    environ=environ,
                )
                persist_runtime_patched_snapshot(path, runtime_patch)
                return Path(path)
            finally:
                phase_seconds["snapshot"] += time.perf_counter() - started
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
    _earth3_operational.load_authenticated_p3_graph = scoped_p3_auth

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
        _earth3_operational.load_authenticated_p3_graph = original_p3_auth
        p3_auth_cache.clear()

    measured_seconds = (
        phase_seconds["load"]
        + phase_seconds["save"]
        + phase_seconds["snapshot"]
    )
    mutate_seconds = max(0.0, total_seconds - measured_seconds)

    result = dict(report)
    if runtime_patch is not None:
        result["frontend_patch"] = runtime_patch
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
        "runtime_patch_fast_path": bool(runtime_patch_fast_path),
        "p3_auth_loads": int(p3_auth_stats["loads"]),
        "p3_auth_cache_hits": int(p3_auth_stats["hits"]),
        **{
            f"save_{name}_ms": _milliseconds(seconds)
            for name, seconds in sorted(save_subphase_seconds.items())
        },
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