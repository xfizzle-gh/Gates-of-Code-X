from __future__ import annotations

from typing import Any

from .diplomacy import are_allied
from .models import CampaignState, Faction, StrategicFormation
from .operational_contact import formation_at_node_id, formations_at_node
from .operational_position import load_operational_graph_for_state
from .operational_schema import (
    COST_MILLI_UNITY,
    require_strict_int,
    stable_node_id,
    stable_site_id,
)

SITE_CONTROL_KEY = "operational_site_control"
DEFAULT_CAPTURE_HOLD_TICKS = 2


def get_site_control_state(
    state: CampaignState,
    *,
    strict: bool = False,
) -> dict[str, dict[str, Any]]:
    """Return site-control rows.

    When ``strict`` is True (graph available / ensure path), malformed roots or
    non-object rows raise. When False (graph unavailable), return a best-effort
    view without mutating or erasing data.
    """
    raw = state.map_metadata.get(SITE_CONTROL_KEY)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise ValueError(
                f"{SITE_CONTROL_KEY} must be an object, got {type(raw).__name__}"
            )
        return {}
    out: dict[str, dict[str, Any]] = {}
    for site_id, value in raw.items():
        if not isinstance(value, dict):
            if strict:
                raise ValueError(
                    f"{SITE_CONTROL_KEY}[{site_id!r}] must be an object, "
                    f"got {type(value).__name__}"
                )
            continue
        out[str(site_id)] = dict(value)
    return out


def set_site_control_state(state: CampaignState, control: dict[str, dict[str, Any]]) -> None:
    state.map_metadata[SITE_CONTROL_KEY] = {
        str(site_id): dict(value)
        for site_id, value in sorted(control.items())
    }


def capture_hold_ticks(state: CampaignState, *, strict: bool = False) -> int:
    """Return capture hold ticks from graph rules.

    When the graph is available (or ``strict``), malformed values raise.
    When the graph cannot be resolved, fall back to the default without error.
    """
    graph = load_operational_graph_for_state(state)
    if graph is None:
        if strict:
            raise ValueError("capture_hold_ticks requires a resolvable operational graph")
        return DEFAULT_CAPTURE_HOLD_TICKS
    rules = graph.get("rules") or {}
    raw = rules.get("capture_hold_ticks", DEFAULT_CAPTURE_HOLD_TICKS)
    return require_strict_int(raw, name="capture_hold_ticks", minimum=1)


def list_control_sites(state: CampaignState) -> list[dict[str, Any]]:
    """Authored graph sites plus legal synthetic anchor control sites.

    Synthetic capture authority only exists where the operational graph actually
    has an anchor. Earth3 P2/P3 further restricts synthetic sites to the frozen P2
    scenario footprint, so approved neutral corridor transit never promotes
    outside provinces into territorial gameplay authority.
    """
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return []
    if not (
        bool(state.map_metadata.get("operational_maneuver_enabled"))
        or str(state.map_metadata.get("operational_graph", "")).strip()
        or graph.get("sites")
    ):
        return []

    authored = [dict(site) for site in graph.get("sites") or [] if isinstance(site, dict)]
    covered_provinces = {
        str(site.get("province_id") or "")
        for site in authored
        if str(site.get("province_id") or "")
    }
    graph_node_provinces = {
        str(node.get("province_id") or "")
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and str(node.get("province_id") or "")
    }
    synthetic_provinces = set(state.provinces) & graph_node_provinces

    from .earth3_bootstrap import earth3_p2_footprint, is_earth3_p2_campaign

    if is_earth3_p2_campaign(state):
        synthetic_provinces &= set(earth3_p2_footprint(state))

    sites = list(authored)
    # Per-province synthetic anchors only where an authored graph node exists,
    # and on Earth3 only inside the immutable P2 scenario footprint.
    for province_id in sorted(synthetic_provinces):
        if province_id in covered_provinces:
            continue
        node_id = stable_node_id(province_id, "anchor")
        site_id = stable_site_id(province_id, "control", "anchor")
        sites.append(
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
    return sorted(sites, key=lambda item: str(item.get("site_id", "")))


def ensure_site_control_state(state: CampaignState) -> dict[str, Any]:
    """Idempotent initialize/validate site control rows.

    - When graph unavailable: leave existing capture data completely unchanged.
    - When graph available: ensure every control site has a validated row;
      initialize controller from authored site owner or province owner.
    - Reject malformed numeric fields via strict ints (raise on corrupt saves).
    """
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return {"ensured": False, "reason": "no_graph", "site_count": 0}

    sites = list_control_sites(state)
    if not sites:
        return {"ensured": True, "reason": "no_sites", "site_count": 0}

    # Graph is available: reject malformed capture config instead of erasing it.
    hold = capture_hold_ticks(state, strict=True)
    existing = get_site_control_state(state, strict=True)
    authored_node_ids = {
        str(node.get("node_id"))
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("node_id")
    }
    control: dict[str, dict[str, Any]] = {}
    for site in sites:
        site_id = str(site.get("site_id") or "")
        if not site_id:
            continue
        node_id = str(site.get("route_node_id") or "")
        province_id = str(site.get("province_id") or "")
        weight = _strict_positive_milli(
            site.get("control_weight_milli", COST_MILLI_UNITY),
            name=f"site[{site_id}].control_weight_milli",
        )
        # Validate authored capture threshold while graph is available.
        if "capture_threshold_milli" in site and site.get("capture_threshold_milli") is not None:
            _strict_positive_milli(
                site.get("capture_threshold_milli"),
                name=f"site[{site_id}].capture_threshold_milli",
            )
        metadata = site.get("metadata") if isinstance(site.get("metadata"), dict) else {}
        eligible_authored_site = (
            metadata.get("synthetic_anchor_control_site") is not True
            and bool(node_id)
            and node_id in authored_node_ids
        )
        prior = existing.get(site_id)
        if prior is None:
            control[site_id] = {
                "controller_faction": _initial_controller(state, site),
                "claimant_faction": None,
                "claimant_formation_id": None,
                "progress_ticks": 0,
                "required_ticks": hold,
                "province_id": province_id,
                "route_node_id": node_id,
                "control_weight_milli": weight,
                "authored_site_id": site_id,
                "site_kind": str(site.get("kind") or ""),
                "authored_site": eligible_authored_site,
                "synthetic_anchor_control_site": metadata.get("synthetic_anchor_control_site") is True,
            }
            continue
        control[site_id] = _validate_control_row(
            prior,
            site_id=site_id,
            hold=hold,
            province_id=province_id,
            node_id=node_id,
            weight=weight,
            default_controller=_initial_controller(state, site),
            site_kind=str(site.get("kind") or ""),
            authored_site=eligible_authored_site,
            synthetic_anchor=metadata.get("synthetic_anchor_control_site") is True,
        )
    set_site_control_state(state, control)
    return {"ensured": True, "site_count": len(control)}


def advance_site_capture(state: CampaignState) -> dict[str, Any]:
    """Advance control-site capture one operational tick."""
    ensured = ensure_site_control_state(state)
    if not ensured.get("ensured"):
        return {
            "advanced": False,
            "reason": ensured.get("reason", "no_graph"),
            "flipped_sites": [],
            "flipped_provinces": [],
        }
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
        row = control.get(site_id)
        if row is None:
            continue
        row["required_ticks"] = hold
        row["province_id"] = province_id
        row["route_node_id"] = node_id

        present = formations_at_node(state, node_id)
        if not present:
            _reset_claim(row)
            continue
        if _node_has_hostile_pair(state, present):
            _reset_claim(row)
            continue

        lead = _lead_formation(present)
        if lead is None:
            _reset_claim(row)
            continue
        controller = row.get("controller_faction")
        if controller and (
            lead.faction.value == controller
            or are_allied(state, lead.faction, Faction(str(controller)))
        ):
            _reset_claim(row)
            continue

        claimant_id = row.get("claimant_formation_id")
        claimant_faction = row.get("claimant_faction")
        if claimant_id and claimant_faction:
            claimant_force = state.strategic_formations.get(str(claimant_id))
            if (
                claimant_force is None
                or formation_at_node_id(claimant_force) != node_id
                or claimant_force.faction.value != str(claimant_faction)
            ):
                _reset_claim(row)
                claimant_id = None

        if not claimant_id:
            row["claimant_formation_id"] = lead.strategic_formation_id
            row["claimant_faction"] = lead.faction.value
            row["progress_ticks"] = 1
        else:
            progress = require_strict_int(
                row.get("progress_ticks", 0),
                name=f"site[{site_id}].progress_ticks",
                minimum=0,
            )
            row["progress_ticks"] = progress + 1

        progress = require_strict_int(
            row.get("progress_ticks", 0),
            name=f"site[{site_id}].progress_ticks",
            minimum=0,
        )
        if progress >= hold:
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
    """Frontend-facing site control rows (ensures initialization first)."""
    ensure_site_control_state(state)
    sites = {str(site.get("site_id")): site for site in list_control_sites(state)}
    control = get_site_control_state(state)
    rows: list[dict[str, Any]] = []
    hold = capture_hold_ticks(state)
    for site_id in sorted(set(sites) | set(control)):
        site = sites.get(site_id) or {}
        row = control.get(site_id) or {}
        weight = row.get("control_weight_milli", site.get("control_weight_milli", COST_MILLI_UNITY))
        progress = row.get("progress_ticks", 0)
        required = row.get("required_ticks", hold)
        rows.append(
            {
                "site_id": site_id,
                "display_name": site.get("display_name") or site_id,
                "province_id": row.get("province_id") or site.get("province_id") or "",
                "route_node_id": row.get("route_node_id") or site.get("route_node_id") or "",
                "control_weight_milli": require_strict_int(
                    weight, name="control_weight_milli", minimum=1
                ),
                "controller_faction": row.get("controller_faction"),
                "claimant_faction": row.get("claimant_faction"),
                "claimant_formation_id": row.get("claimant_formation_id"),
                "progress_ticks": require_strict_int(
                    progress, name="progress_ticks", minimum=0
                ),
                "required_ticks": require_strict_int(
                    required, name="required_ticks", minimum=1
                ),
                "pixel": list(site.get("pixel") or [0, 0]),
            }
        )
    return rows


def _validate_control_row(
    prior: dict[str, Any],
    *,
    site_id: str,
    hold: int,
    province_id: str,
    node_id: str,
    weight: int,
    default_controller: str | None,
    site_kind: str,
    authored_site: bool,
    synthetic_anchor: bool,
) -> dict[str, Any]:
    progress = require_strict_int(
        prior.get("progress_ticks", 0),
        name=f"site[{site_id}].progress_ticks",
        minimum=0,
    )
    required = require_strict_int(
        prior.get("required_ticks", hold),
        name=f"site[{site_id}].required_ticks",
        minimum=1,
    )
    row_weight = require_strict_int(
        prior.get("control_weight_milli", weight),
        name=f"site[{site_id}].control_weight_milli",
        minimum=1,
    )
    controller = (
        prior["controller_faction"]
        if "controller_faction" in prior
        else default_controller
    )
    if controller is not None:
        controller = str(controller)
        if not controller.strip():
            controller = None
    claimant = prior.get("claimant_faction")
    if claimant is not None:
        claimant = str(claimant) if str(claimant).strip() else None
    claimant_fid = prior.get("claimant_formation_id")
    if claimant_fid is not None:
        claimant_fid = str(claimant_fid) if str(claimant_fid).strip() else None
    # Both-or-neither for claim pair.
    if (claimant is None) != (claimant_fid is None):
        claimant = None
        claimant_fid = None
        progress = 0
    return {
        "controller_faction": controller,
        "claimant_faction": claimant,
        "claimant_formation_id": claimant_fid,
        "progress_ticks": progress,
        "required_ticks": required,
        "province_id": province_id or str(prior.get("province_id") or ""),
        "route_node_id": node_id or str(prior.get("route_node_id") or ""),
        "control_weight_milli": row_weight,
        "authored_site_id": site_id,
        "site_kind": site_kind,
        "authored_site": authored_site,
        "synthetic_anchor_control_site": synthetic_anchor,
    }


def _strict_positive_milli(value: Any, *, name: str) -> int:
    return require_strict_int(value, name=name, minimum=1)


def _initial_controller(state: CampaignState, site: dict[str, Any]) -> str | None:
    owner = site.get("owner_faction")
    if owner not in (None, ""):
        owner_id = str(owner)
        if owner_id in state.factions:
            return owner_id
        runtime = state.map_metadata.get("strategic_actor_runtime")
        actors = runtime.get("actors") if isinstance(runtime, dict) else None
        actor = actors.get(owner_id) if isinstance(actors, dict) else None
        if isinstance(actor, dict):
            campaign_faction = actor.get("campaign_faction")
            if isinstance(campaign_faction, str):
                try:
                    return Faction(campaign_faction).value
                except ValueError:
                    pass
            tactical_side = actor.get("tactical_side")
            if isinstance(tactical_side, str):
                from .strategic_actors import EngineTacticalSide

                try:
                    return EngineTacticalSide(tactical_side).campaign_faction().value
                except ValueError:
                    pass
        # Preserve legacy graph behavior for non-actor owner strings. Earth3 P3
        # actor IDs are resolved above through authenticated P2 runtime without
        # collapsing their strategic or Expanded tactical identity globally.
        return owner_id
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
    """Flip province owner only on strict majority site weight (ties preserve owner)."""
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
            weight = require_strict_int(
                row.get("control_weight_milli", site.get("control_weight_milli", COST_MILLI_UNITY)),
                name="control_weight_milli",
                minimum=1,
            )
            total_weight += weight
            controller = row.get("controller_faction")
            if controller:
                held[str(controller)] = held.get(str(controller), 0) + weight
        if total_weight <= 0 or not held:
            continue

        # Strict majority for multi-site; single-site uses capture_threshold_milli.
        if len(items) == 1:
            site, _row = items[0]
            threshold = require_strict_int(
                site.get("capture_threshold_milli", COST_MILLI_UNITY),
                name="capture_threshold_milli",
                minimum=1,
            )
            threshold = min(threshold, total_weight)
        else:
            threshold = total_weight // 2 + 1

        # Unique winner strictly meeting threshold; ties / multi-winners → no flip.
        winners = [
            faction_id
            for faction_id, weight in sorted(held.items())
            if weight >= threshold
        ]
        if len(winners) != 1:
            continue
        winner = winners[0]
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
            return [
                require_strict_int(pixel[0], name="pixel[0]", minimum=0),
                require_strict_int(pixel[1], name="pixel[1]", minimum=0),
            ]
    return None