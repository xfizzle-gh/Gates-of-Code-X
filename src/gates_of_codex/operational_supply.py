from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Any

from .diplomacy import allied_factions, is_friendly_owner
from .models import CampaignState, Faction, StrategicFormation
from .operational_movement import assert_edge_hop_legal
from .operational_position import load_operational_graph_for_state
from .operational_schema import (
    PROGRESS_MILLI_MAX,
    EdgeAuthority,
    EdgeKind,
    OperationalRouteEdge,
    PositionMode,
    require_strict_int,
    stable_node_id,
)
from .strategic import infrastructure_levels


_SEA_SUPPLY_OPT_IN_KINDS = frozenset(
    {
        EdgeKind.FERRY.value,
        EdgeKind.FERRY_OR_SEA_LANE.value,
        EdgeKind.SEA_LANE.value,
    }
)
_SOURCE_TAGS = frozenset({"supply_source", "supply_hub"})
OPERATIONAL_SUPPLY_SCHEMA_VERSION = 8
MIGRATION_RECORD_KEY = "operational_supply_migration"


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


@dataclass(frozen=True, slots=True)
class OperationalSupplyRoute:
    route_cost: int
    node_id_path: tuple[str, ...]
    edge_id_path: tuple[str, ...]
    source_hub_id: str

    @property
    def key(
        self,
    ) -> tuple[int, tuple[str, ...], tuple[str, ...], str]:
        return (
            self.route_cost,
            self.node_id_path,
            self.edge_id_path,
            self.source_hub_id,
        )


@dataclass(frozen=True, slots=True)
class OperationalSupplyReport:
    authoritative: bool
    connected: tuple[str, ...] = ()
    grace: tuple[str, ...] = ()
    cut_off: tuple[str, ...] = ()
    diagnostics: tuple[OperationalSupplyDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "authoritative": self.authoritative,
            "connected": list(self.connected),
            "grace": list(self.grace),
            "cut_off": list(self.cut_off),
            "diagnostics": [
                {
                    "source_hub_id": item.source_hub_id,
                    "province_id": item.province_id,
                    "reason": item.reason,
                }
                for item in self.diagnostics
            ],
        }


def ensure_operational_supply_state(state: CampaignState) -> dict[str, Any]:
    """Version S8 state only when an operational graph is authoritative."""
    incoming_schema = int(state.schema_version)
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return {
            "schema_version": incoming_schema,
            "map_id": state.map_id,
            "graph_loaded": False,
            "skipped": True,
        }

    state.schema_version = max(
        state.schema_version, OPERATIONAL_SUPPLY_SCHEMA_VERSION
    )
    if MIGRATION_RECORD_KEY not in state.map_metadata:
        state.map_metadata[MIGRATION_RECORD_KEY] = {
            "schema_version": OPERATIONAL_SUPPLY_SCHEMA_VERSION,
            "migrated_from_schema": min(
                incoming_schema, OPERATIONAL_SUPPLY_SCHEMA_VERSION
            ),
            "map_id": state.map_id,
            "graph_loaded": True,
            "source_identity": "logical-source-id-separate-from-routing-node",
            "grace_state": "one-disconnected-operational-tick",
        }
    return state.map_metadata[MIGRATION_RECORD_KEY]


def refresh_operational_supply(
    state: CampaignState,
    *,
    consume_grace: bool,
    completed_tick: int | None = None,
) -> OperationalSupplyReport:
    """Refresh graph connectivity and optionally advance persisted grace once."""
    if load_operational_graph_for_state(state) is None:
        return OperationalSupplyReport(authoritative=False)
    ensure_operational_supply_state(state)
    if consume_grace:
        completed_tick = require_strict_int(
            completed_tick,
            name="completed_tick",
            minimum=0,
        )

    from .operational_movement import get_operational_clock

    refresh_tick = (
        completed_tick
        if completed_tick is not None
        else int(get_operational_clock(state)["global_tick"])
    )
    connected_ids: list[str] = []
    grace_ids: list[str] = []
    cut_off_ids: list[str] = []
    diagnostics: set[OperationalSupplyDiagnostic] = set()
    routes_by_faction: dict[str, dict[str, OperationalSupplyRoute]] = {}

    for force in sorted(
        state.strategic_formations.values(),
        key=lambda item: item.strategic_formation_id,
    ):
        faction_key = force.faction.value
        routes = routes_by_faction.get(faction_key)
        if routes is None:
            sources, source_diagnostics = resolve_operational_supply_sources(
                state, force.faction
            )
            diagnostics.update(source_diagnostics)
            routes = compute_operational_supply_routes(
                state, force.faction, sources
            )
            routes_by_faction[faction_key] = routes
        route = route_for_formation(state, force, routes)
        force.last_supply_refresh_tick = refresh_tick
        force.last_supply_refresh_turn = int(state.turn_number)
        if route is not None:
            force.supplied = True
            force.cut_off = False
            force.source_hub_id = route.source_hub_id
            force.route_cost = route.route_cost
            force.grace_ticks_remaining = 0
            if consume_grace:
                force.last_grace_consuming_tick = completed_tick
            connected_ids.append(force.strategic_formation_id)
            continue

        force.source_hub_id = None
        force.route_cost = None
        if (
            consume_grace
            and force.last_grace_consuming_tick != completed_tick
        ):
            if force.grace_ticks_remaining == 1:
                force.supplied = False
                force.cut_off = True
                force.grace_ticks_remaining = 0
            elif force.cut_off:
                force.supplied = False
            else:
                force.supplied = True
                force.cut_off = False
                force.grace_ticks_remaining = 1
            force.last_grace_consuming_tick = completed_tick
        if force.cut_off:
            cut_off_ids.append(force.strategic_formation_id)
        elif force.grace_ticks_remaining == 1:
            grace_ids.append(force.strategic_formation_id)

    return OperationalSupplyReport(
        authoritative=True,
        connected=tuple(connected_ids),
        grace=tuple(grace_ids),
        cut_off=tuple(cut_off_ids),
        diagnostics=tuple(sorted(diagnostics, key=_diagnostic_sort_key)),
    )


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


    friendly_values = tuple(
        sorted(item.value for item in allied_factions(state, faction))
    )
    friendly_set = set(friendly_values)
    control = _site_control_snapshot(state)
    sources: list[OperationalSupplySource] = []
    diagnostics: list[OperationalSupplyDiagnostic] = []
    source_sites_by_province: dict[str, list[dict[str, Any]]] = {}

    for site in sites:
        if not _site_is_usable_supply_source(site):
            continue
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
        invalid_reason = _source_node_invalid_reason(
            nodes, node_id, province_id
        )
        if invalid_reason is not None:
            diagnostics.append(
                OperationalSupplyDiagnostic(
                    source_id, province_id, invalid_reason
                )
            )
            continue
        source_sites_by_province.setdefault(province_id, []).append(site)
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


def compute_operational_supply_routes(
    state: CampaignState,
    faction: Faction,
    sources: tuple[OperationalSupplySource, ...],
) -> dict[str, OperationalSupplyRoute]:
    """Return the best legal node-to-source route for one faction."""
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return {}
    nodes, edges = _routing_graph_indexes(graph)
    if not nodes:
        return {}

    reverse: dict[str, list[tuple[str, str, int]]] = {}
    for edge_id in sorted(edges):
        edge = edges[edge_id]
        if not _node_is_friendly(state, faction, nodes[edge.a]):
            continue
        if not _node_is_friendly(state, faction, nodes[edge.b]):
            continue
        cost = edge.movement_cost_milli
        try:
            assert_supply_edge_hop_legal(edge, origin=edge.a, dest=edge.b)
        except ValueError:
            pass
        else:
            reverse.setdefault(edge.b, []).append((edge.a, edge.edge_id, cost))
        try:
            assert_supply_edge_hop_legal(edge, origin=edge.b, dest=edge.a)
        except ValueError:
            pass
        else:
            reverse.setdefault(edge.a, []).append((edge.b, edge.edge_id, cost))
    for node_id in list(reverse):
        reverse[node_id] = sorted(
            reverse[node_id], key=lambda row: (row[0], row[1], row[2])
        )

    best: dict[str, OperationalSupplyRoute] = {}
    heap: list[
        tuple[
            tuple[int, tuple[str, ...], tuple[str, ...], str],
            str,
        ]
    ] = []
    for source in sorted(sources, key=_source_sort_key):
        node_id = source.source_node_id
        node = nodes.get(node_id)
        if node is None or not _node_is_friendly(state, faction, node):
            continue
        route = OperationalSupplyRoute(
            route_cost=0,
            node_id_path=(node_id,),
            edge_id_path=(),
            source_hub_id=source.source_hub_id,
        )
        previous = best.get(node_id)
        if previous is not None and previous.key <= route.key:
            continue
        best[node_id] = route
        heappush(heap, (route.key, node_id))

    while heap:
        key, node_id = heappop(heap)
        current = best.get(node_id)
        if current is None or current.key != key:
            continue
        for predecessor, edge_id, cost in reverse.get(node_id, ()):
            candidate = OperationalSupplyRoute(
                route_cost=current.route_cost + cost,
                node_id_path=(predecessor,) + current.node_id_path,
                edge_id_path=(edge_id,) + current.edge_id_path,
                source_hub_id=current.source_hub_id,
            )
            previous = best.get(predecessor)
            if previous is not None and previous.key <= candidate.key:
                continue
            best[predecessor] = candidate
            heappush(heap, (candidate.key, predecessor))
    return {node_id: best[node_id] for node_id in sorted(best)}


def route_for_formation(
    state: CampaignState,
    formation: StrategicFormation,
    routes: dict[str, OperationalSupplyRoute],
) -> OperationalSupplyRoute | None:
    graph = load_operational_graph_for_state(state)
    position = formation.position
    if graph is None or position is None:
        return None
    if position.mode == PositionMode.AT_NODE.value:
        return routes.get(str(position.node_id or ""))
    if position.mode != PositionMode.ON_EDGE.value:
        return None

    _nodes, edges = _routing_graph_indexes(graph)
    edge_id = str(position.edge_id or "")
    edge = edges.get(edge_id)
    if edge is None:
        return None
    facing = str(position.facing_node_id or "")
    progress = require_strict_int(
        position.progress_milli,
        name="progress_milli",
        minimum=0,
        maximum=PROGRESS_MILLI_MAX,
    )
    if facing == edge.b:
        canonical = progress
    elif facing == edge.a:
        canonical = PROGRESS_MILLI_MAX - progress
    else:
        return None

    candidates: list[OperationalSupplyRoute] = []
    for endpoint, segment, origin, dest in (
        (edge.a, canonical, edge.b, edge.a),
        (
            edge.b,
            PROGRESS_MILLI_MAX - canonical,
            edge.a,
            edge.b,
        ),
    ):
        try:
            assert_supply_edge_hop_legal(edge, origin=origin, dest=dest)
        except ValueError:
            continue
        endpoint_route = routes.get(endpoint)
        if endpoint_route is None:
            continue
        if endpoint_route.edge_id_path[:1] == (edge_id,):
            continue
        attachment = on_edge_attachment_cost(edge.movement_cost_milli, segment)
        candidates.append(
            OperationalSupplyRoute(
                route_cost=attachment + endpoint_route.route_cost,
                node_id_path=endpoint_route.node_id_path,
                edge_id_path=(edge_id,) + endpoint_route.edge_id_path,
                source_hub_id=endpoint_route.source_hub_id,
            )
        )
    return None if not candidates else min(candidates, key=lambda item: item.key)


def on_edge_attachment_cost(edge_cost: int, segment_milli: int) -> int:
    cost = require_strict_int(edge_cost, name="edge_cost", minimum=1)
    segment = require_strict_int(
        segment_milli,
        name="segment_milli",
        minimum=0,
        maximum=PROGRESS_MILLI_MAX,
    )
    return (cost * segment + PROGRESS_MILLI_MAX - 1) // PROGRESS_MILLI_MAX


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
    metadata = edge.metadata or {}
    if "supply_capable" in metadata and type(
        metadata["supply_capable"]
    ) is not bool:
        raise ValueError("invalid_supply_capable")
    flag = metadata.get("supply_capable")
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


def _site_is_usable_supply_source(site: dict[str, Any]) -> bool:
    if not _site_is_explicit_supply_source(site):
        return False
    if str(
        site.get("authority", EdgeAuthority.AUTHORED.value)
    ) != EdgeAuthority.AUTHORED.value:
        return False
    metadata = site.get("metadata") or {}
    return not bool(metadata.get("disabled"))


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
        if _source_node_invalid_reason(nodes, node_id, province_id) is None:
            return node_id
    if associated_node_id and _source_node_invalid_reason(
        nodes, associated_node_id, province_id
    ) is None:
        return associated_node_id
    anchor_id = stable_node_id(province_id, "anchor")
    return (
        anchor_id
        if _source_node_invalid_reason(nodes, anchor_id, province_id) is None
        else None
    )


def _source_node_invalid_reason(
    nodes: dict[str, dict[str, Any]], node_id: str, province_id: str
) -> str | None:
    node = nodes.get(node_id)
    if node is None:
        return "missing_source_node"
    if str(node.get("province_id") or "") != province_id:
        return "cross_province_source_node"
    if str(
        node.get("authority", EdgeAuthority.AUTHORED.value)
    ) != EdgeAuthority.AUTHORED.value:
        return "non_authored_source_node"
    return None


def _source_sort_key(source: OperationalSupplySource) -> tuple[str, str, str]:
    return source.source_hub_id, source.source_node_id, source.province_id


def _diagnostic_sort_key(
    diagnostic: OperationalSupplyDiagnostic,
) -> tuple[str, str, str]:
    return diagnostic.source_hub_id, diagnostic.province_id, diagnostic.reason


def _routing_graph_indexes(
    graph: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, OperationalRouteEdge]]:
    nodes = {
        str(row.get("node_id")): dict(row)
        for row in graph.get("nodes") or []
        if isinstance(row, dict) and str(row.get("node_id") or "").strip()
    }
    edges: dict[str, OperationalRouteEdge] = {}
    for row in graph.get("edges") or []:
        if not isinstance(row, dict):
            continue
        try:
            edge = OperationalRouteEdge(
                edge_id=str(row["edge_id"]),
                a=str(row["a"]),
                b=str(row["b"]),
                kind=str(row["kind"]),
                authority=str(row["authority"]),
                length_px=require_strict_int(
                    row.get("length_px", 1), name="length_px", minimum=1
                ),
                base_move_points_milli=require_strict_int(
                    row.get("base_move_points_milli", 1000),
                    name="base_move_points_milli",
                    minimum=1,
                ),
                movement_cost_milli=require_strict_int(
                    row.get("movement_cost_milli", 1000),
                    name="movement_cost_milli",
                    minimum=1,
                ),
                requires_port=_strict_graph_bool(
                    row.get("requires_port", False), "requires_port"
                ),
                can_be_blockaded=_strict_graph_bool(
                    row.get("can_be_blockaded", False), "can_be_blockaded"
                ),
                traversal_enabled=_strict_graph_bool(
                    row.get("traversal_enabled", True), "traversal_enabled"
                ),
                bidirectional=_strict_graph_bool(
                    row.get("bidirectional", True), "bidirectional"
                ),
                province_ids=list(row.get("province_ids") or []),
                legacy_crossing_type=row.get("legacy_crossing_type"),
                metadata=dict(row.get("metadata") or {}),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not edge.edge_id.strip() or edge.a not in nodes or edge.b not in nodes:
            continue
        edges[edge.edge_id] = edge
    return nodes, edges


def _strict_graph_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be bool")
    return value


def _node_is_friendly(
    state: CampaignState, faction: Faction, node: dict[str, Any]
) -> bool:
    province = state.provinces.get(str(node.get("province_id") or ""))
    return province is not None and is_friendly_owner(
        state, faction, province.owner
    )
