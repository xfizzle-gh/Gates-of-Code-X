from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class SiteKind(str, Enum):
    SETTLEMENT = "settlement"
    PORT = "port"
    AIRFIELD = "airfield"
    BRIDGE = "bridge"
    FACILITY = "facility"
    OBJECTIVE = "objective"
    CROSSING = "crossing"
    FORT = "fort"
    DEPOT = "depot"


class NodeKind(str, Enum):
    """Generic route nodes must not falsely claim to be real settlements."""

    ANCHOR = "anchor"  # province migration/centroid anchor
    JUNCTION = "junction"
    SITE = "site"  # bound to a real StrategicSite only


class EdgeKind(str, Enum):
    ROAD = "road"
    RAIL = "rail"
    CORRIDOR = "corridor"  # generic land adjacency candidate — not invented road
    MOUNTAIN_PASS = "mountain_pass"
    STRAIT = "strait"
    FERRY = "ferry"
    FERRY_OR_SEA_LANE = "ferry_or_sea_lane"
    SEA_LANE = "sea_lane"
    RIVER_CROSSING = "river_crossing"


class EdgeAuthority(str, Enum):
    CANDIDATE = "candidate"
    AUTHORED = "authored"


class PositionMode(str, Enum):
    AT_NODE = "at_node"
    ON_EDGE = "on_edge"


class MoveOrderStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


PROGRESS_MILLI_MIN = 0
PROGRESS_MILLI_MAX = 1000


DEFAULT_CROSSING_META: dict[str, dict[str, Any]] = {
    EdgeKind.STRAIT.value: {
        "movement_cost_multiplier": 1.25,
        "requires_port": False,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.FERRY.value: {
        "movement_cost_multiplier": 1.5,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.FERRY_OR_SEA_LANE.value: {
        "movement_cost_multiplier": 1.5,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.SEA_LANE.value: {
        "movement_cost_multiplier": 2.0,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.CORRIDOR.value: {
        "movement_cost_multiplier": 1.0,
        "requires_port": False,
        "can_be_blockaded": False,
        "bidirectional": True,
    },
    EdgeKind.ROAD.value: {
        "movement_cost_multiplier": 1.0,
        "requires_port": False,
        "can_be_blockaded": False,
        "bidirectional": True,
    },
    EdgeKind.RAIL.value: {
        "movement_cost_multiplier": 0.75,
        "requires_port": False,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.MOUNTAIN_PASS.value: {
        "movement_cost_multiplier": 1.75,
        "requires_port": False,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.RIVER_CROSSING.value: {
        "movement_cost_multiplier": 1.25,
        "requires_port": False,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
}


@dataclass(slots=True)
class StrategicSite:
    site_id: str
    display_name: str
    kind: str
    province_id: str
    pixel: list[int]
    route_node_id: str
    control_weight: float = 1.0
    capture_threshold: float = 1.0
    tags: list[str] = field(default_factory=list)
    facilities: list[str] = field(default_factory=list)
    owner_faction: str | None = None
    authority: str = EdgeAuthority.AUTHORED.value
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, node_ids: set[str], province_ids: set[str]) -> None:
        if not self.site_id.strip():
            raise ValueError("site_id required")
        if self.kind not in {item.value for item in SiteKind}:
            raise ValueError(f"invalid site kind {self.kind}")
        if self.province_id not in province_ids:
            raise ValueError(f"site {self.site_id} province missing: {self.province_id}")
        if self.route_node_id not in node_ids:
            raise ValueError(f"site {self.site_id} node missing: {self.route_node_id}")
        if len(self.pixel) != 2:
            raise ValueError(f"site {self.site_id} pixel must be [x,y]")


@dataclass(slots=True)
class OperationalRouteNode:
    node_id: str
    display_name: str
    kind: str
    pixel: list[int]
    province_id: str
    site_id: str | None = None
    terrain: str = "unknown"
    is_hub: bool = False
    authority: str = EdgeAuthority.AUTHORED.value
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, province_ids: set[str], site_ids: set[str]) -> None:
        if not self.node_id.strip():
            raise ValueError("node_id required")
        if self.kind not in {item.value for item in NodeKind}:
            raise ValueError(f"invalid node kind {self.kind}")
        if self.province_id not in province_ids:
            raise ValueError(f"node {self.node_id} province missing: {self.province_id}")
        if len(self.pixel) != 2:
            raise ValueError(f"node {self.node_id} pixel must be [x,y]")
        if self.kind == NodeKind.SITE.value and not self.site_id:
            raise ValueError(f"site node {self.node_id} requires site_id")
        if self.site_id and self.site_id not in site_ids:
            raise ValueError(f"node {self.node_id} site missing: {self.site_id}")
        # Generic anchors must not claim to be real settlements.
        if self.kind == NodeKind.ANCHOR.value and self.site_id:
            raise ValueError(f"anchor node {self.node_id} must not bind a site")


@dataclass(slots=True)
class OperationalRouteEdge:
    edge_id: str
    a: str
    b: str
    kind: str
    authority: str
    length_px: float = 1.0
    base_move_points: float = 1.0
    movement_cost_multiplier: float = 1.0
    requires_port: bool = False
    can_be_blockaded: bool = False
    bidirectional: bool = True
    province_ids: list[str] = field(default_factory=list)
    legacy_crossing_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(
        self,
        *,
        node_ids: set[str],
        province_ids: set[str],
        node_province: dict[str, str],
    ) -> None:
        if not self.edge_id.strip():
            raise ValueError("edge_id required")
        if self.a not in node_ids or self.b not in node_ids:
            raise ValueError(f"edge {self.edge_id} references missing nodes")
        if self.a == self.b:
            raise ValueError(f"edge {self.edge_id} is a self-loop")
        if self.kind not in {item.value for item in EdgeKind}:
            raise ValueError(f"invalid edge kind {self.kind}")
        if self.authority not in {item.value for item in EdgeAuthority}:
            raise ValueError(f"invalid edge authority {self.authority}")
        if self.length_px <= 0:
            raise ValueError(f"edge {self.edge_id} length must be positive")
        if self.base_move_points <= 0:
            raise ValueError(f"edge {self.edge_id} base_move_points must be positive")
        if len(self.province_ids) != 2 or len(set(self.province_ids)) != 2:
            raise ValueError(
                f"edge {self.edge_id} must list exactly two distinct province_ids"
            )
        for pid in self.province_ids:
            if pid not in province_ids:
                raise ValueError(f"edge {self.edge_id} province missing: {pid}")
        endpoint_provinces = {node_province[self.a], node_province[self.b]}
        if endpoint_provinces != set(self.province_ids):
            raise ValueError(
                f"edge {self.edge_id} province_ids must match endpoint node provinces"
            )
        # Authority vs kind rules.
        if self.authority == EdgeAuthority.AUTHORED.value and self.kind == EdgeKind.CORRIDOR.value:
            raise ValueError(f"authored edge {self.edge_id} cannot be corridor")
        if self.authority == EdgeAuthority.CANDIDATE.value and self.kind in {
            EdgeKind.ROAD.value,
            EdgeKind.RAIL.value,
        }:
            raise ValueError(f"candidate edge {self.edge_id} cannot claim road/rail")
        if self.authority == EdgeAuthority.CANDIDATE.value and self.kind != EdgeKind.CORRIDOR.value:
            # S1 candidates are corridors only.
            raise ValueError(f"candidate edge {self.edge_id} must be corridor in S1")
        if self.authority == EdgeAuthority.AUTHORED.value and self.kind not in {
            EdgeKind.STRAIT.value,
            EdgeKind.FERRY.value,
            EdgeKind.FERRY_OR_SEA_LANE.value,
            EdgeKind.SEA_LANE.value,
        }:
            # Current authored set is sea/strait/ferry only; keep strict for S1.
            if self.legacy_crossing_type:
                raise ValueError(
                    f"authored crossing edge {self.edge_id} has unexpected kind {self.kind}"
                )


@dataclass(slots=True)
class FormationOperationalPosition:
    """Serialized formation location on the operational graph (unused in S1 gameplay)."""

    mode: str = PositionMode.AT_NODE.value
    node_id: str | None = None
    edge_id: str | None = None
    progress_milli: int = 0
    facing_node_id: str | None = None

    def validate(
        self,
        *,
        node_ids: set[str],
        edge_ids: set[str],
        edges_by_id: dict[str, OperationalRouteEdge],
    ) -> None:
        if self.mode == PositionMode.AT_NODE.value:
            if not self.node_id or self.node_id not in node_ids:
                raise ValueError("at_node position requires valid node_id")
            if self.edge_id is not None:
                raise ValueError("at_node position must not set edge_id")
            if int(self.progress_milli) != 0:
                raise ValueError("at_node progress_milli must be 0")
            if self.facing_node_id is not None:
                raise ValueError("at_node position must not set facing_node_id")
        elif self.mode == PositionMode.ON_EDGE.value:
            if not self.edge_id or self.edge_id not in edge_ids:
                raise ValueError("on_edge position requires valid edge_id")
            if self.node_id is not None:
                raise ValueError("on_edge position must not set node_id")
            progress = int(self.progress_milli)
            if progress < PROGRESS_MILLI_MIN or progress > PROGRESS_MILLI_MAX:
                raise ValueError("progress_milli must be in 0..1000")
            if not self.facing_node_id or self.facing_node_id not in node_ids:
                raise ValueError("on_edge requires valid facing_node_id")
            edge = edges_by_id[self.edge_id]
            if self.facing_node_id not in {edge.a, edge.b}:
                raise ValueError("facing_node_id must be an endpoint of edge_id")
        else:
            raise ValueError(f"invalid position mode {self.mode}")


@dataclass(slots=True)
class OperationalMoveOrder:
    order_id: str
    formation_id: str
    path_node_ids: list[str] = field(default_factory=list)
    path_edge_ids: list[str] = field(default_factory=list)
    destination_site_id: str | None = None
    issued_tick: int = 0
    status: str = MoveOrderStatus.PENDING.value

    def validate(
        self,
        *,
        node_ids: set[str],
        edge_ids: set[str],
        site_ids: set[str],
        edges_by_id: dict[str, OperationalRouteEdge],
    ) -> None:
        if not self.order_id.strip() or not self.formation_id.strip():
            raise ValueError("order_id and formation_id required")
        if self.status not in {item.value for item in MoveOrderStatus}:
            raise ValueError(f"invalid move order status {self.status}")
        if int(self.issued_tick) < 0:
            raise ValueError("issued_tick must be >= 0")
        if not self.path_node_ids:
            raise ValueError("path_node_ids must be non-empty")
        if len(self.path_node_ids) != len(self.path_edge_ids) + 1:
            raise ValueError("len(path_node_ids) must equal len(path_edge_ids) + 1")
        for node_id in self.path_node_ids:
            if node_id not in node_ids:
                raise ValueError(f"path references missing node {node_id}")
        for edge_id in self.path_edge_ids:
            if edge_id not in edge_ids:
                raise ValueError(f"path references missing edge {edge_id}")
        for left, right in zip(self.path_node_ids, self.path_node_ids[1:]):
            if left == right:
                raise ValueError("path must not contain consecutive duplicate nodes")
        for index, edge_id in enumerate(self.path_edge_ids):
            edge = edges_by_id[edge_id]
            pair = {self.path_node_ids[index], self.path_node_ids[index + 1]}
            if pair != {edge.a, edge.b}:
                raise ValueError(
                    f"path edge {edge_id} does not connect nodes "
                    f"{self.path_node_ids[index]} and {self.path_node_ids[index + 1]}"
                )
        if self.destination_site_id is not None and self.destination_site_id not in site_ids:
            raise ValueError(f"destination_site_id missing: {self.destination_site_id}")


@dataclass(slots=True)
class OperationalRules:
    ticks_per_strategic_turn: int = 10
    capture_hold_ticks: int = 2
    max_friendly_formations_per_node: int = 3
    capture_mode: str = "control_site_node_only"
    interception_mode: str = "swept_movement"
    formation_is_movement_authority: bool = True

    def validate(self) -> None:
        if self.ticks_per_strategic_turn < 1:
            raise ValueError("ticks_per_strategic_turn must be >= 1")
        if self.capture_hold_ticks < 1:
            raise ValueError("capture_hold_ticks must be >= 1")
        if self.max_friendly_formations_per_node < 1:
            raise ValueError("max_friendly_formations_per_node must be >= 1")


@dataclass(slots=True)
class OperationalGraph:
    map_id: str
    schema: str = "gates-of-codex.operational-graph"
    schema_version: int = 1
    rules: OperationalRules = field(default_factory=OperationalRules)
    sites: list[StrategicSite] = field(default_factory=list)
    nodes: list[OperationalRouteNode] = field(default_factory=list)
    edges: list[OperationalRouteEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, province_ids: Iterable[str]) -> None:
        provinces = set(province_ids)
        self.rules.validate()
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate node_ids")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("duplicate edge_ids")
        site_ids = [site.site_id for site in self.sites]
        if len(site_ids) != len(set(site_ids)):
            raise ValueError("duplicate site_ids")
        node_id_set = set(node_ids)
        site_id_set = set(site_ids)
        node_province = {node.node_id: node.province_id for node in self.nodes}
        edges_by_id = {edge.edge_id: edge for edge in self.edges}
        for site in self.sites:
            site.validate(node_ids=node_id_set, province_ids=provinces)
        for node in self.nodes:
            node.validate(province_ids=provinces, site_ids=site_id_set)
        for edge in self.edges:
            edge.validate(
                node_ids=node_id_set,
                province_ids=provinces,
                node_province=node_province,
            )
        # Bidirectional undirected uniqueness.
        undirected: set[tuple[str, str, str]] = set()
        for edge in self.edges:
            key = (edge.kind, *sorted((edge.a, edge.b)))
            if key in undirected:
                raise ValueError(f"duplicate undirected edge for {key}")
            undirected.add(key)
        # Expose helpers for optional order/position checks by callers.
        self.metadata.setdefault("_validated_edge_ids", sorted(edges_by_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "map_id": self.map_id,
            "rules": asdict(self.rules),
            "sites": [asdict(site) for site in sorted(self.sites, key=lambda item: item.site_id)],
            "nodes": [asdict(node) for node in sorted(self.nodes, key=lambda item: item.node_id)],
            "edges": [asdict(edge) for edge in sorted(self.edges, key=lambda item: item.edge_id)],
            "metadata": dict(self.metadata),
        }


def crossing_type_to_edge_kind(crossing_type: str) -> str:
    value = crossing_type.strip().lower()
    mapping = {
        "strait": EdgeKind.STRAIT.value,
        "ferry": EdgeKind.FERRY.value,
        "ferry_or_sea_lane": EdgeKind.FERRY_OR_SEA_LANE.value,
        "sea_lane": EdgeKind.SEA_LANE.value,
        "land": EdgeKind.CORRIDOR.value,
    }
    if value not in mapping:
        raise ValueError(f"unsupported crossing type {crossing_type}")
    return mapping[value]


def apply_default_meta(kind: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(DEFAULT_CROSSING_META.get(kind, DEFAULT_CROSSING_META[EdgeKind.CORRIDOR.value]))
    if overrides:
        for key in (
            "movement_cost_multiplier",
            "requires_port",
            "can_be_blockaded",
            "bidirectional",
        ):
            if key in overrides:
                base[key] = overrides[key]
    return base


def stable_node_id(province_id: str, suffix: str = "anchor") -> str:
    safe = province_id.strip().replace(" ", "_")
    return f"op-node-{safe}-{suffix}"


def stable_edge_id(kind: str, a: str, b: str) -> str:
    left, right = sorted((a, b))
    return f"op-edge-{kind}-{left}__{right}"


def stable_site_id(province_id: str, kind: str, slug: str) -> str:
    safe_p = province_id.strip().replace(" ", "_")
    safe_s = slug.strip().replace(" ", "_")
    return f"op-site-{kind}-{safe_p}-{safe_s}"
