from __future__ import annotations

"""Scoped acceleration for the file-backed strategic frontend (#207).

The ordinary frontend projection is deliberately authoritative and remains the
single implementation of snapshot semantics. This module only removes repeated
work around that projection:

* ``build_frontend_snapshot`` already initializes the strategic layer once, but
  its per-province ``construction_options`` call re-enters that initialization
  for every province and re-runs the selected faction's legacy/admin supply BFS.
  Earth3 has 3,514 provinces, so that turns one snapshot into thousands of
  redundant traversals.
* the published snapshot was pretty-printed even though Godot consumes it as
  machine JSON, inflating the file and parse/write work.

During one snapshot build we temporarily replace only the two strategic helper
lookups used by ``construction_options``. Strategic initialization becomes a
no-op after the frontend's real initialization. The first construction
reachability lookup runs the original BFS against that already-initialized
projection and caches the exact set for the rest of the province loop. Original
helpers are restored in a ``finally`` block. The frontend's own supply/status
calculations still use the unmodified supply module functions.
"""

import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from . import frontend as _frontend
from . import strategic as _strategic
from .models import CampaignState, Faction


_ORIGINAL_STRATEGIC_REACHABLE = _strategic.reachable_supply_provinces


def build_frontend_snapshot_fast(
    state: CampaignState,
    *,
    campaign_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the normal snapshot while deduplicating per-province setup work."""

    selected = state.selected_faction
    previous_ensure = _strategic.ensure_strategic_layer
    previous_reachable = _strategic.reachable_supply_provinces
    selected_reachable: set[str] | None = None
    projection_identity: int | None = None

    def _already_initialized(_state: CampaignState) -> None:
        # ``frontend.build_frontend_snapshot`` calls its own imported original
        # ``ensure_strategic_layer`` once on the deep-copied projection before
        # any construction projection. Calls reached through strategic helper
        # globals after that point are repeats.
        return None

    def _snapshot_reachable(candidate: CampaignState, faction: Faction) -> set[str]:
        nonlocal selected_reachable, projection_identity
        if faction != selected:
            return _ORIGINAL_STRATEGIC_REACHABLE(candidate, faction)
        candidate_identity = id(candidate)
        if selected_reachable is None or projection_identity != candidate_identity:
            selected_reachable = _ORIGINAL_STRATEGIC_REACHABLE(candidate, faction)
            projection_identity = candidate_identity
        return set(selected_reachable)

    _strategic.ensure_strategic_layer = _already_initialized
    _strategic.reachable_supply_provinces = _snapshot_reachable
    try:
        return _frontend.build_frontend_snapshot(
            state,
            campaign_path=campaign_path,
            snapshot_path=snapshot_path,
            environ=environ,
        )
    finally:
        _strategic.ensure_strategic_layer = previous_ensure
        _strategic.reachable_supply_provinces = previous_reachable


def write_frontend_snapshot_fast(
    state: CampaignState,
    path: str | Path,
    *,
    campaign_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Atomically publish compact JSON for the unchanged frontend schema."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            build_frontend_snapshot_fast(
                state,
                campaign_path=campaign_path,
                snapshot_path=destination,
                environ=environ,
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )
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


def install_frontend_fast_path() -> None:
    """Install the fast writer once, preserving the public frontend API."""

    current = _frontend.write_frontend_snapshot
    if bool(getattr(current, "_goc_issue_207_fastpath", False)):
        return
    write_frontend_snapshot_fast._goc_issue_207_fastpath = True  # type: ignore[attr-defined]
    _frontend.write_frontend_snapshot = write_frontend_snapshot_fast
