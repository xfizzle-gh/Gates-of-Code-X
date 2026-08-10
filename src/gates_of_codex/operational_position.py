from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import CampaignState, StrategicFormation
from .operational_schema import (
    FormationOperationalPosition,
    OperationalRouteEdge,
    PositionMode,
    require_strict_int,
    stable_node_id,
)

OPERATIONAL_POSITION_SCHEMA_VERSION = 7
MIGRATION_RECORD_KEY = "operational_position_migration"

# Relative to a strategic map asset root (sibling of map_manifest.json).
_DEFAULT_GRAPH_RELATIVE = "operational/operational_graph.json"

# map_id -> path under godot/ (frontend-style asset contract).
_GRAPH_UNDER_GODOT: dict[str, str] = {
    "europe_mediterranean_from_goe": (
        "assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
    ),
}


def province_anchor_position(province_id: str) -> FormationOperationalPosition:
    """M1 default when no higher-weight site node exists: province anchor node."""
    return FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value,
        node_id=stable_node_id(province_id, "anchor"),
        edge_id=None,
        progress_milli=0,
        facing_node_id=None,
    )


def position_to_dict(position: FormationOperationalPosition | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "mode": position.mode,
        "node_id": position.node_id,
        "edge_id": position.edge_id,
        "progress_milli": int(position.progress_milli),
        "facing_node_id": position.facing_node_id,
    }


def position_from_dict(raw: Any) -> FormationOperationalPosition | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("position must be an object or null")
    if not raw:
        return None
    progress_raw = raw.get("progress_milli", 0)
    progress_milli = require_strict_int(progress_raw, name="progress_milli", minimum=0, maximum=1000)
    return FormationOperationalPosition(
        mode=str(raw.get("mode", PositionMode.AT_NODE.value)),
        node_id=None if raw.get("node_id") in (None, "") else str(raw.get("node_id")),
        edge_id=None if raw.get("edge_id") in (None, "") else str(raw.get("edge_id")),
        progress_milli=progress_milli,
        facing_node_id=(
            None if raw.get("facing_node_id") in (None, "") else str(raw.get("facing_node_id"))
        ),
    )


def place_formation_at_province_anchor(
    force: StrategicFormation,
    state: CampaignState | None = None,
) -> FormationOperationalPosition | None:
    """Snap formation to province migration anchor when an operational graph is available.

    If the graph cannot be resolved, leave ``force.position`` completely unchanged
    (temporary path/packaging failures must not erase saved positions).
    """
    if state is not None and load_operational_graph_for_state(state) is None:
        return force.position
    position = province_anchor_position(force.province_id)
    force.position = position
    return position


def ensure_operational_positions(state: CampaignState) -> dict:
    """Hydrate missing/invalid operational positions (S2 / M1).

    Only when an operational graph file is successfully loaded:
    - missing/invalid positions are placed (M1)
    - campaign schema may bump to 7
    - migration metadata may be written

    If the graph cannot be resolved, leave formation positions, schema_version,
    and map_metadata completely unchanged.
    """
    from .force_migration import ensure_strategic_formations

    ensure_strategic_formations(state)
    incoming_schema = int(state.schema_version)
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return {
            "schema_version": incoming_schema,
            "map_id": state.map_id,
            "graph_loaded": False,
            "skipped": True,
            "note": "Operational graph unresolved; existing positions left unchanged.",
        }

    node_ids, edge_ids, edges_by_id, nodes_by_id = _graph_indexes(graph)
    hydrated = 0
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if _position_is_valid(
            force.position,
            province_id=force.province_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
            edges_by_id=edges_by_id,
            nodes_by_id=nodes_by_id,
        ):
            continue
        force.position = _migration_position_for_province(
            force.province_id,
            graph=graph,
            nodes_by_id=nodes_by_id,
        )
        hydrated += 1

    state.schema_version = max(state.schema_version, OPERATIONAL_POSITION_SCHEMA_VERSION)
    if MIGRATION_RECORD_KEY not in state.map_metadata:
        state.map_metadata[MIGRATION_RECORD_KEY] = _stable_migration_record(
            incoming_schema, map_id=state.map_id, graph_loaded=True
        )
    record = state.map_metadata[MIGRATION_RECORD_KEY]
    if "hydrated_on_first_pass" not in record:
        record["hydrated_on_first_pass"] = hydrated
    return record


def resolve_display_pixel(
    state: CampaignState,
    force: StrategicFormation,
) -> list[int] | None:
    """Pixel for UI draw: node/edge lerp when graph known, else province marker."""
    graph = load_operational_graph_for_state(state)
    if force.position is not None and graph is not None:
        pixel = _pixel_from_position(force.position, graph)
        if pixel is not None:
            return pixel
    province = state.provinces.get(force.province_id)
    if province is None:
        return None
    return [int(round(province.x)), int(round(province.y))]


def load_operational_graph_for_state(state: CampaignState) -> dict[str, Any] | None:
    """Resolve operational graph via map metadata / asset contract (not package path)."""
    from .earth3_operational import (
        EARTH3_MAP_ID,
        P3_AUTHORITY_METADATA_KEY,
        Earth3OperationalAuthorityError,
        load_authenticated_p3_graph_for_state,
    )

    map_metadata = state.map_metadata
    map_id = getattr(state, "map_id", None)
    if P3_AUTHORITY_METADATA_KEY in map_metadata:
        if map_id != EARTH3_MAP_ID:
            raise Earth3OperationalAuthorityError(
                "Earth3 P3 state authority marker requires the exact Earth3 map identity"
            )
        return load_authenticated_p3_graph_for_state(state)
    if map_id == EARTH3_MAP_ID:
        return load_authenticated_p3_graph_for_state(state)
    return load_operational_graph_payload(
        map_id=str(map_id),
        map_metadata=state.map_metadata,
    )


def default_asset_search_roots() -> list[Path]:
    """Automatic roots for installed package / Windows executable / frozen builds.

    Production callers should not need to pass ``search_roots``; cwd alone is not enough
    when the process is launched from another directory.
    """
    roots: list[Path] = []

    def _add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved not in roots:
            roots.append(resolved)

    # PyInstaller one-file extract dir / frozen resource root.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        _add(Path(str(meipass)))

    # Executable directory (Windows .exe, PyInstaller one-dir, python.exe in venv).
    try:
        exe = Path(sys.executable).resolve()
        _add(exe.parent)
        _add(exe.parent / "_internal")
        _add(exe.parent / "godot")
    except OSError:
        pass

    # argv[0] may differ from sys.executable for wrapped launchers.
    if sys.argv:
        try:
            argv0 = Path(sys.argv[0]).expanduser()
            if argv0.is_file():
                _add(argv0.resolve().parent)
                _add(argv0.resolve().parent / "godot")
        except OSError:
            pass

    # Installed / editable package locations.
    try:
        import gates_of_codex as _pkg

        pkg_dir = Path(_pkg.__file__).resolve().parent
        _add(pkg_dir)
        if pkg_dir.parent.name == "src":
            _add(pkg_dir.parents[1])  # repo root
        else:
            _add(pkg_dir.parent)
    except Exception:
        pass

    _add(Path.cwd())
    return roots


def load_operational_graph_payload(
    map_id: str,
    *,
    map_metadata: dict[str, Any] | None = None,
    search_roots: list[Path] | None = None,
) -> dict[str, Any] | None:
    """Load operational graph JSON if a matching asset file is found.

    Resolution order (per root):
    1. Absolute/relative path in map_metadata['operational_graph']
    2. Sibling of strategic_map_manifest: operational/operational_graph.json
    3. Known map_id under godot/assets/...

    Default roots: executable dir, frozen ``_MEIPASS``, package/repo layout, cwd.
    """
    meta = dict(map_metadata or {})
    if search_roots is None:
        roots = default_asset_search_roots()
    else:
        roots = list(search_roots)
        # Always include automatic roots after explicit ones.
        for root in default_asset_search_roots():
            if root not in roots:
                roots.append(root)

    for candidate in _graph_candidate_paths(map_id=map_id, map_metadata=meta, roots=roots):
        try:
            path = candidate.resolve()
        except OSError:
            continue
        if path.is_file():
            return _read_graph_json(str(path))
    return None


def _graph_candidate_paths(
    *,
    map_id: str,
    map_metadata: dict[str, Any],
    roots: list[Path],
) -> list[Path]:
    candidates: list[Path] = []
    configured = str(map_metadata.get("operational_graph", "") or "").strip()
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_absolute():
            candidates.append(configured_path)
        else:
            for root in roots:
                candidates.append(root / configured_path)
                candidates.append(root / "godot" / configured_path)
                # assets/... form used in campaign metadata
                if configured_path.parts and configured_path.parts[0] != "godot":
                    candidates.append(root / "godot" / configured_path)

    manifest = str(map_metadata.get("strategic_map_manifest", "") or "").strip()
    if manifest:
        manifest_path = Path(manifest).expanduser()
        manifest_candidates: list[Path] = []
        if manifest_path.is_absolute():
            manifest_candidates.append(manifest_path)
        else:
            for root in roots:
                manifest_candidates.append(root / manifest_path)
                manifest_candidates.append(root / "godot" / manifest_path)
                if manifest_path.parts and manifest_path.parts[0] != "godot":
                    manifest_candidates.append(root / "godot" / manifest_path)
        for mpath in manifest_candidates:
            parent = mpath.parent if mpath.suffix else mpath
            candidates.append(parent / _DEFAULT_GRAPH_RELATIVE)

    relative = _GRAPH_UNDER_GODOT.get(str(map_id))
    if relative:
        for root in roots:
            candidates.append(root / "godot" / relative)
            candidates.append(root / relative)

    return candidates


@lru_cache(maxsize=8)
def _read_graph_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        for edge in payload.get("edges") or []:
            if isinstance(edge, dict) and edge.get("authority") == "approved":
                raise ValueError(
                    "approved edges require the authenticated Earth3 P3 loader"
                )
    return payload


def clear_operational_graph_cache() -> None:
    """Drop cached graph payloads (tests rewriting graph files on disk)."""
    _read_graph_json.cache_clear()


def _stable_migration_record(incoming_schema: int, *, map_id: str, graph_loaded: bool) -> dict:
    return {
        "schema_version": OPERATIONAL_POSITION_SCHEMA_VERSION,
        "migrated_from_schema": min(incoming_schema, OPERATIONAL_POSITION_SCHEMA_VERSION),
        "map_id": map_id,
        "placement": "province_anchor_or_highest_weight_site",
        "graph_loaded": bool(graph_loaded),
        "note": "S2 M1: strategic formations placed on operational graph; province_id retained.",
    }


def _migration_position_for_province(
    province_id: str,
    *,
    graph: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> FormationOperationalPosition:
    site_node = _highest_weight_site_node(province_id, graph=graph, nodes_by_id=nodes_by_id)
    if site_node is not None:
        return FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=str(site_node["node_id"]),
            progress_milli=0,
        )
    return province_anchor_position(province_id)


def _highest_weight_site_node(
    province_id: str,
    *,
    graph: dict[str, Any] | None,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if graph is None:
        return None
    sites = [
        site
        for site in graph.get("sites") or []
        if str(site.get("province_id")) == province_id
    ]
    if not sites:
        return None

    def sort_key(site: dict[str, Any]) -> tuple:
        # S1 schema field is control_weight_milli (strict int). Ignore legacy aliases.
        weight = site.get("control_weight_milli", 0)
        try:
            weight_key = -int(weight)
        except (TypeError, ValueError):
            weight_key = 0
        return (weight_key, str(site.get("site_id", "")))

    best = sorted(sites, key=sort_key)[0]
    route_node_id = best.get("route_node_id")
    if route_node_id and str(route_node_id) in nodes_by_id:
        return nodes_by_id[str(route_node_id)]
    site_id = str(best.get("site_id", ""))
    candidates = [
        node
        for node in nodes_by_id.values()
        if str(node.get("province_id")) == province_id and str(node.get("site_id") or "") == site_id
    ]
    if candidates:
        return sorted(candidates, key=lambda node: str(node["node_id"]))[0]
    return None


def _position_is_valid(
    position: FormationOperationalPosition | None,
    *,
    province_id: str,
    node_ids: set[str],
    edge_ids: set[str],
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
) -> bool:
    if position is None:
        return False
    try:
        position.validate(node_ids=node_ids, edge_ids=edge_ids, edges_by_id=edges_by_id)
        if position.mode == PositionMode.AT_NODE.value:
            node = nodes_by_id.get(str(position.node_id))
            if node is None or str(node.get("province_id")) != province_id:
                return False
        if position.mode == PositionMode.ON_EDGE.value:
            edge = edges_by_id[str(position.edge_id)]
            provinces = {
                str(nodes_by_id.get(edge.a, {}).get("province_id", "")),
                str(nodes_by_id.get(edge.b, {}).get("province_id", "")),
            }
            if province_id not in provinces:
                return False
    except (TypeError, ValueError, KeyError):
        return False
    return True


def _graph_indexes(
    graph: dict[str, Any],
) -> tuple[
    set[str],
    set[str],
    dict[str, OperationalRouteEdge],
    dict[str, dict[str, Any]],
]:
    nodes_by_id = {str(node["node_id"]): node for node in graph.get("nodes") or []}
    node_ids = set(nodes_by_id)
    edges_by_id: dict[str, OperationalRouteEdge] = {}
    for edge in graph.get("edges") or []:
        edges_by_id[str(edge["edge_id"])] = OperationalRouteEdge(
            edge_id=str(edge["edge_id"]),
            a=str(edge["a"]),
            b=str(edge["b"]),
            kind=str(edge["kind"]),
            authority=str(edge["authority"]),
            length_px=int(edge["length_px"]),
            base_move_points_milli=int(edge["base_move_points_milli"]),
            movement_cost_milli=int(edge["movement_cost_milli"]),
            requires_port=bool(edge["requires_port"]),
            can_be_blockaded=bool(edge["can_be_blockaded"]),
            traversal_enabled=bool(edge["traversal_enabled"]),
            bidirectional=bool(edge["bidirectional"]),
            province_ids=list(edge.get("province_ids") or []),
            legacy_crossing_type=edge.get("legacy_crossing_type"),
            metadata=dict(edge.get("metadata") or {}),
        )
    return node_ids, set(edges_by_id), edges_by_id, nodes_by_id


def _pixel_from_position(
    position: FormationOperationalPosition,
    graph: dict[str, Any],
) -> list[int] | None:
    nodes = {str(node["node_id"]): node for node in graph.get("nodes") or []}
    if position.mode == PositionMode.AT_NODE.value:
        node = nodes.get(str(position.node_id))
        if node is None:
            return None
        pixel = node.get("pixel") or [0, 0]
        return [int(pixel[0]), int(pixel[1])]
    if position.mode == PositionMode.ON_EDGE.value:
        edges = {str(edge["edge_id"]): edge for edge in graph.get("edges") or []}
        edge = edges.get(str(position.edge_id))
        if edge is None:
            return None
        a = nodes.get(str(edge["a"]))
        b = nodes.get(str(edge["b"]))
        if a is None or b is None:
            return None
        facing = str(position.facing_node_id)
        if facing == str(edge["b"]):
            start, end = a, b
        elif facing == str(edge["a"]):
            start, end = b, a
        else:
            start, end = a, b
        t = max(0, min(1000, int(position.progress_milli))) / 1000.0
        sx, sy = start.get("pixel") or [0, 0]
        ex, ey = end.get("pixel") or [0, 0]
        return [int(round(sx + (ex - sx) * t)), int(round(sy + (ey - sy) * t))]
    return None
