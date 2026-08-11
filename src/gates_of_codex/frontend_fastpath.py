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
lookups used by ``construction_options``: strategic initialization becomes a
no-op after the frontend's real initialization, and selected-faction supply
reachability returns one precomputed set. The original helpers are restored in a
``finally`` block. The frontend's own supply/status calculations still use the
unmodified supply module functions, so presentation semantics do not change.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

from . import frontend as _frontend
from . import strategic as _strategic
from .models import CampaignState, Faction
from .supply import reachable_supply_provinces as _reachable_supply_provinces


_ORIGINAL_STRATEGIC_ENSURE = _strategic.ensure_strategic_layer
_ORIGINAL_STRATEGIC_REACHABLE = _strategic.reachable_supply_provinces


def build_frontend_snapshot_fast(
    state: CampaignState,
    *,
    campaign_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the normal snapshot while deduplicating per-province setup work."""

    selected = state.selected_faction
    selected_reachable = _reachable_supply_provinces(state, selected)
    previous_ensure = _strategic.ensure_strategic_layer
    previous_reachable = _strategic.reachable_supply_provinces

    def _already_initialized(_state: CampaignState) -> None:
        # ``frontend.build_frontend_snapshot`` calls its imported original
        # ``ensure_strategic_layer`` once before any construction projection.
        # Calls reached through strategic helper globals after that are repeats.
        return None

    def _snapshot_reachable(candidate: CampaignState, faction: Faction) -> set[str]:
        if faction == selected:
            return set(selected_reachable)
        return _ORIGINAL_STRATEGIC_REACHABLE(candidate, faction)

    _strategic.ensure_strategic_layer = _already_initialized
    _strategic.reachable_supply_provinces = _snapshot_reachable
    try:
        return _frontend.build_frontend_snapshot(
            state,
            campaign_path=campaign_path,
            snapshot_path=snapshot_path,
        )
    finally:
        _strategic.ensure_strategic_layer = previous_ensure
        _strategic.reachable_supply_provinces = previous_reachable


def write_frontend_snapshot_fast(
    state: CampaignState,
    path: str | Path,
    *,
    campaign_path: str | Path | None = None,
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
