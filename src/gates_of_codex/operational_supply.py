from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .diplomacy import allied_factions, is_friendly_owner
from .models import CampaignState, Faction
from .operational_movement import assert_edge_hop_legal
from .operational_position import load_operational_graph_for_state
from .operational_schema import EdgeKind, OperationalRouteEdge, stable_node_id
from .strategic import infrastructure_levels


_SEA_SUPPLY_OPT_IN_KINDS = frozenset(
    {
        EdgeKind.FERRY.value,
        EdgeKind.FERRY_OR_SEA_LANE.value,
        EdgeKind.SEA_LANE.value,
    }
)
_SOURCE_TAGS = frozenset({"supply_source", "supply_hub"})


@dataclass(frozen=True, slots=True)
class OperationalSupplySource:
    source_hub_id: str
    source_node_id: str
    province_id: str
    eligible_factions: tuple[str, ...]
    source_kind: str


@dataclass(frozen=True, slots=True)
class OperationalSupplyDiagnostic:
    source_hub_id: str
    province_id: str
    reason: str


def resolve_operational_supply_sources(
    state: CampaignState, faction: Faction
) -> tuple[
    tuple[OperationalSupplySource, ...],
    tuple[OperationalSupplyDiagnostic, ...],
]:
    """Resolve existing logical sources onto authored operational nodes."""
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return (), ()

    nodes = {
        str(row.get("node_id")): dict(row)
        for row in graph.get("nodes") or []
        if isinstance(row, dict) and str(row.get("node_id") or "").strip()
    }
    sites = sorted(
        (
            dict(row)
            for row in graph.get("sites") or []
            if isinstance(row, dict) and str(row.get("site_id") or "").strip()
        ),
        key=lambda row: str(row["site_id"]),
    )
    source_sites = [row for row in sites if _site_is_explicit_supply_source(row)]
    source_sites_by_province: dict[str, list[dict[str, Any]]] = {}
    for site in source_sites:
        source_sites_by_province.setdefault(
            str(site.get("province_id") or ""), []
        ).append(site)

    friendly_values = tuple(
        sorted(item.value for item in allied_factions(state, faction))
    )
    friendly_set = set(friendly_values)
    control = _site_control_snapshot(state)
    sources: list[OperationalSupplySource] = []
    diagnostics: list[OperationalSupplyDiagnostic] = []

    for site in source_sites:
        province_id = str(site.get("province_id") or "")
        source_id = str(site["site_id"])
        if province_id not in state.provinces:
            diagnostics.append(
                OperationalSupplyDiagnostic(source_id, province_id, "missing_province")
            )
            continue
        controller = _site_controller(state, site, control)
        if controller not in friendly_set:
            continue
        node_id = str(site.get("route_node_id") or "")
        if node_id not in nodes:
            diagnostics.append(
                OperationalSupplyDiagnostic(source_id, province_id, "missing_source_node")
            )
            continue
        sources.append(
            OperationalSupplySource(
                source_hub_id=source_id,
                source_node_id=node_id,
                province_id=province_id,
                eligible_factions=(controller,),
                source_kind="authored_site",
            )
        )

    for province_id in sorted(state.provinces):
        province = state.provinces[province_id]
        if not is_friendly_owner(state, faction, province.owner):
            continue
        meta = province.metadata or {}
        static_values = {
            str(item) for item in meta.get("static_supply_source_for", [])
        }
        dynamic_values = {str(item) for item in meta.get("supply_source_for", [])}
        hub_level = infrastructure_levels(province).get("supply_hub", 0)
        constructed = hub_level > 0 and province.owner != Faction.NEUTRAL
        if constructed and province.owner.value in friendly_set:
            source_id = f"constructed-supply-hub:{province_id}"
            node_id = _routing_node_for_source(
                province_id=province_id,
                nodes=nodes,
                source_sites_by_province=source_sites_by_province,
                associated_node_id=str(meta.get("supply_hub_node_id") or ""),
            )
            if node_id is None:
                diagnostics.append(
                    OperationalSupplyDiagnostic(source_id, province_id, "missing_anchor")
                )
            else:
                sources.append(
                    OperationalSupplySource(
                        source_hub_id=source_id,
                        source_node_id=node_id,
                        province_id=province_id,
                        eligible_factions=(province.owner.value,),
                        source_kind="constructed_hub",
                    )
                )

        # sync_province_infrastructure_owner writes the constructed hub owner to
        # supply_source_for. Do not turn that same authority into a second source.
        metadata_values = static_values | dynamic_values
        if constructed and province.owner.value not in static_values:
            metadata_values.discard(province.owner.value)
        eligible = tuple(sorted(metadata_values & friendly_set))
        if not eligible:
            continue
        source_id = f"province-supply-source:{province_id}"
        node_id = _routing_node_for_source(
            province_id=province_id,
            nodes=nodes,
            source_sites_by_province=source_sites_by_province,
        )
        if node_id is None:
            diagnostics.append(
                OperationalSupplyDiagnostic(source_id, province_id, "missing_anchor")
            )
            continue
        sources.append(
            OperationalSupplySource(
                source_hub_id=source_id,
                source_node_id=node_id,
                province_id=province_id,
                eligible_factions=eligible,
                source_kind="province_metadata",
            )
        )

    return (
        tuple(sorted(sources, key=_source_sort_key)),
        tuple(sorted(diagnostics, key=_diagnostic_sort_key)),
    )


def edge_is_supply_capable(edge: OperationalRouteEdge) -> bool:
    try:
        assert_supply_edge_hop_legal(edge, origin=edge.a, dest=edge.b)
    except ValueError:
        if edge.bidirectional:
            try:
                assert_supply_edge_hop_legal(edge, origin=edge.b, dest=edge.a)
            except ValueError:
                return False
            return True
        return False
    return True


def assert_supply_edge_hop_legal(
    edge: OperationalRouteEdge, *, origin: str, dest: str
) -> None:
    """Apply shared movement authority plus S8 sea-edge opt-in."""
    assert_edge_hop_legal(edge, origin=origin, dest=dest)
    flag = (edge.metadata or {}).get("supply_capable")
    if flag is False:
        raise ValueError("supply_blocked")
    if edge.kind in _SEA_SUPPLY_OPT_IN_KINDS and flag is not True:
        raise ValueError("supply_opt_in_required")


def _site_is_explicit_supply_source(site: dict[str, Any]) -> bool:
    metadata = site.get("metadata") or {}
    tags = {str(item) for item in site.get("tags") or []}
    facilities = {str(item) for item in site.get("facilities") or []}
    if metadata.get("supply_source") is True:
        return True
    if _SOURCE_TAGS.intersection(tags | facilities):
        return True
    return str(site.get("kind") or "") == "depot"


def _site_control_snapshot(state: CampaignState) -> dict[str, dict[str, Any]]:
    from .operational_capture import get_site_control_state

    return get_site_control_state(state)


def _site_controller(
    state: CampaignState,
    site: dict[str, Any],
    control: dict[str, dict[str, Any]],
) -> str:
    site_id = str(site.get("site_id") or "")
    row = control.get(site_id) or {}
    controller = str(
        row.get("controller_faction") or site.get("owner_faction") or ""
    )
    if controller:
        return controller
    province = state.provinces.get(str(site.get("province_id") or ""))
    return "" if province is None else province.owner.value


def _routing_node_for_source(
    *,
    province_id: str,
    nodes: dict[str, dict[str, Any]],
    source_sites_by_province: dict[str, list[dict[str, Any]]],
    associated_node_id: str = "",
) -> str | None:
    for site in source_sites_by_province.get(province_id, []):
        node_id = str(site.get("route_node_id") or "")
        if node_id in nodes:
            return node_id
    if associated_node_id and associated_node_id in nodes:
        return associated_node_id
    anchor_id = stable_node_id(province_id, "anchor")
    return anchor_id if anchor_id in nodes else None


def _source_sort_key(source: OperationalSupplySource) -> tuple[str, str, str]:
    return source.source_hub_id, source.source_node_id, source.province_id


def _diagnostic_sort_key(
    diagnostic: OperationalSupplyDiagnostic,
) -> tuple[str, str, str]:
    return diagnostic.source_hub_id, diagnostic.province_id, diagnostic.reason
