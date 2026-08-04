from __future__ import annotations

from collections import Counter
from pathlib import Path

from .europe import load_goe_europe_graph
from .map_layout import load_marker_layout
from .strategic_map import (
    GraphMappingResult,
    import_strategic_map,
    resolve_graph_mapping,
)


RGB = tuple[int, int, int]


def build_goe_source_nodes() -> dict[str, dict]:
    original_rows = [dict(row) for row in load_marker_layout()["provinces"]]
    rows = [dict(row) for row in original_rows]
    id_counts = Counter(str(row.get("id", "")) for row in original_rows)
    node_rows: dict[str, dict] = {}
    node_keys: list[str] = []
    for row in rows:
        original_id = str(row.get("id", "")).strip()
        if not original_id:
            raise ValueError("GoE marker row has no textual ID")
        color = _rgb(row["id_color"])
        node_key = (
            original_id
            if id_counts[original_id] == 1
            else f"{original_id}#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
        )
        if node_key in node_rows:
            raise ValueError(f"GoE marker row key still collides: {node_key}")
        row["source_province_id"] = original_id
        row["source_node_key"] = node_key
        row["neighbors"] = []
        node_rows[node_key] = row
        node_keys.append(node_key)

    for left_index, left_key in enumerate(node_keys):
        left_original = original_rows[left_index]
        left_id = str(left_original["id"])
        left_tokens = {str(value) for value in left_original.get("neighbors", [])}
        left_id_is_duplicate = id_counts[left_id] > 1
        for right_index in range(left_index + 1, len(node_keys)):
            right_key = node_keys[right_index]
            right_original = original_rows[right_index]
            right_id = str(right_original["id"])
            right_tokens = {str(value) for value in right_original.get("neighbors", [])}
            right_id_is_duplicate = id_counts[right_id] > 1
            left_mentions_right = right_id in left_tokens
            right_mentions_left = left_id in right_tokens

            is_edge = left_mentions_right and right_mentions_left
            if not is_edge and not left_id_is_duplicate and not right_id_is_duplicate:
                is_edge = left_mentions_right or right_mentions_left
            elif not is_edge and left_id_is_duplicate and not right_id_is_duplicate:
                is_edge = left_mentions_right
            elif not is_edge and right_id_is_duplicate and not left_id_is_duplicate:
                is_edge = right_mentions_left
            if is_edge:
                node_rows[left_key]["neighbors"].append(right_key)
                node_rows[right_key]["neighbors"].append(left_key)

    for row in node_rows.values():
        row["neighbors"].sort()
    if len(node_rows) != 517:
        raise ValueError(f"Expected 517 distinct GoE RGB nodes, found {len(node_rows)}")
    return node_rows


def resolve_goe_graph_mapping() -> GraphMappingResult:
    graph = load_goe_europe_graph()["provinces"]
    return resolve_graph_mapping(graph, build_goe_source_nodes())


def build_interim_goe_province_table() -> list[dict]:
    graph = load_goe_europe_graph()["provinces"]
    source = build_goe_source_nodes()
    result = resolve_graph_mapping(graph, source)
    table: list[dict] = []
    colors: set[RGB] = set()
    for province_id in sorted(graph):
        source_key = result.graph_to_source[province_id]
        marker = source[source_key]
        color = _rgb(marker["id_color"])
        if color in colors:
            raise ValueError(f"Duplicate GoE source RGB {color}")
        colors.add(color)
        table.append({
            "province_id": province_id,
            "display_name": graph[province_id].get("display_name", province_id),
            "rgb": list(color),
            "source_province_id": marker["source_province_id"],
            "source_node_key": source_key,
            "mapping_method": result.methods[province_id],
            "marker_anchor": [float(marker["x"]), float(marker["y"])],
            "marker_map_region": marker.get("map_region"),
        })
    if len(table) != 517 or len(colors) != 517:
        raise ValueError("Interim GoE table must contain 517 provinces and colors")
    return table


def write_interim_goe_province_table(path: str | Path) -> Path:
    import json

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "gates-of-codex.province-table",
        "schema_version": 1,
        "map_id": "goe_europe",
        "provenance": "interim_goe_reference_asset",
        "provinces": build_interim_goe_province_table(),
    }
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def import_interim_goe_map(
    id_map: str | Path,
    output: str | Path,
    *,
    texture_output: str | Path | None = None,
    ignored_colors: tuple[RGB, ...] | list[RGB] = ((0, 0, 0),),
) -> dict:
    return import_strategic_map(
        id_map,
        build_interim_goe_province_table(),
        output,
        map_id="goe_europe",
        provenance="interim_goe_reference_asset",
        ignored_colors=ignored_colors,
        expected_graph=load_goe_europe_graph()["provinces"],
        texture_output=texture_output,
    )


def duplicate_marker_ids() -> dict[str, list[dict]]:
    rows = load_marker_layout()["provinces"]
    counts = Counter(str(row.get("id", "")) for row in rows)
    return {
        province_id: [
            {
                "rgb": list(_rgb(row["id_color"])),
                "display_name": row.get("display_name", ""),
                "x": row.get("x"),
                "y": row.get("y"),
                "neighbors": list(row.get("neighbors", [])),
            }
            for row in rows
            if str(row.get("id", "")) == province_id
        ]
        for province_id, count in sorted(counts.items())
        if count > 1
    }


def degree_distributions() -> dict[str, dict[int, int]]:
    graph = load_goe_europe_graph()["provinces"]
    source = build_goe_source_nodes()
    return {
        "graph": dict(sorted(Counter(len(row.get("neighbors", [])) for row in graph.values()).items())),
        "source": dict(sorted(Counter(len(row.get("neighbors", [])) for row in source.values()).items())),
    }


def _rgb(value: dict) -> RGB:
    return int(value["r"]), int(value["g"]), int(value["b"])
