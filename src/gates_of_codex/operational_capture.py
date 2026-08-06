from __future__ import annotations

from typing import Any

from .diplomacy import are_allied
from .models import CampaignState, Faction, StrategicFormation
from .operational_contact import (
    enemy_formations_at_node,
    formation_at_node_id,
    formations_at_node,
    friendly_formations_at_node,
)
from .operational_position import load_operational_graph_for_state
from .operational_schema import COST_MILLI_UNITY, stable_node_id, stable_site_id

SITE_CONTROL_KEY = "operational_site_control"
DEFAULT_CAPTURE_HOLD_TICKS = 2


def get_site_control_state(state: CampaignState) -> dict[str, dict[str, Any]]:
    raw = state.map_metadata.get(SITE_CONTROL_KEY)
    if not isinstance(raw, dict):
        return {}
    return {
        str(site_id): dict(value)
        for site_id, value in raw.items()
        if isinstance(value, dict)
    }


def set_site_control_state(state: CampaignState, control: dict[str, dict[str, Any]]) -> None:
    state.map_metadata[SITE_CONTROL_KEY] = {
        str(site_id): dict(value)
        for site_id, value in sorted(control.items())
    }


def capture_hold_ticks(state: CampaignState) -> int:
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return DEFAULT_CAPTURE_HOLD_TICKS
    rules = graph.get("rules") or {}
    try:
        return max(1, int(rules.get("capture_hold_ticks", DEFAULT_CAPTURE_HOLD_TICKS)))
    except (TypeError, ValueError):
        return DEFAULT_CAPTURE_HOLD_TICKS


def list_control_sites(state: CampaignState) -> list[dict[str, Any]]:
    """Authored graph sites, or synthetic one-per-province anchor sites when enabled."""
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return []
    sites = [dict(site) for site in graph.get("sites") or [] if isinstance(site, dict)]
    if sites:
        return sorted(sites, key=lambda item: str(item.get("site_id", "")))
    if not (
        bool(state.map_metadata.get("operational_maneuver_enabled"))
        or str(state.map_metadata.get("operational_graph", "")).strip()
    ):
        return []
    # Synthetic control sites at province anchors (no invented settlements beyond anchors).
    synthetic: list[dict[str, Any]] = []
    for province_id in sorted(state.provinces):
        node_id = stable_node_id(province_id, "anchor")
        site_id = stable_site_id(province_id, "control", "anchor")
        synthetic.append(
            {
                "site_id": site_id,
                "display_name": f"{province_id} control",
                "kind": "objective",
                "province_id": province_id,
                "pixel": _node_pixel(graph, node_id) or [0, 0],
                "route_node_id": node_id,
                "control_weight_milli": COST_MILLI_UNITY,
                "capture_threshold_milli": COST_MILLI_UNITY,
                "owner_faction": None,
                "metadata": {"synthetic_anchor_control_site": True},
            }
        )
    return synthetic


def advance_site_capture(state: CampaignState) -> dict[str, Any]:
    """Advance control-site capture one operational tick.

    Rules (S5):
    - Capture only while a formation is physically at the site node.
    - Uncontested: no enemy at the node.
    - First formation that begins an uncontested capture is the claimant;
      allies may protect but do not steal the claim.
    - Enemy presence or claimant leaving resets progress.
    - After capture_hold_ticks uncontested ticks, site controller flips to claimant.
    - Province ownership updates only from held site control weight, never from
      mere province entry.
    """
    sites = list_control_sites(state)
    if not sites:
        return {"advanced": False, "reason": "no_sites", "flipped_sites": [], "flipped_provinces": []}

    hold = capture_hold_ticks(state)
    control = get_site_control_state(state)
    flipped_sites: list[str] = []

    for site in sites:
        site_id = str(site.get("site_id") or "")
        node_id = str(site.get("route_node_id") or "")
        province_id = str(site.get("province_id") or "")
        if not site_id or not node_id:
            continue
        row = control.setdefault(
            site_id,
            {
                "controller_faction": _initial_controller(state, site),
                "claimant_faction": None,
                "claimant_formation_id": None,
                "progress_ticks": 0,
                "required_ticks": hold,
                "province_id": province_id,
                "route_node_id": node_id,
                "control_weight_milli": int(site.get("control_weight_milli") or COST_MILLI_UNITY),
            },
        )
        row["required_ticks"] = hold
        row["province_id"] = province_id
        row["route_node_id"] = node_id
        row["control_weight_milli"] = int(site.get("control_weight_milli") or COST_MILLI_UNITY)

        present = formations_at_node(state, node_id)
        if not present:
            _reset_claim(row)
            continue

        # Contested if any hostile pair present.
        if _node_has_hostile_pair(state, present):
            _reset_claim(row)
            continue

        # Single coalition present.
        lead = _lead_formation(present)
        if lead is None:
            _reset_claim(row)
            continue
        controller = row.get("controller_faction")
        if controller and (
            lead.faction.value == controller
            or are_allied(state, lead.faction, Faction(controller))
        ):
            # Friendly/allied already control — clear opposing claim progress.
            _reset_claim(row)
            continue

        # Hostile or neutral site: continue or start claim.
        claimant_id = row.get("claimant_formation_id")
        claimant_faction = row.get("claimant_faction")
        if claimant_id and claimant_faction:
            claimant_force = state.strategic_formations.get(str(claimant_id))
            if (
                claimant_force is None
                or formation_at_node_id(claimant_force) != node_id
                or claimant_force.faction.value != str(claimant_faction)
            ):
                # Original claimant left or invalid — if another friendly remains,
                # first-present (stable sort) may start a new claim next tick after reset.
                _reset_claim(row)
                # Fall through to start new claim this tick if friendlies still present.
                claimant_id = None

        if not claimant_id:
            # First formation in stable order begins the claim (allies protect only).
            row["claimant_formation_id"] = lead.strategic_formation_id
            row["claimant_faction"] = lead.faction.value
            row["progress_ticks"] = 1
        else:
            row["progress_ticks"] = int(row.get("progress_ticks") or 0) + 1

        if int(row["progress_ticks"]) >= hold:
            row["controller_faction"] = row["claimant_faction"]
            row["progress_ticks"] = hold
            row["claimant_formation_id"] = None
            row["claimant_faction"] = None
            flipped_sites.append(site_id)

    set_site_control_state(state, control)
    flipped_provinces = _apply_province_ownership_from_sites(state, sites, control)
    return {
        "advanced": True,
        "flipped_sites": flipped_sites,
        "flipped_provinces": flipped_provinces,
        "site_count": len(sites),
    }


def site_control_snapshot(state: CampaignState) -> list[dict[str, Any]]:
    """Frontend-facing site control rows."""
    sites = {str(site.get("site_id")): site for site in list_control_sites(state)}
    control = get_site_control_state(state)
    rows: list[dict[str, Any]] = []
    for site_id in sorted(set(sites) | set(control)):
        site = sites.get(site_id) or {}
        row = control.get(site_id) or {}
        rows.append(
            {
                "site_id": site_id,
                "display_name": site.get("display_name") or site_id,
                "province_id": row.get("province_id") or site.get("province_id") or "",
                "route_node_id": row.get("route_node_id") or site.get("route_node_id") or "",
                "control_weight_milli": int(
                    row.get("control_weight_milli")
                    or site.get("control_weight_milli")
                    or COST_MILLI_UNITY
                ),
                "controller_faction": row.get("controller_faction"),
                "claimant_faction": row.get("claimant_faction"),
                "claimant_formation_id": row.get("claimant_formation_id"),
                "progress_ticks": int(row.get("progress_ticks") or 0),
                "required_ticks": int(row.get("required_ticks") or capture_hold_ticks(state)),
                "pixel": list(site.get("pixel") or [0, 0]),
            }
        )
    return rows


def _initial_controller(state: CampaignState, site: dict[str, Any]) -> str | None:
    owner = site.get("owner_faction")
    if owner:
        return str(owner)
    province_id = str(site.get("province_id") or "")
    province = state.provinces.get(province_id)
    if province is None or province.owner == Faction.NEUTRAL:
        return None
    return province.owner.value


def _reset_claim(row: dict[str, Any]) -> None:
    row["claimant_faction"] = None
    row["claimant_formation_id"] = None
    row["progress_ticks"] = 0


def _node_has_hostile_pair(state: CampaignState, present: list[StrategicFormation]) -> bool:
    for index, left in enumerate(present):
        for right in present[index + 1 :]:
            if left.faction == right.faction:
                continue
            if are_allied(state, left.faction, right.faction):
                continue
            return True
    return False


def _lead_formation(present: list[StrategicFormation]) -> StrategicFormation | None:
    if not present:
        return None
    return sorted(present, key=lambda value: value.strategic_formation_id)[0]


def _apply_province_ownership_from_sites(
    state: CampaignState,
    sites: list[dict[str, Any]],
    control: dict[str, dict[str, Any]],
) -> list[str]:
    """Flip province owner when one faction holds enough site control weight."""
    by_province: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for site in sites:
        site_id = str(site.get("site_id") or "")
        province_id = str(site.get("province_id") or "")
        if not site_id or not province_id or province_id not in state.provinces:
            continue
        row = control.get(site_id) or {}
        by_province.setdefault(province_id, []).append((site, row))

    flipped: list[str] = []
    for province_id, items in sorted(by_province.items()):
        total_weight = 0
        held: dict[str, int] = {}
        for site, row in items:
            weight = int(row.get("control_weight_milli") or site.get("control_weight_milli") or COST_MILLI_UNITY)
            total_weight += weight
            controller = row.get("controller_faction")
            if controller:
                held[str(controller)] = held.get(str(controller), 0) + weight
        if total_weight <= 0 or not held:
            continue
        # Threshold: default majority of total weight (capture_threshold on sites averaged).
        threshold = max(1, (total_weight + 1) // 2)
        # Prefer explicit per-site thresholds when single-site province.
        if len(items) == 1:
            site, _row = items[0]
            threshold = int(site.get("capture_threshold_milli") or COST_MILLI_UNITY)
            threshold = min(threshold, total_weight)
        winner = None
        best = -1
        for faction_id, weight in sorted(held.items()):
            if weight >= threshold and weight > best:
                winner = faction_id
                best = weight
        if winner is None:
            continue
        province = state.provinces[province_id]
        if province.owner.value == winner:
            continue
        province.owner = Faction(winner)
        from .strategic import sync_province_infrastructure_owner

        sync_province_infrastructure_owner(province)
        flipped.append(province_id)
    if flipped:
        from .strategic import evaluate_campaign_outcome

        evaluate_campaign_outcome(state)
    return flipped


def _node_pixel(graph: dict[str, Any], node_id: str) -> list[int] | None:
    for node in graph.get("nodes") or []:
        if str(node.get("node_id")) == node_id:
            pixel = node.get("pixel") or [0, 0]
            return [int(pixel[0]), int(pixel[1])]
    return None
