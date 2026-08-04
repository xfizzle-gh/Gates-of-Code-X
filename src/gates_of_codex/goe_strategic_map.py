from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .europe import load_goe_europe_graph
from .map_layout import load_marker_layout
from .strategic_map import import_strategic_map


RGB = tuple[int, int, int]
Edge = tuple[str, str]


@dataclass(frozen=True, slots=True)
class GoEGraphAlignment:
    graph_to_source: dict[str, str]
    methods: dict[str, str]
    source_index_offset: int
    seed_count: int
    missing_campaign_edges: tuple[Edge, ...]
    extra_source_edges: tuple[Edge, ...]
    verified: bool

    def to_dict(self) -> dict:
        return {
            "graph_to_source": dict(sorted(self.graph_to_source.items())),
            "methods": dict(sorted(self.methods.items())),
            "source_index_offset": self.source_index_offset,
            "seed_count": self.seed_count,
            "missing_campaign_edges": [list(edge) for edge in self.missing_campaign_edges],
            "extra_source_edges": [list(edge) for edge in self.extra_source_edges],
            "verified": self.verified,
            "method_counts": dict(sorted(Counter(self.methods.values()).items())),
        }


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
        node_key = _source_key(row, id_counts)
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


def resolve_goe_graph_mapping() -> GoEGraphAlignment:
    graph = load_goe_europe_graph()["provinces"]
    marker_rows = [dict(row) for row in load_marker_layout()["provinces"]]
    source = build_goe_source_nodes()
    id_counts = Counter(str(row.get("id", "")) for row in marker_rows)
    graph_edges = _edges(graph)
    source_edges = _edges(source)
    candidates: list[GoEGraphAlignment] = []

    for offset in (0, 1):
        mapping: dict[str, str] = {}
        methods: dict[str, str] = {}
        used: set[str] = set()
        valid = True
        seed_count = 0
        for graph_id, graph_row in graph.items():
            synthetic = re.fullmatch(r"province_(\d+)", graph_id)
            marker_row: dict | None = None
            method = ""
            if synthetic:
                marker_index = int(synthetic.group(1)) - offset
                if 0 <= marker_index < len(marker_rows):
                    marker_row = marker_rows[marker_index]
                    method = f"preserved_source_index_{offset}"
            else:
                graph_name = str(graph_row.get("display_name", graph_id))
                matches = [
                    row
                    for row in marker_rows
                    if str(row.get("id", "")) == graph_id
                    or str(row.get("display_name", "")) == graph_name
                ]
                if len(matches) == 1:
                    marker_row = matches[0]
                    method = "exact_text_id"
                    seed_count += 1
            if marker_row is None:
                valid = False
                break
            source_key = _source_key(marker_row, id_counts)
            if source_key not in source or source_key in used:
                valid = False
                break
            mapping[graph_id] = source_key
            methods[graph_id] = method
            used.add(source_key)

        if not valid or len(mapping) != len(graph) or len(used) != len(source):
            continue
        mapped_graph_edges = {
            tuple(sorted((mapping[left], mapping[right])))
            for left, right in graph_edges
        }
        missing = tuple(sorted(mapped_graph_edges - source_edges))
        extra = tuple(sorted(source_edges - mapped_graph_edges))
        candidates.append(
            GoEGraphAlignment(
                graph_to_source=dict(sorted(mapping.items())),
                methods=dict(sorted(methods.items())),
                source_index_offset=offset,
                seed_count=seed_count,
                missing_campaign_edges=missing,
                extra_source_edges=extra,
                verified=not missing,
            )
        )

    if not candidates:
        raise ValueError("Could not construct a complete GoE source-index alignment")
    selected = min(
        candidates,
        key=lambda value: (
            len(value.missing_campaign_edges),
            len(value.extra_source_edges),
            value.source_index_offset,
        ),
    )
    if not selected.verified:
        raise ValueError(
            "GoE source-index alignment omits campaign graph edges: "
            f"{len(selected.missing_campaign_edges)}"
        )
    return selected


def build_aligned_source_graph(
    alignment: GoEGraphAlignment | None = None,
) -> dict[str, dict]:
    resolved = alignment or resolve_goe_graph_mapping()
    source = build_goe_source_nodes()
    reverse = {source_id: graph_id for graph_id, source_id in resolved.graph_to_source.items()}
    graph: dict[str, dict] = {}
    for graph_id, source_id in resolved.graph_to_source.items():
        graph[graph_id] = {
            "neighbors": sorted(reverse[neighbor] for neighbor in source[source_id]["neighbors"]),
        }
    return graph


def build_interim_goe_province_table() -> list[dict]:
    graph = load_goe_europe_graph()["provinces"]
    source = build_goe_source_nodes()
    alignment = resolve_goe_graph_mapping()
    reverse = {source_id: graph_id for graph_id, source_id in alignment.graph_to_source.items()}
    table: list[dict] = []
    colors: set[RGB] = set()
    for province_id in sorted(graph):
        source_key = alignment.graph_to_source[province_id]
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
            "mapping_method": alignment.methods[province_id],
            "source_index_offset": alignment.source_index_offset,
            "source_neighbors": sorted(reverse[neighbor] for neighbor in marker["neighbors"]),
            "marker_anchor": [float(marker["x"]), float(marker["y"])],
            "marker_map_region": marker.get("map_region"),
        })
    if len(table) != 517 or len(colors) != 517:
        raise ValueError("Interim GoE table must contain 517 provinces and colors")
    return table


def write_interim_goe_province_table(path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    alignment = resolve_goe_graph_mapping()
    payload = {
        "schema": "gates-of-codex.province-table",
        "schema_version": 1,
        "map_id": "goe_europe",
        "provenance": "interim_goe_reference_asset",
        "alignment": alignment.to_dict(),
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
    alignment = resolve_goe_graph_mapping()
    manifest = import_strategic_map(
        id_map,
        build_interim_goe_province_table(),
        output,
        map_id="goe_europe",
        provenance="interim_goe_reference_asset",
        ignored_colors=ignored_colors,
        expected_graph=build_aligned_source_graph(alignment),
        texture_output=texture_output,
    )
    manifest["source_alignment"] = alignment.to_dict()
    Path(output).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


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


def _source_key(row: dict, counts: Counter[str]) -> str:
    original_id = str(row.get("id", "")).strip()
    if counts[original_id] == 1:
        return original_id
    color = _rgb(row["id_color"])
    return f"{original_id}#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def _edges(rows: dict[str, dict]) -> set[Edge]:
    return {
        tuple(sorted((node_id, str(neighbor))))
        for node_id, row in rows.items()
        for neighbor in row.get("neighbors", [])
        if str(neighbor) in rows and str(neighbor) != node_id
    }


def _rgb(value: dict) -> RGB:
    return int(value["r"]), int(value["g"]), int(value["b"])
