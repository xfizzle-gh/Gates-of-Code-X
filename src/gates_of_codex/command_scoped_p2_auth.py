from __future__ import annotations

"""Authenticated Earth3 P1/P2 authority reuse for the #207/#212 hot path.

The immutable P1/P2 authority must remain fail-closed at every command boundary.
The expensive part is not proving which bytes are present; it is reparsing those
same approved bytes into the same semantic authority and walking the 3.5k-
province geometry contract repeatedly.

This module therefore has two deliberately separate cache layers:

* process-scoped semantic caches are keyed by the exact raw identities captured
  through the existing canonical/symlink/TOCTOU-safe authority readers. Every
  lookup still re-reads and hashes the fixed files. A changed byte produces a new
  key and forces the original full semantic loader, which retains all rejection
  conditions. Cached values are detached before return and the caches are small.
* command-scoped P2 reuse keeps the existing optimization: after the first exact
  authentication in one atomic frontend command, nested validators receive
  detached copies without re-reading the same fixed bundle again.

The daemon's normal authenticated campaign load occurs after these wrappers are
installed, so it warms the semantic caches without adding a new trust path. A
one-shot/source command that installs the same seam receives identical behavior.
"""

import copy
import functools
import hashlib
import time
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path
from threading import RLock
from typing import Any, Callable


_PROCESS_CACHE_MAX = 4
_PROCESS_CACHE_LOCK = RLock()
_P1_SEMANTIC_CACHE: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
_P2_SEMANTIC_CACHE: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
_PROCESS_STATS = {
    "p1_semantic_loads": 0,
    "p1_semantic_hits": 0,
    "p2_semantic_loads": 0,
    "p2_semantic_hits": 0,
}
_AI_PROFILE_EVENTS: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "goc_issue212_ai_profile_events",
    default=None,
)
_ROUND_ADVANCE_EVENTS: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "goc_issue212_round_advance_events",
    default=None,
)
_ROUND_ADVANCE_ACTIVE: ContextVar[bool] = ContextVar(
    "goc_issue212_round_advance_active",
    default=False,
)
_AUTH_PROFILE_EVENTS: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "goc_issue212_authority_profile_events",
    default=None,
)


def _authority_key(authority_root: str | Path | None) -> str:
    if authority_root is None:
        return "<default>"
    return str(Path(authority_root).expanduser().resolve(strict=False))


def _cache_get(cache: OrderedDict[tuple[Any, ...], Any], key: tuple[Any, ...]) -> Any | None:
    with _PROCESS_CACHE_LOCK:
        value = cache.get(key)
        if value is None:
            return None
        cache.move_to_end(key)
        return copy.deepcopy(value)


def _cache_put(cache: OrderedDict[tuple[Any, ...], Any], key: tuple[Any, ...], value: Any) -> None:
    with _PROCESS_CACHE_LOCK:
        cache[key] = copy.deepcopy(value)
        cache.move_to_end(key)
        while len(cache) > _PROCESS_CACHE_MAX:
            cache.popitem(last=False)


def _process_stats_snapshot() -> dict[str, int]:
    with _PROCESS_CACHE_LOCK:
        return {key: int(value) for key, value in _PROCESS_STATS.items()}


def _increment_stat(name: str) -> None:
    with _PROCESS_CACHE_LOCK:
        _PROCESS_STATS[name] = int(_PROCESS_STATS.get(name, 0)) + 1


def _clear_process_semantic_caches_for_tests() -> None:
    """Test-only reset. Runtime callers should never clear authenticated reuse."""

    with _PROCESS_CACHE_LOCK:
        _P1_SEMANTIC_CACHE.clear()
        _P2_SEMANTIC_CACHE.clear()
        for key in _PROCESS_STATS:
            _PROCESS_STATS[key] = 0


def _profiled_authority_call(name: str, action: Callable[[], Any]) -> Any:
    events = _AUTH_PROFILE_EVENTS.get()
    if events is None:
        return action()
    started = time.perf_counter()
    try:
        return action()
    finally:
        events.append(
            {
                "phase": name,
                "ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
        )


def _capture_p1_identity(authority_root: str | Path | None) -> tuple[Any, ...]:
    """Re-authenticate exact fixed P1 bytes without skipping path safety."""

    from . import earth3_campaign as p1

    requested_root = Path(authority_root) if authority_root is not None else p1._default_authority_root()
    root = p1._canonical_authority_root(requested_root)
    manifest = p1._read_fixed_authority_json(root, p1.EARTH3_MANIFEST_PATH, "Earth3 manifest")
    dataset = p1._read_fixed_authority_json(root, p1.EARTH3_DATASET_PATH, "Earth3 production dataset")
    metadata = p1._read_fixed_authority_json(root, p1.EARTH3_METADATA_PATH, "Earth3 dataset metadata")
    production = p1._read_fixed_authority_json(
        root,
        p1.EARTH3_PRODUCTION_AUTHORITY_PATH,
        "Earth3 production authority",
    )

    if manifest.raw_sha256 != p1.APPROVED_MANIFEST_SHA256:
        raise p1.Earth3AuthorityError(
            "Earth3 manifest SHA-256 mismatch: "
            f"expected {p1.APPROVED_MANIFEST_SHA256}, got {manifest.raw_sha256}"
        )
    if dataset.raw_sha256 != p1.APPROVED_DATASET_RAW_SHA256:
        raise p1.Earth3AuthorityError(
            "Earth3 production dataset bytes/SHA-256 mismatch: "
            f"expected raw digest {p1.APPROVED_DATASET_RAW_SHA256}, got {dataset.raw_sha256}"
        )
    if dataset.raw_bytes[-1:] != b"\n":
        raise p1.Earth3AuthorityError(
            "Earth3 production dataset bytes/SHA-256 mismatch: expected one terminal LF"
        )
    embedded = hashlib.sha256(dataset.raw_bytes[:-1]).hexdigest()
    if embedded != p1.APPROVED_EMBEDDED_DATASET_SHA256:
        raise p1.Earth3AuthorityError(
            "Earth3 production dataset bytes/SHA-256 mismatch: "
            f"expected embedded digest {p1.APPROVED_EMBEDDED_DATASET_SHA256}, got {embedded}"
        )
    if (
        manifest.raw_sha256,
        dataset.raw_sha256,
        embedded,
    ) not in p1._APPROVED_EXACT_BYTE_IDENTITIES:
        raise p1.Earth3AuthorityError(
            "Earth3 owner provenance is not an accepted exact-byte contract"
        )
    return (
        str(root),
        manifest.raw_sha256,
        dataset.raw_sha256,
        embedded,
        metadata.raw_sha256,
        production.raw_sha256,
    )


def _capture_p2_identity(
    authority_root: str | Path | None,
    *,
    authenticated_p1: Any,
) -> tuple[Any, ...]:
    """Re-authenticate every fixed P2 file and bind it to current P1 authority."""

    from . import earth3_bootstrap as p2

    root = p2._canonical_data_root(p2._bootstrap_data_root())
    try:
        present = sorted(path.name for path in root.iterdir())
    except OSError as exc:
        raise p2.Earth3BootstrapError("Earth3 P2 data directory cannot be enumerated") from exc
    if present != list(p2._FIXED_FILES):
        raise p2.Earth3BootstrapError(
            f"unexpected bootstrap file set: expected={list(p2._FIXED_FILES)} got={present}"
        )
    raw_hashes: list[tuple[str, str]] = []
    for filename in p2._FIXED_FILES:
        captured = p2._read_fixed_bootstrap_json(root, filename)
        expected = p2._APPROVED_RAW_FILE_SHA256.get(filename)
        if expected is None:
            raise p2.Earth3BootstrapError("P2 approved raw-file contract is incomplete")
        if captured.raw_sha256 != expected:
            raise p2.Earth3BootstrapError(
                f"{filename} raw SHA-256 mismatch: expected {expected}, got {captured.raw_sha256}"
            )
        raw_hashes.append((filename, captured.raw_sha256))
    if set(p2._APPROVED_RAW_FILE_SHA256) != set(p2._FIXED_FILES):
        raise p2.Earth3BootstrapError("P2 approved raw-file contract is incomplete")

    p1_identity = (
        str(authenticated_p1.root),
        authenticated_p1.manifest_sha256,
        authenticated_p1.dataset_sha256,
        authenticated_p1.embedded_dataset_sha256,
        authenticated_p1.geometry_sha256,
        authenticated_p1.production_asset_version,
        authenticated_p1.topology_edge_count,
        authenticated_p1.included_ids_sha256,
    )
    return (str(root), _authority_key(authority_root), tuple(raw_hashes), p1_identity)


def _install_process_semantic_authority_cache() -> None:
    """Install exact-byte authenticated semantic caches once per process."""

    from . import earth3_bootstrap as p2
    from . import earth3_campaign as p1

    current_p1 = p1.load_earth3_authority
    current_p2 = p2.load_earth3_bootstrap
    if bool(getattr(current_p1, "_goc_authenticated_semantic_cache", False)) and bool(
        getattr(current_p2, "_goc_authenticated_semantic_cache", False)
    ):
        return

    original_p1 = current_p1
    original_p2 = current_p2

    def authenticated_cached_p1(authority_root=None):
        key = _profiled_authority_call(
            "p1_identity_capture",
            lambda: _capture_p1_identity(authority_root),
        )
        cached = _cache_get(_P1_SEMANTIC_CACHE, key)
        if cached is not None:
            _increment_stat("p1_semantic_hits")
            return cached
        value = original_p1(authority_root)
        _increment_stat("p1_semantic_loads")
        _cache_put(_P1_SEMANTIC_CACHE, key, value)
        return value

    def authenticated_cached_p2(*, authority_root=None):
        authenticated_p1 = p1.load_earth3_authority(authority_root)
        key = _profiled_authority_call(
            "p2_identity_capture",
            lambda: _capture_p2_identity(
                authority_root,
                authenticated_p1=authenticated_p1,
            ),
        )
        cached = _cache_get(_P2_SEMANTIC_CACHE, key)
        if cached is not None:
            _increment_stat("p2_semantic_hits")
            return cached
        value = original_p2(authority_root=authority_root)
        _increment_stat("p2_semantic_loads")
        _cache_put(_P2_SEMANTIC_CACHE, key, value)
        return value

    authenticated_cached_p1._goc_authenticated_semantic_cache = True  # type: ignore[attr-defined]
    authenticated_cached_p2._goc_authenticated_semantic_cache = True  # type: ignore[attr-defined]
    p1.load_earth3_authority = authenticated_cached_p1
    p2.load_earth3_bootstrap = authenticated_cached_p2


def _run_with_command_scoped_p2_auth(
    action: Callable[[], Any],
) -> tuple[Any, dict[str, int]]:
    """Run ``action`` with one exactly-authenticated P2 snapshot per root."""

    from . import earth3_bootstrap

    original_loader = earth3_bootstrap.load_earth3_bootstrap
    cache: dict[str, Any] = {}
    stats = {"loads": 0, "hits": 0}

    def scoped_loader(*, authority_root=None):
        key = _authority_key(authority_root)
        cached = cache.get(key)
        if cached is not None:
            stats["hits"] += 1
            return copy.deepcopy(cached)

        bundle = original_loader(authority_root=authority_root)
        stats["loads"] += 1
        cache[key] = copy.deepcopy(bundle)
        return bundle

    earth3_bootstrap.load_earth3_bootstrap = scoped_loader
    try:
        result = action()
    finally:
        earth3_bootstrap.load_earth3_bootstrap = original_loader
        cache.clear()
    return result, stats


def _profiled_phase(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def profiled(*args, **kwargs):
        events = _AI_PROFILE_EVENTS.get()
        if events is None:
            return function(*args, **kwargs)
        faction = ""
        if len(args) > 1:
            faction = str(getattr(args[1], "value", args[1]))
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            events.append(
                {
                    "phase": name,
                    "faction": faction,
                    "ms": round((time.perf_counter() - started) * 1000.0, 3),
                }
            )

    profiled._goc_issue212_ai_profiled = True  # type: ignore[attr-defined]
    return profiled


def _install_ai_phase_profiler() -> None:
    """Instrument existing AI subphases without changing planning semantics."""

    from . import operational_ai, strategic_ai

    targets = (
        (strategic_ai, "run_ai_economy", "economy"),
        (strategic_ai, "run_ai_construction", "construction"),
        (operational_ai, "build_operational_planning_view", "planning_view"),
        (operational_ai, "plan_operational_intents", "plan_intents"),
        (
            operational_ai,
            "validate_and_commit_operational_intents",
            "commit_intents",
        ),
    )
    for module, attribute, label in targets:
        current = getattr(module, attribute)
        if bool(getattr(current, "_goc_issue212_ai_profiled", False)):
            continue
        setattr(module, attribute, _profiled_phase(label, current))


def _profiled_round_phase(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def profiled(*args, **kwargs):
        events = _ROUND_ADVANCE_EVENTS.get()
        if events is None or not _ROUND_ADVANCE_ACTIVE.get():
            return function(*args, **kwargs)
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            events.append(
                {
                    "phase": name,
                    "ms": round((time.perf_counter() - started) * 1000.0, 3),
                }
            )

    profiled._goc_issue212_round_profiled = True  # type: ignore[attr-defined]
    return profiled


def _profiled_campaign_end_turn(function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def profiled(engine, *args, **kwargs):
        events = _ROUND_ADVANCE_EVENTS.get()
        if events is None:
            return function(engine, *args, **kwargs)
        before_turn = int(engine.state.turn_number)
        started = time.perf_counter()
        token = _ROUND_ADVANCE_ACTIVE.set(True)
        try:
            return function(engine, *args, **kwargs)
        finally:
            _ROUND_ADVANCE_ACTIVE.reset(token)
            events.append(
                {
                    "phase": "end_turn_total",
                    "round_rollover": int(engine.state.turn_number) != before_turn,
                    "ms": round((time.perf_counter() - started) * 1000.0, 3),
                }
            )

    profiled._goc_issue212_round_profiled = True  # type: ignore[attr-defined]
    return profiled


def _install_round_advance_profiler() -> None:
    """Time exact CampaignEngine rollover authorities without changing them."""

    from . import economy, operational_movement, operational_supply, strategic, supply
    from .campaign import CampaignEngine

    current_end_turn = CampaignEngine.end_turn
    if not bool(getattr(current_end_turn, "_goc_issue212_round_profiled", False)):
        CampaignEngine.end_turn = _profiled_campaign_end_turn(current_end_turn)

    targets = (
        (operational_movement, "resolve_strategic_turn_movement", "movement_resolution"),
        (operational_supply, "refresh_operational_supply", "operational_supply_refresh"),
        (economy, "settle_round_economy", "round_economy_settlement"),
        (supply, "refresh_all_supply", "global_supply_refresh"),
        (strategic, "evaluate_campaign_outcome", "campaign_outcome_evaluation"),
    )
    for module, attribute, label in targets:
        current = getattr(module, attribute)
        if bool(getattr(current, "_goc_issue212_round_profiled", False)):
            continue
        setattr(module, attribute, _profiled_round_phase(label, current))


def _turn_cycle_perf(report: dict[str, Any]) -> dict[str, Any] | None:
    """Extract existing End Turn subphase telemetry without changing command data."""

    results = report.get("results")
    if not isinstance(results, list):
        return None
    for result in results:
        if not isinstance(result, dict) or str(result.get("op", "")) != "end_player_round":
            continue
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        perf = data.get("perf_turn_cycle")
        if isinstance(perf, dict):
            return copy.deepcopy(perf)
    return None


def install_command_scoped_p2_auth() -> None:
    """Install authority reuse and wrap the measured command seam exactly once."""

    from . import command_cycle_perf as perf
    from . import frontend_commands as commands

    _install_process_semantic_authority_cache()
    _install_ai_phase_profiler()
    _install_round_advance_profiler()

    current = perf.measured_apply_frontend_commands
    if bool(getattr(current, "_goc_issue_207_p2_auth_cache", False)):
        return

    def measured_with_p2_auth_cache(*args, **kwargs):
        process_before = _process_stats_snapshot()
        events: list[dict[str, Any]] = []
        round_events: list[dict[str, Any]] = []
        authority_events: list[dict[str, Any]] = []
        token = _AI_PROFILE_EVENTS.set(events)
        round_token = _ROUND_ADVANCE_EVENTS.set(round_events)
        auth_token = _AUTH_PROFILE_EVENTS.set(authority_events)
        try:
            report, stats = _run_with_command_scoped_p2_auth(
                lambda: current(*args, **kwargs)
            )
        finally:
            _AUTH_PROFILE_EVENTS.reset(auth_token)
            _ROUND_ADVANCE_EVENTS.reset(round_token)
            _AI_PROFILE_EVENTS.reset(token)
        process_after = _process_stats_snapshot()
        if isinstance(report, dict):
            timings = report.get("timings")
            if isinstance(timings, dict):
                timings["p2_auth_loads"] = int(stats["loads"])
                timings["p2_auth_cache_hits"] = int(stats["hits"])
                for name in _PROCESS_STATS:
                    timings[name] = int(process_after[name] - process_before[name])
                turn_cycle = _turn_cycle_perf(report)
                if turn_cycle is not None:
                    timings["turn_cycle"] = turn_cycle
                if events:
                    timings["ai_phase_events"] = events
                if round_events:
                    timings["round_advance_events"] = round_events
                if authority_events:
                    timings["authority_phase_events"] = authority_events
        return report

    measured_with_p2_auth_cache._goc_issue_207_measured = True  # type: ignore[attr-defined]
    measured_with_p2_auth_cache._goc_issue_207_p2_auth_cache = True  # type: ignore[attr-defined]
    perf.measured_apply_frontend_commands = measured_with_p2_auth_cache
    commands.apply_frontend_commands = measured_with_p2_auth_cache
