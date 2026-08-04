from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from .models import CampaignState


_GENERIC_NAME = re.compile(r"(?i)^province([_\s-]?\d+)?$")


@lru_cache(maxsize=1)
def load_marker_layout() -> dict:
    package = files("gates_of_codex")
    raw = package.joinpath("data/goe_marker_layout.json").read_text(encoding="utf-8")
    return json.loads(raw)


def is_human_readable_name(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return _GENERIC_NAME.fullmatch(text) is None


def source_display_name(*candidates: object) -> str | None:
    """Return the first explicit non-generic name; never invent labels."""

    for candidate in candidates:
        text = str(candidate or "").strip()
        if is_human_readable_name(text):
            return text
    return None


def province_name_coverage(state: CampaignState) -> dict[str, int | float]:
    total = len(state.provinces)
    named = sum(1 for province in state.provinces.values() if is_human_readable_name(province.display_name))
    generic = total - named
    return {
        "total": total,
        "human_readable": named,
        "generic": generic,
        "human_readable_pct": round((100.0 * named / total), 1) if total else 0.0,
    }


def apply_source_display_names(state: CampaignState) -> dict[str, int | float]:
    """Copy extracted GoE marker/source names onto campaign provinces via alignment."""

    from .goe_strategic_map import build_goe_source_nodes, resolve_goe_graph_mapping

    alignment = resolve_goe_graph_mapping()
    source = build_goe_source_nodes()
    applied = 0
    kept_generic = 0
    for province_id, province in state.provinces.items():
        # Theatre/manifest locks (e.g. Donetsk/Luhansk modern names) win.
        if bool(province.metadata.get("display_name_locked")):
            applied += 1
            continue
        source_key = alignment.graph_to_source.get(province_id)
        if not source_key:
            if not is_human_readable_name(province.display_name):
                kept_generic += 1
            continue
        marker = source[source_key]
        label = source_display_name(
            marker.get("display_name"),
            marker.get("source_province_id"),
            marker.get("id"),
            source_key,
        )
        if label is None:
            kept_generic += 1
            province.metadata["name_source"] = "generic"
            continue
        if province.display_name != label:
            province.metadata["previous_display_name"] = province.display_name
        province.display_name = label
        province.metadata["name_source"] = "goe_marker"
        province.metadata["source_node_key"] = source_key
        applied += 1

    coverage = province_name_coverage(state)
    state.map_metadata["province_names"] = {
        **coverage,
        "applied_from_source": applied,
        "kept_generic": kept_generic,
        "mapping_methods": dict(sorted(
            {
                method: sum(1 for value in alignment.methods.values() if value == method)
                for method in set(alignment.methods.values())
            }.items()
        )),
    }
    return state.map_metadata["province_names"]


def apply_marker_layout(state: CampaignState) -> int:
    """Remap province x/y onto observed GoE marker positions where matchable.

    GoE builds maps as MapChart HOI4 provinces with unique RGB id-colors and
    marker anchors. We reuse observed marker anchors (not their art texture).
    """

    layout = load_marker_layout()
    by_id = {row["id"]: row for row in layout["provinces"]}
    by_name = {
        str(row.get("display_name", "")).strip().lower(): row
        for row in layout["provinces"]
        if str(row.get("display_name", "")).strip()
    }

    matched: dict[str, str] = {}
    for province_id in state.provinces:
        if province_id in by_id:
            matched[province_id] = province_id
        elif province_id.strip().lower() in by_name:
            matched[province_id] = by_name[province_id.strip().lower()]["id"]

    # Grow matches across unique neighbor pairs.
    changed = True
    while changed:
        changed = False
        for our_id, their_id in list(matched.items()):
            our = state.provinces[our_id]
            their = by_id[their_id]
            their_neighbors = [value for value in their.get("neighbors", []) if value in by_id]
            unmatched_ours = [nid for nid in our.neighbors if nid not in matched and nid in state.provinces]
            unmatched_theirs = [nid for nid in their_neighbors if nid not in matched.values()]
            if len(unmatched_ours) == 1 and len(unmatched_theirs) == 1:
                matched[unmatched_ours[0]] = unmatched_theirs[0]
                changed = True

    # Screen space: GoE Y increases north in world units; flip into top-left canvas space.
    bounds = layout.get("bounds", {})
    min_y = float(bounds.get("min_y", 0.0))
    max_y = float(bounds.get("max_y", 1.0))
    applied = 0
    placed: set[str] = set()
    for our_id, their_id in matched.items():
        row = by_id[their_id]
        province = state.provinces[our_id]
        province.x = float(row["x"])
        province.y = (min_y + max_y) - float(row["y"])
        color = row.get("id_color") or {}
        province.metadata["id_color"] = {
            "r": int(color.get("r", 0)),
            "g": int(color.get("g", 0)),
            "b": int(color.get("b", 0)),
            "a": int(color.get("a", 255)),
        }
        province.metadata["layout_source"] = "goe_marker_layout"
        if our_id != their_id:
            province.metadata["layout_matched_as"] = their_id
        placed.add(our_id)
        applied += 1

    # Pull unmatched nodes into marker space via neighbor averages so bounds stay geographic.
    for _ in range(24):
        progressed = False
        for province_id, province in state.provinces.items():
            if province_id in placed:
                continue
            anchors = [
                state.provinces[neighbor_id]
                for neighbor_id in province.neighbors
                if neighbor_id in placed
            ]
            if not anchors:
                continue
            province.x = sum(item.x for item in anchors) / len(anchors)
            province.y = sum(item.y for item in anchors) / len(anchors)
            province.metadata["layout_source"] = "neighbor_average"
            placed.add(province_id)
            progressed = True
        if not progressed:
            break

    if placed:
        xs = [state.provinces[pid].x for pid in placed]
        ys = [state.provinces[pid].y for pid in placed]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        for province_id, province in state.provinces.items():
            if province_id in placed:
                continue
            province.x = cx
            province.y = cy
            province.metadata["layout_source"] = "fallback_center"
            placed.add(province_id)

    state.map_metadata["marker_layout"] = {
        "source": layout.get("source", "goe_marker_layout"),
        "method": layout.get("method", "mapchart_hoi4_color_id"),
        "matched": applied,
        "total": len(state.provinces),
    }
    apply_source_display_names(state)
    return applied


def write_marker_layout(path: str | Path, payload: dict) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return destination
