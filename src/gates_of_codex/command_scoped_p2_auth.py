from __future__ import annotations

"""Command-scoped Earth3 P2 authority reuse for the #207 hot path.

A production Earth3 validation currently reaches ``load_earth3_bootstrap`` more
than once while validating the same atomic command. Every top-level command must
still authenticate the immutable P2 bundle fail-closed, but repeating the same
fixed-file capture inside that command adds no new authority. This layer keeps
one detached authenticated bundle per authority root for the duration of exactly
one measured frontend command, then restores the loader and drops the cache.

The cache is deliberately not process- or daemon-scoped. The next command reads
and authenticates the fixed P2 files again, so external changes are observed at
the same command boundary used by the existing command-scoped P3 graph cache.
"""

import copy
from pathlib import Path
from typing import Any, Callable


def _authority_key(authority_root: str | Path | None) -> str:
    if authority_root is None:
        return "<default>"
    return str(Path(authority_root).expanduser().resolve(strict=False))


def _run_with_command_scoped_p2_auth(
    action: Callable[[], Any],
) -> tuple[Any, dict[str, int]]:
    """Run ``action`` with one authenticated P2 bundle snapshot per root."""

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
        # Never let a caller mutate the reusable instance. The first caller keeps
        # the original authenticated bundle; later callers receive detached copies
        # of this pristine snapshot.
        cache[key] = copy.deepcopy(bundle)
        return bundle

    earth3_bootstrap.load_earth3_bootstrap = scoped_loader
    try:
        result = action()
    finally:
        earth3_bootstrap.load_earth3_bootstrap = original_loader
        cache.clear()
    return result, stats


def install_command_scoped_p2_auth() -> None:
    """Wrap the measured frontend command seam once for source and frozen paths."""

    from . import command_cycle_perf as perf
    from . import frontend_commands as commands

    current = perf.measured_apply_frontend_commands
    if bool(getattr(current, "_goc_issue_207_p2_auth_cache", False)):
        return

    def measured_with_p2_auth_cache(*args, **kwargs):
        report, stats = _run_with_command_scoped_p2_auth(
            lambda: current(*args, **kwargs)
        )
        if isinstance(report, dict):
            timings = report.get("timings")
            if isinstance(timings, dict):
                # Diagnostic-only counters. Keep the stable public timing key
                # contract unchanged, matching the P3 auth counters.
                timings["p2_auth_loads"] = int(stats["loads"])
                timings["p2_auth_cache_hits"] = int(stats["hits"])
        return report

    # Preserve the measured marker so repeated _install_fast_paths() calls do not
    # replace this wrapper with the underlying measured function.
    measured_with_p2_auth_cache._goc_issue_207_measured = True  # type: ignore[attr-defined]
    measured_with_p2_auth_cache._goc_issue_207_p2_auth_cache = True  # type: ignore[attr-defined]
    perf.measured_apply_frontend_commands = measured_with_p2_auth_cache
    commands.apply_frontend_commands = measured_with_p2_auth_cache
