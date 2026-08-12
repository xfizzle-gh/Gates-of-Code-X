from __future__ import annotations

"""Measured command-cycle wrapper for the P8 responsiveness lane (#207).

The frontend command contract remains file-backed and authoritative. This module
adds phase timings around the existing implementation without changing command
semantics, and removes one proven redundant path: ``verify_result`` is read-only,
so it must not rewrite the campaign or republish the full frontend snapshot.

All mutating commands still execute the existing load -> mutate -> save -> full
snapshot publication path until native timings identify the next dominant phase.
"""

import time
from pathlib import Path
from typing import Any

from . import frontend as _frontend
from . import frontend_commands as _commands


_TIMING_KEYS = (
    "load_ms",
    "mutate_ms",
    "save_ms",
    "snapshot_ms",
    "total_ms",
    "campaign_bytes",
    "snapshot_bytes",
    "read_only_fast_path",
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


def measured_apply_frontend_commands(
    campaign_path: str | Path,
    *,
    commands: list[dict[str, Any]] | None = None,
    commands_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the existing command engine and attach phase telemetry.

    ``verify_result`` is the only current read-only frontend operation. For that
    operation the existing command engine is still used, including manifest,
    battle, stack, and save verification. Only its redundant final campaign save
    and snapshot publication are replaced with no-ops. The command queue is still
    cleared by the underlying implementation exactly as before.
    """

    requested = _requested_commands(commands, commands_path)
    read_only_fast_path = _verify_only(requested)

    original_load = _commands.load_campaign
    original_save = _commands.save_campaign
    original_snapshot = _frontend.write_frontend_snapshot

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
            return original_save(
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
        if read_only_fast_path:
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
