from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .operational_schema import (
    EdgeAuthority,
    EdgeKind,
    NodeKind,
    OperationalGraph,
    OperationalRouteEdge,
    OperationalRouteNode,
    OperationalRules,
    apply_default_meta,
    crossing_type_to_edge_kind,
    stable_edge_id,
    stable_node_id,
)
from .strategic_map import decode_png_rgb


DEFAULT_EM_MANIFEST = Path("godot/assets/maps/europe_mediterranean/from_goe/map_manifest.json")
DEFAULT_EM_ID_MAP = Path("godot/assets/maps/europe_mediterranean/from_goe/province_id_map.png")
DEFAULT_OUTPUT_DIR = Path("godot/assets/maps/europe_mediterranean/from_goe/operational")


def generate_em_operational_graph(
    *,
    manifest_path: str | Path = DEFAULT_EM_MANIFEST,
    id_map_path: str | Path | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Build S1 operational graph assets for the frozen EM theatre.

    No movement/capture/AI behavior — data + validation only.
    """

    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if str(manifest.get("map_id")) != "europe_mediterranean_from_goe":
        raise ValueError(f"expected europe_mediterranean_from_goe, got {manifest.get('map_id')}")

    texture = manifest.get("id_texture") or {}
    width = int(texture.get("width", 0))
    height = int(texture.get("height", 0))
    texture_path = Path(id_map_path) if id_map_path else manifest_file.parent / str(texture.get("path", "province_id_map.png"))
    image = decode_png_rgb(texture_path)
    if image.width != width or image.height != height:
        raise ValueError("id map dimensions do not match manifest")

    color_to_pid = {
        tuple(int(c) for c in row["rgb"]): str(row["province_id"])
        for row in manifest.get("province_table", [])
    }
    rows = list(manifest.get("province_table", []))
    province_ids = sorted(str(row["province_id"]) for row in rows)
    if len(province_ids) != 342:
        # Soft check — still valid if theatre size changes later, but S1 locks 342.
        pass

    nodes: list[OperationalRouteNode] = []
    for row in sorted(rows, key=lambda item: str(item["province_id"])):
        pid = str(row["province_id"])
        pixel = _resolve_anchor_pixel(row, image, color_to_pid, width, height)
        node = OperationalRouteNode(
            node_id=stable_node_id(pid, "anchor"),
            display_name=f"{row.get('display_name', pid)} anchor",
            kind=NodeKind.ANCHOR.value,
            pixel=[int(pixel[0]), int(pixel[1])],
            province_id=pid,
            site_id=None,
            terrain="unknown",
            is_hub=False,
            authority=EdgeAuthority.AUTHORED.value,
            metadata={
                "role": "province_migration_anchor",
                "source_marker_anchor": list(row.get("marker_anchor") or []),
            },
        )
        nodes.append(node)

    node_by_province = {node.province_id: node for node in nodes}
    edges: list[OperationalRouteEdge] = []

    # Generic land adjacency -> corridor candidates (not invented roads).
    seen_undirected: set[tuple[str, str]] = set()
    for row in rows:
        pid = str(row["province_id"])
        for neighbor in row.get("land_neighbors") or []:
            nid = str(neighbor)
            if nid not in node_by_province:
                continue
            key = tuple(sorted((pid, nid)))
            if key in seen_undirected:
                continue
            seen_undirected.add(key)
            a = node_by_province[key[0]]
            b = node_by_province[key[1]]
            kind = EdgeKind.CORRIDOR.value
            meta = apply_default_meta(kind)
            length = _pixel_distance(a.pixel, b.pixel)
            edges.append(
                OperationalRouteEdge(
                    edge_id=stable_edge_id(kind, a.node_id, b.node_id),
                    a=a.node_id,
                    b=b.node_id,
                    kind=kind,
                    authority=EdgeAuthority.CANDIDATE.value,
                    length_px=length,
                    base_move_points=1.0,
                    movement_cost_multiplier=float(meta["movement_cost_multiplier"]),
                    requires_port=bool(meta["requires_port"]),
                    can_be_blockaded=bool(meta["can_be_blockaded"]),
                    bidirectional=bool(meta["bidirectional"]),
                    province_ids=[key[0], key[1]],
                    legacy_crossing_type=None,
                    metadata={"source": "land_adjacency"},
                )
            )

    # Authored crossings from province edge_types / edge_meta (authoritative).
    authored_pairs: set[tuple[str, str]] = set()
    for row in rows:
        pid = str(row["province_id"])
        edge_types = row.get("edge_types") or {}
        edge_meta = row.get("edge_meta") or {}
        for neighbor, etype in edge_types.items():
            nid = str(neighbor)
            if str(etype) == "land":
                continue
            if nid not in node_by_province or pid not in node_by_province:
                continue
            pair = tuple(sorted((pid, nid)))
            if pair in authored_pairs:
                continue
            authored_pairs.add(pair)
            kind = crossing_type_to_edge_kind(str(etype))
            overrides = edge_meta.get(nid) if isinstance(edge_meta, dict) else None
            if not isinstance(overrides, dict):
                # edge_meta may be keyed only on one side; try reverse later via pair canonical.
                overrides = None
            # Prefer meta from either endpoint if present.
            if overrides is None:
                other_row = next((r for r in rows if str(r["province_id"]) == nid), None)
                if other_row is not None:
                    other_meta = (other_row.get("edge_meta") or {}).get(pid)
                    if isinstance(other_meta, dict):
                        overrides = other_meta
            meta = apply_default_meta(kind, overrides)
            a = node_by_province[pair[0]]
            b = node_by_province[pair[1]]
            # Remove candidate corridor between same endpoints if present.
            edges = [
                edge
                for edge in edges
                if not (
                    edge.kind == EdgeKind.CORRIDOR.value
                    and set((edge.a, edge.b)) == {a.node_id, b.node_id}
                )
            ]
            edges.append(
                OperationalRouteEdge(
                    edge_id=stable_edge_id(kind, a.node_id, b.node_id),
                    a=a.node_id,
                    b=b.node_id,
                    kind=kind,
                    authority=EdgeAuthority.AUTHORED.value,
                    length_px=_pixel_distance(a.pixel, b.pixel),
                    base_move_points=1.0,
                    movement_cost_multiplier=float(meta["movement_cost_multiplier"]),
                    requires_port=bool(meta["requires_port"]),
                    can_be_blockaded=bool(meta["can_be_blockaded"]),
                    bidirectional=bool(meta["bidirectional"]),
                    province_ids=[pair[0], pair[1]],
                    legacy_crossing_type=str(etype),
                    metadata={"source": "authored_crossing"},
                )
            )

    graph = OperationalGraph(
        map_id="europe_mediterranean_from_goe",
        rules=OperationalRules(
            ticks_per_strategic_turn=10,
            capture_hold_ticks=2,
            max_friendly_formations_per_node=3,
            capture_mode="control_site_node_only",
            interception_mode="swept_movement",
            formation_is_movement_authority=True,
        ),
        sites=[],  # S1: no invented settlements/ports/airfields
        nodes=nodes,
        edges=edges,
        metadata={
            "generator": "operational_em_generate_s1",
            "frame": {"width": width, "height": height},
            "province_count": len(province_ids),
            "notes": [
                "No invented settlements, ports, roads, or railways.",
                "Land adjacency exported as corridor candidates only.",
                "Authored crossings are authoritative typed edges.",
                "S1 does not change formation movement or ownership.",
            ],
        },
    )
    graph.validate(province_ids=province_ids)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = graph.to_dict()
    graph_path = out / "operational_graph.json"
    graph_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Compact indexes for loaders/tests.
    index = {
        "map_id": payload["map_id"],
        "schema_version": payload["schema_version"],
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["edges"]),
        "site_count": len(payload["sites"]),
        "authored_edge_count": sum(1 for e in payload["edges"] if e["authority"] == "authored"),
        "candidate_edge_count": sum(1 for e in payload["edges"] if e["authority"] == "candidate"),
        "rules": payload["rules"],
        "graph_path": "operational_graph.json",
    }
    (out / "operational_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "README.md").write_text(
        "\n".join(
            [
                "# Operational graph (S1)",
                "",
                "Schema-only operational route data for Europe-Mediterranean.",
                "",
                "- `operational_graph.json` — nodes, edges, rules",
                "- `operational_index.json` — counts and paths",
                "",
                "No movement, capture, interception, or AI behavior in S1.",
                "Candidate corridors are not gameplay-authoritative.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "output_dir": str(out),
        "graph_path": str(graph_path),
        "index": index,
        "graph": payload,
    }


def _resolve_anchor_pixel(
    row: dict,
    image,
    color_to_pid: dict[tuple[int, int, int], str],
    width: int,
    height: int,
) -> tuple[int, int]:
    pid = str(row["province_id"])
    rgb = tuple(int(c) for c in row["rgb"])
    anchor = row.get("marker_anchor") or [0, 0]
    ax = int(round(float(anchor[0])))
    # EM theatre stores bottom-left Y.
    ay_bl = int(round(float(anchor[1])))
    x = max(0, min(width - 1, ax))
    y = max(0, min(height - 1, height - 1 - ay_bl))
    if color_to_pid.get(image.color_at(x, y)) == pid:
        return x, y
    # Snap to nearest pixel of this province.
    best = None
    best_d = None
    # Bounded search first around anchor, then full scan if needed.
    for radius in (8, 24, 64, max(width, height)):
        x0 = max(0, x - radius)
        x1 = min(width - 1, x + radius)
        y0 = max(0, y - radius)
        y1 = min(height - 1, y + radius)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if color_to_pid.get(image.color_at(px, py)) != pid:
                    continue
                d = (px - x) * (px - x) + (py - y) * (py - y)
                if best_d is None or d < best_d:
                    best_d = d
                    best = (px, py)
        if best is not None:
            return best
    raise RuntimeError(f"no pixels for province {pid}")


def _pixel_distance(a: list[int], b: list[int]) -> float:
    dx = float(a[0] - b[0])
    dy = float(a[1] - b[1])
    return max((dx * dx + dy * dy) ** 0.5, 1.0)
