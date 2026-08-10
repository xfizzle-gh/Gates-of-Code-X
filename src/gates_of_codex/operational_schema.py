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
    OBSERVATION = "observation"
    COMMAND = "command"


class NodeKind(str, Enum):
    """Generic route nodes must not falsely claim to be real settlements."""

    ANCHOR = "anchor"
    JUNCTION = "junction"
    SITE = "site"


class EdgeKind(str, Enum):
    ROAD = "road"
    RAIL = "rail"
    CORRIDOR = "corridor"
    MOUNTAIN_PASS = "mountain_pass"
    STRAIT = "strait"
    FERRY = "ferry"
    FERRY_OR_SEA_LANE = "ferry_or_sea_lane"
    SEA_LANE = "sea_lane"
    RIVER_CROSSING = "river_crossing"


class EdgeAuthority(str, Enum):
    CANDIDATE = "candidate"
    AUTHORED = "authored"
    APPROVED = "approved"


class PositionMode(str, Enum):
    AT_NODE = "at_node"
    ON_EDGE = "on_edge"


class MoveOrderStatus(str, Enum):
    """Weekly commitment model statuses."""

    DRAFT = "draft"  # player is planning; not locked
    COMMITTED = "committed"  # locked for the strategic turn/week
    ACTIVE = "active"  # resolving across operational ticks
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class FormationStance(str, Enum):
    """Approved stable stance IDs for locked commitment."""

    OPERATIONAL = "operational"
    FORCED_MARCH = "forced_march"
    ENTRENCHED = "entrenched"
    REFIT_RESUPPLY = "refit_resupply"
    AMBUSH = "ambush"


# Statuses that must retain commitment fields once set.
# blocked/cancelled use both-or-neither (may reject a draft with no lock).
_COMMITMENT_RETAINING_STATUSES = frozenset(
    {
        MoveOrderStatus.COMMITTED.value,
        MoveOrderStatus.ACTIVE.value,
        MoveOrderStatus.COMPLETED.value,
    }
)

PROGRESS_MILLI_MIN = 0
PROGRESS_MILLI_MAX = 1000
# Fixed-point: 1000 == 1.0x cost / 1.0 base move point.
COST_MILLI_UNITY = 1000

APPROVED_CORRIDOR_COMMENT_ID = 5234226059
APPROVED_CORRIDOR_BATCH_ID = "earth3-p3-first-playable-corridors-v1"
APPROVED_CORRIDOR_ROLLBACK_BATCH_ID = "p3-batch-001"
APPROVED_CORRIDOR_SOURCE = "owner_approved_earth3_p3_corridor"
APPROVED_CORRIDOR_METADATA_KEYS = frozenset(
    {
        "approval_comment_id",
        "batch_id",
        "rollback_batch_id",
        "source",
        "supply_capable",
    }
)


def require_strict_int(value: Any, *, name: str, minimum: int | None = None, maximum: int | None = None) -> int:
    """Accept only real ints. Reject bool, str, float (including whole floats)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a strict int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


# Default edge costs as milli-multipliers (1000 = 1.0x).
DEFAULT_CROSSING_META_MILLI: dict[str, dict[str, Any]] = {
    EdgeKind.STRAIT.value: {
        "movement_cost_milli": 1250,
        "requires_port": False,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.FERRY.value: {
        "movement_cost_milli": 1500,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.FERRY_OR_SEA_LANE.value: {
        "movement_cost_milli": 1500,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.SEA_LANE.value: {
        "movement_cost_milli": 2000,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.CORRIDOR.value: {
        "movement_cost_milli": COST_MILLI_UNITY,
        "requires_port": False,
        "can_be_blockaded": False,
        "bidirectional": True,
    },
    EdgeKind.ROAD.value: {
        "movement_cost_milli": COST_MILLI_UNITY,
        "requires_port": False,
        "can_be_blockaded": False,
        "bidirectional": True,
    },
    EdgeKind.RAIL.value: {
        "movement_cost_milli": 750,
        "requires_port": False,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.MOUNTAIN_PASS.value: {
        "movement_cost_milli": 1750,
        "requires_port": False,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    EdgeKind.RIVER_CROSSING.value: {
        "movement_cost_milli": 1250,
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
    control_weight_milli: int = COST_MILLI_UNITY
    capture_threshold_milli: int = COST_MILLI_UNITY
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
        require_strict_int(self.pixel[0], name="site.pixel[0]", minimum=0)
        require_strict_int(self.pixel[1], name="site.pixel[1]", minimum=0)
        require_strict_int(self.control_weight_milli, name="control_weight_milli", minimum=1)
        require_strict_int(self.capture_threshold_milli, name="capture_threshold_milli", minimum=1)


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
        require_strict_int(self.pixel[0], name="node.pixel[0]", minimum=0)
        require_strict_int(self.pixel[1], name="node.pixel[1]", minimum=0)
        if self.kind == NodeKind.SITE.value and not self.site_id:
            raise ValueError(f"site node {self.node_id} requires site_id")
        if self.site_id and self.site_id not in site_ids:
            raise ValueError(f"node {self.node_id} site missing: {self.site_id}")
        if self.kind == NodeKind.ANCHOR.value and self.site_id:
            raise ValueError(f"anchor node {self.node_id} must not bind a site")


@dataclass(slots=True)
class OperationalRouteEdge:
    edge_id: str
    a: str
    b: str
    kind: str
    authority: str
    length_px: int = 1
    base_move_points_milli: int = COST_MILLI_UNITY
    movement_cost_milli: int = COST_MILLI_UNITY
    requires_port: bool = False
    can_be_blockaded: bool = False
    # Authored crossings are traversable in v1; port/blockade *enforcement* is deferred.
    traversal_enabled: bool = True
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
        require_strict_int(self.length_px, name="length_px", minimum=1)
        require_strict_int(
            self.base_move_points_milli, name="base_move_points_milli", minimum=1
        )
        require_strict_int(self.movement_cost_milli, name="movement_cost_milli", minimum=1)
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
        if self.authority == EdgeAuthority.AUTHORED.value and self.kind == EdgeKind.CORRIDOR.value:
            raise ValueError(f"authored edge {self.edge_id} cannot be corridor")
        if self.authority == EdgeAuthority.CANDIDATE.value and self.kind in {
            EdgeKind.ROAD.value,
            EdgeKind.RAIL.value,
        }:
            raise ValueError(f"candidate edge {self.edge_id} cannot claim road/rail")
        if (
            self.authority == EdgeAuthority.CANDIDATE.value
            and self.kind != EdgeKind.CORRIDOR.value
        ):
            raise ValueError(f"candidate edge {self.edge_id} must be corridor in S1")
        if self.authority == EdgeAuthority.CANDIDATE.value and self.traversal_enabled:
            raise ValueError(
                f"candidate edge {self.edge_id} must have traversal_enabled=false "
                "until explicitly authored or approved"
            )
        if self.authority == EdgeAuthority.APPROVED.value:
            valid_approved_policy = all(
                (
                    self.kind == EdgeKind.CORRIDOR.value,
                    self.edge_id == stable_edge_id(EdgeKind.CORRIDOR.value, self.a, self.b),
                    self.base_move_points_milli == COST_MILLI_UNITY,
                    self.movement_cost_milli == COST_MILLI_UNITY,
                    self.requires_port is False,
                    self.can_be_blockaded is False,
                    self.traversal_enabled is True,
                    self.bidirectional is True,
                    self.legacy_crossing_type is None,
                    set(self.metadata) == APPROVED_CORRIDOR_METADATA_KEYS,
                    isinstance(self.metadata.get("approval_comment_id"), int)
                    and not isinstance(self.metadata.get("approval_comment_id"), bool),
                    self.metadata.get("approval_comment_id")
                    == APPROVED_CORRIDOR_COMMENT_ID,
                    self.metadata.get("batch_id") == APPROVED_CORRIDOR_BATCH_ID,
                    self.metadata.get("rollback_batch_id")
                    == APPROVED_CORRIDOR_ROLLBACK_BATCH_ID,
                    self.metadata.get("source") == APPROVED_CORRIDOR_SOURCE,
                    self.metadata.get("supply_capable") is True,
                )
            )
            if not valid_approved_policy:
                raise ValueError(
                    f"approved edge {self.edge_id} does not match the exact owner-approved "
                    "corridor policy"
                )
        if self.authority == EdgeAuthority.AUTHORED.value and self.kind not in {
            EdgeKind.STRAIT.value,
            EdgeKind.FERRY.value,
            EdgeKind.FERRY_OR_SEA_LANE.value,
            EdgeKind.SEA_LANE.value,
        }:
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
        progress = require_strict_int(
            self.progress_milli,
            name="progress_milli",
            minimum=PROGRESS_MILLI_MIN,
            maximum=PROGRESS_MILLI_MAX,
        )
        if self.mode == PositionMode.AT_NODE.value:
            if not self.node_id or self.node_id not in node_ids:
                raise ValueError("at_node position requires valid node_id")
            if self.edge_id is not None:
                raise ValueError("at_node position must not set edge_id")
            if progress != 0:
                raise ValueError("at_node progress_milli must be 0")
            if self.facing_node_id is not None:
                raise ValueError("at_node position must not set facing_node_id")
        elif self.mode == PositionMode.ON_EDGE.value:
            if not self.edge_id or self.edge_id not in edge_ids:
                raise ValueError("on_edge position requires valid edge_id")
            if self.node_id is not None:
                raise ValueError("on_edge position must not set node_id")
            if not self.facing_node_id or self.facing_node_id not in node_ids:
                raise ValueError("on_edge requires valid facing_node_id")
            edge = edges_by_id[self.edge_id]
            if self.facing_node_id not in {edge.a, edge.b}:
                raise ValueError("facing_node_id must be an endpoint of edge_id")
        else:
            raise ValueError(f"invalid position mode {self.mode}")


@dataclass(slots=True)
class OperationalMoveOrder:
    """Weekly commitment model for formation movement (schema only in S1)."""

    order_id: str
    formation_id: str
    path_node_ids: list[str] = field(default_factory=list)
    path_edge_ids: list[str] = field(default_factory=list)
    destination_site_id: str | None = None
    issued_tick: int = 0
    status: str = MoveOrderStatus.DRAFT.value
    # Commitment lock (strategic turn / week).
    committed_turn: int | None = None
    locked_stance: str | None = None

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
        require_strict_int(self.issued_tick, name="issued_tick", minimum=0)
        if self.committed_turn is not None:
            require_strict_int(self.committed_turn, name="committed_turn", minimum=0)
        if self.locked_stance is not None:
            if self.locked_stance not in {item.value for item in FormationStance}:
                raise ValueError(
                    f"locked_stance must be one of "
                    f"{sorted(item.value for item in FormationStance)}, "
                    f"got {self.locked_stance!r}"
                )
        # Draft must not carry commitment fields.
        if self.status == MoveOrderStatus.DRAFT.value:
            if self.committed_turn is not None:
                raise ValueError("draft orders must not set committed_turn")
            if self.locked_stance is not None:
                raise ValueError("draft orders must not set locked_stance")
        # Once committed (or later lifecycle states), retain commitment info.
        if self.status in _COMMITMENT_RETAINING_STATUSES:
            if self.committed_turn is None:
                raise ValueError(
                    f"{self.status} orders require committed_turn"
                )
            if self.locked_stance is None:
                raise ValueError(
                    f"{self.status} orders require locked_stance"
                )
        # Cancelled/blocked: both commitment fields or neither (not a half-pair).
        if self.status in {
            MoveOrderStatus.CANCELLED.value,
            MoveOrderStatus.BLOCKED.value,
        }:
            has_turn = self.committed_turn is not None
            has_stance = self.locked_stance is not None
            if has_turn != has_stance:
                raise ValueError(
                    f"{self.status} orders require both committed_turn and locked_stance, "
                    "or neither"
                )
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
    # Authored crossings are part of v1 topology/traversal graph.
    # Port requirement and blockade effects are not enforced until later stages.
    authored_crossings_traversable_v1: bool = True
    enforce_port_requirements: bool = False
    enforce_blockades: bool = False

    def validate(self) -> None:
        require_strict_int(
            self.ticks_per_strategic_turn, name="ticks_per_strategic_turn", minimum=1
        )
        require_strict_int(self.capture_hold_ticks, name="capture_hold_ticks", minimum=1)
        require_strict_int(
            self.max_friendly_formations_per_node,
            name="max_friendly_formations_per_node",
            minimum=1,
        )


@dataclass(slots=True)
class OperationalGraph:
    map_id: str
    schema: str = "gates-of-codex.operational-graph"
    schema_version: int = 2
    rules: OperationalRules = field(default_factory=OperationalRules)
    sites: list[StrategicSite] = field(default_factory=list)
    nodes: list[OperationalRouteNode] = field(default_factory=list)
    edges: list[OperationalRouteEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, province_ids: Iterable[str]) -> None:
        """Validate graph. Must not mutate self.metadata or any nested records."""
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
        undirected: set[tuple[str, str, str]] = set()
        for edge in self.edges:
            key = (edge.kind, *sorted((edge.a, edge.b)))
            if key in undirected:
                raise ValueError(f"duplicate undirected edge for {key}")
            undirected.add(key)

    def to_dict(self) -> dict[str, Any]:
        # Never serialize transient validation helpers.
        metadata = {
            key: value
            for key, value in self.metadata.items()
            if not str(key).startswith("_")
        }
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "map_id": self.map_id,
            "rules": asdict(self.rules),
            "sites": [asdict(site) for site in sorted(self.sites, key=lambda item: item.site_id)],
            "nodes": [asdict(node) for node in sorted(self.nodes, key=lambda item: item.node_id)],
            "edges": [asdict(edge) for edge in sorted(self.edges, key=lambda item: item.edge_id)],
            "metadata": metadata,
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


def apply_default_meta_milli(kind: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(
        DEFAULT_CROSSING_META_MILLI.get(kind, DEFAULT_CROSSING_META_MILLI[EdgeKind.CORRIDOR.value])
    )
    if overrides:
        # Accept legacy float multiplier keys from theatre edge_meta and convert.
        if "movement_cost_milli" in overrides:
            base["movement_cost_milli"] = require_strict_int(
                overrides["movement_cost_milli"], name="movement_cost_milli", minimum=1
            )
        elif "movement_cost_multiplier" in overrides:
            mult = overrides["movement_cost_multiplier"]
            if isinstance(mult, bool) or not isinstance(mult, (int, float)):
                raise ValueError("movement_cost_multiplier must be numeric")
            base["movement_cost_milli"] = max(1, int(round(float(mult) * COST_MILLI_UNITY)))
        for key in ("requires_port", "can_be_blockaded", "bidirectional"):
            if key in overrides:
                base[key] = bool(overrides[key])
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
