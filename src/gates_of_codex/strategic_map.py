from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .europe import load_goe_europe_graph
from .map_layout import load_marker_layout


MAP_SCHEMA_VERSION = 1
RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class GraphMappingResult:
    graph_to_source: dict[str, str]
    methods: dict[str, str]
    seed_count: int
    verified: bool

    def to_dict(self) -> dict:
        return {
            "graph_to_source": dict(sorted(self.graph_to_source.items())),
            "methods": dict(sorted(self.methods.items())),
            "seed_count": self.seed_count,
            "verified": self.verified,
            "method_counts": dict(sorted(Counter(self.methods.values()).items())),
        }


@dataclass(frozen=True, slots=True)
class DecodedIdImage:
    width: int
    height: int
    pixels: tuple[RGB, ...]

    def color_at(self, x: int, y: int) -> RGB:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise IndexError((x, y))
        return self.pixels[y * self.width + x]


def resolve_goe_graph_mapping() -> GraphMappingResult:
    graph = load_goe_europe_graph()["provinces"]
    markers = load_marker_layout()["provinces"]
    source = {row["id"]: row for row in markers}
    return resolve_graph_mapping(graph, source)


def resolve_graph_mapping(graph_rows: dict[str, dict], source_rows: dict[str, dict]) -> GraphMappingResult:
    if len(graph_rows) != len(source_rows):
        raise ValueError(
            f"Graph/source node counts differ: {len(graph_rows)} != {len(source_rows)}"
        )
    graph_neighbors = _neighbor_sets(graph_rows)
    source_neighbors = _neighbor_sets(source_rows)
    if sorted(len(value) for value in graph_neighbors.values()) != sorted(
        len(value) for value in source_neighbors.values()
    ):
        raise ValueError("Graph/source degree distributions differ")

    mapping: dict[str, str] = {}
    methods: dict[str, str] = {}
    used: set[str] = set()
    source_names: dict[str, list[str]] = defaultdict(list)
    for source_id, row in source_rows.items():
        source_names[_normalized_name(row.get("display_name", source_id))].append(source_id)

    for graph_id in sorted(graph_rows):
        if graph_id in source_rows and graph_id not in used:
            mapping[graph_id] = graph_id
            methods[graph_id] = "exact_id"
            used.add(graph_id)
            continue
        name = _normalized_name(graph_rows[graph_id].get("display_name", graph_id))
        candidates = [value for value in source_names.get(name, []) if value not in used]
        if len(candidates) == 1:
            mapping[graph_id] = candidates[0]
            methods[graph_id] = "exact_display_name"
            used.add(candidates[0])

    _validate_partial_mapping(mapping, graph_neighbors, source_neighbors)
    seed_count = len(mapping)
    _propagate_unique_neighbors(
        mapping,
        methods,
        graph_neighbors,
        source_neighbors,
        method="unique_neighbor_inference",
    )

    labels_graph, labels_source = _paired_wl_labels(
        graph_neighbors,
        source_neighbors,
        mapping,
    )
    changed = True
    while changed:
        changed = False
        graph_classes: dict[str, list[str]] = defaultdict(list)
        source_classes: dict[str, list[str]] = defaultdict(list)
        used = set(mapping.values())
        for graph_id in graph_rows:
            if graph_id not in mapping:
                graph_classes[labels_graph[graph_id]].append(graph_id)
        for source_id in source_rows:
            if source_id not in used:
                source_classes[labels_source[source_id]].append(source_id)
        if set(graph_classes) != set(source_classes):
            raise ValueError("Graph/source refinement classes differ")
        for label in sorted(graph_classes):
            graph_class = sorted(graph_classes[label])
            source_class = sorted(source_classes[label])
            if len(graph_class) != len(source_class):
                raise ValueError(f"Graph/source refinement class size differs for {label}")
            if len(graph_class) == 1:
                graph_id = graph_class[0]
                source_id = source_class[0]
                if _assignment_consistent(
                    graph_id,
                    source_id,
                    mapping,
                    graph_neighbors,
                    source_neighbors,
                ):
                    mapping[graph_id] = source_id
                    methods[graph_id] = "graph_refinement"
                    changed = True
        if changed:
            _propagate_unique_neighbors(
                mapping,
                methods,
                graph_neighbors,
                source_neighbors,
                method="graph_refinement",
            )
            labels_graph, labels_source = _paired_wl_labels(
                graph_neighbors,
                source_neighbors,
                mapping,
            )

    if len(mapping) < len(graph_rows):
        solution = _search_isomorphism(
            graph_neighbors,
            source_neighbors,
            mapping,
            labels_graph,
            labels_source,
        )
        if solution is None:
            raise ValueError(
                f"Could not resolve full graph isomorphism: {len(mapping)}/{len(graph_rows)} mapped"
            )
        for graph_id, source_id in solution.items():
            if graph_id not in mapping:
                methods[graph_id] = "graph_isomorphism_search"
        mapping = solution

    verified = _verify_isomorphism(mapping, graph_neighbors, source_neighbors)
    if not verified:
        raise ValueError("Resolved graph mapping does not preserve adjacency")
    if len(set(mapping.values())) != len(source_rows):
        raise ValueError("Resolved graph mapping is not bijective")
    return GraphMappingResult(
        graph_to_source=dict(sorted(mapping.items())),
        methods=dict(sorted(methods.items())),
        seed_count=seed_count,
        verified=True,
    )


def build_interim_goe_province_table() -> list[dict]:
    graph = load_goe_europe_graph()["provinces"]
    marker_layout = load_marker_layout()
    source = {row["id"]: row for row in marker_layout["provinces"]}
    result = resolve_graph_mapping(graph, source)
    table: list[dict] = []
    seen_colors: set[RGB] = set()
    for province_id in sorted(graph):
        source_id = result.graph_to_source[province_id]
        marker = source[source_id]
        color = _rgb(marker["id_color"])
        if color in seen_colors:
            raise ValueError(f"Duplicate source RGB {color}")
        seen_colors.add(color)
        table.append({
            "province_id": province_id,
            "display_name": graph[province_id].get("display_name", province_id),
            "rgb": list(color),
            "source_province_id": source_id,
            "mapping_method": result.methods[province_id],
            "marker_anchor": [float(marker["x"]), float(marker["y"])],
            "marker_map_region": marker.get("map_region"),
        })
    if len(table) != 517 or len(seen_colors) != 517:
        raise ValueError("Interim GoE table must contain 517 provinces and colors")
    return table


def write_interim_goe_province_table(path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "gates-of-codex.province-table",
        "schema_version": MAP_SCHEMA_VERSION,
        "map_id": "goe_europe",
        "provenance": "interim_goe_reference_asset",
        "provinces": build_interim_goe_province_table(),
    }
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def load_province_table(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rows = payload.get("provinces", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Province table must be a list or contain a provinces list")
    return [dict(row) for row in rows]


def import_strategic_map(
    id_map: str | Path,
    province_table: Sequence[dict],
    output: str | Path,
    *,
    map_id: str,
    provenance: str,
    ignored_colors: Iterable[RGB] = ((0, 0, 0),),
    expected_graph: dict[str, dict] | None = None,
    texture_output: str | Path | None = None,
) -> dict:
    source_path = Path(id_map)
    image = decode_png_rgb(source_path)
    table = _validate_table(province_table)
    ignored = {tuple(int(channel) for channel in color) for color in ignored_colors}
    table_colors = {tuple(row["rgb"]): row["province_id"] for row in table}
    image_colors = set(image.pixels)
    orphan_colors = sorted(image_colors - set(table_colors) - ignored)
    missing_colors = sorted(set(table_colors) - image_colors)
    if orphan_colors:
        raise ValueError(f"ID map contains orphan colors: {orphan_colors[:10]}")
    if missing_colors:
        raise ValueError(f"Province table colors missing from ID map: {missing_colors[:10]}")

    extracted_edges = extract_color_adjacency(
        image,
        recognized_colors=set(table_colors),
        ignored_colors=ignored,
        max_gap=6,
    )
    province_edges = {
        tuple(sorted((table_colors[left], table_colors[right])))
        for left, right in extracted_edges
    }
    expected_edges: set[tuple[str, str]] = set()
    if expected_graph is not None:
        expected_edges = _graph_edges(expected_graph)
    missing_edges = sorted(expected_edges - province_edges)
    extra_edges = sorted(province_edges - expected_edges) if expected_graph is not None else []
    if expected_graph is not None and (missing_edges or extra_edges):
        raise ValueError(
            "ID map adjacency differs from expected graph: "
            f"missing={len(missing_edges)}, extra={len(extra_edges)}"
        )

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    texture_path = source_path
    if texture_output is not None:
        texture_path = Path(texture_output)
        texture_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.resolve() != texture_path.resolve():
            shutil.copy2(source_path, texture_path)
    texture_reference = _relative_reference(destination.parent, texture_path)
    manifest = {
        "schema": "gates-of-codex.strategic-map",
        "schema_version": MAP_SCHEMA_VERSION,
        "map_id": map_id,
        "provenance": provenance,
        "asset_status": "interim" if provenance == "interim_goe_reference_asset" else "project_owned",
        "id_texture": {
            "path": texture_reference,
            "width": image.width,
            "height": image.height,
            "format": "RGB8",
            "sampling": "nearest",
            "sha256": hashlib.sha256(texture_path.read_bytes()).hexdigest(),
            "ignored_colors": [list(color) for color in sorted(ignored)],
        },
        "province_count": len(table),
        "province_table": sorted(table, key=lambda row: row["province_id"]),
        "adjacency": {
            "edge_count": len(province_edges),
            "validated_against_graph": expected_graph is not None,
            "missing_edges": [list(edge) for edge in missing_edges],
            "extra_edges": [list(edge) for edge in extra_edges],
        },
        "layers": [
            "background",
            "owner_fill",
            "province_borders",
            "coalition_front",
            "supply_encirclement",
            "selection_targets",
            "infrastructure_bases",
            "battalion_counters",
            "labels",
        ],
        "runtime_contract": {
            "pixel_lookup": "sample source ID texture with nearest-neighbor coordinates",
            "ownership": "runtime recolor only; source ID texture remains immutable",
            "gameplay_key": "province_id",
        },
    }
    destination.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def import_interim_goe_map(
    id_map: str | Path,
    output: str | Path,
    *,
    texture_output: str | Path | None = None,
    ignored_colors: Iterable[RGB] = ((0, 0, 0),),
) -> dict:
    graph = load_goe_europe_graph()["provinces"]
    return import_strategic_map(
        id_map,
        build_interim_goe_province_table(),
        output,
        map_id="goe_europe",
        provenance="interim_goe_reference_asset",
        ignored_colors=ignored_colors,
        expected_graph=graph,
        texture_output=texture_output,
    )


def decode_png_rgb(path: str | Path) -> DecodedIdImage:
    data = Path(path).read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("ID map must be a PNG file")
    offset = 8
    width = height = bit_depth = color_type = interlace = -1
    idat = bytearray()
    palette: list[RGB] = []
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            if compression != 0 or filter_method != 0:
                raise ValueError("Unsupported PNG compression/filter method")
        elif chunk_type == b"PLTE":
            if len(chunk) % 3:
                raise ValueError("Invalid PNG palette")
            palette = [tuple(chunk[index : index + 3]) for index in range(0, len(chunk), 3)]
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            break
    if width <= 0 or height <= 0 or bit_depth != 8 or interlace != 0:
        raise ValueError("Only non-interlaced 8-bit PNG ID maps are supported")
    if color_type not in {2, 3, 6}:
        raise ValueError(f"Unsupported PNG color type {color_type}")
    bytes_per_pixel = {2: 3, 3: 1, 6: 4}[color_type]
    stride = width * bytes_per_pixel
    raw = zlib.decompress(bytes(idat))
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError(f"Unexpected PNG data size {len(raw)} != {expected}")
    rows: list[bytes] = []
    previous = bytes(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        scanline = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        reconstructed = _unfilter_scanline(scanline, previous, bytes_per_pixel, filter_type)
        rows.append(reconstructed)
        previous = reconstructed
    pixels: list[RGB] = []
    for row in rows:
        if color_type == 2:
            pixels.extend(tuple(row[index : index + 3]) for index in range(0, len(row), 3))
        elif color_type == 6:
            pixels.extend(tuple(row[index : index + 3]) for index in range(0, len(row), 4))
        else:
            if not palette:
                raise ValueError("Indexed PNG has no palette")
            for index in row:
                if index >= len(palette):
                    raise ValueError("Indexed PNG references missing palette entry")
                pixels.append(palette[index])
    return DecodedIdImage(width=width, height=height, pixels=tuple(pixels))


def extract_color_adjacency(
    image: DecodedIdImage,
    *,
    recognized_colors: set[RGB],
    ignored_colors: set[RGB] | None = None,
    max_gap: int = 0,
) -> set[tuple[RGB, RGB]]:
    """Find province edges in an id-color map.

    MapChart/GoE id maps often separate provinces with white/black border pixels.
    ``max_gap`` allows scanning through that many ignored pixels when looking for
    a neighboring province color.
    """

    ignored = ignored_colors or set()
    edges: set[tuple[RGB, RGB]] = set()
    for y in range(image.height):
        for x in range(image.width):
            current = image.color_at(x, y)
            if current not in recognized_colors:
                continue
            for dx, dy in ((1, 0), (0, 1)):
                other = _first_recognized_neighbor(
                    image,
                    x,
                    y,
                    dx,
                    dy,
                    recognized_colors=recognized_colors,
                    ignored_colors=ignored,
                    max_gap=max_gap,
                )
                if other is not None and other != current:
                    edges.add(tuple(sorted((current, other))))
    return edges


def _first_recognized_neighbor(
    image: DecodedIdImage,
    x: int,
    y: int,
    dx: int,
    dy: int,
    *,
    recognized_colors: set[RGB],
    ignored_colors: set[RGB],
    max_gap: int,
) -> RGB | None:
    gap = 0
    cx, cy = x + dx, y + dy
    while 0 <= cx < image.width and 0 <= cy < image.height:
        color = image.color_at(cx, cy)
        if color in recognized_colors:
            return color
        if color not in ignored_colors:
            return None
        gap += 1
        if gap > max_gap:
            return None
        cx += dx
        cy += dy
    return None


def owner_color_lookup(
    province_table: Sequence[dict],
    ownership: dict[str, str],
    faction_colors: dict[str, RGB],
    *,
    default_color: RGB = (112, 119, 128),
) -> dict[RGB, RGB]:
    result: dict[RGB, RGB] = {}
    for row in _validate_table(province_table):
        source = tuple(row["rgb"])
        faction = ownership.get(row["province_id"], "neutral")
        result[source] = faction_colors.get(faction, default_color)
    return result


def _neighbor_sets(rows: dict[str, dict]) -> dict[str, set[str]]:
    keys = set(rows)
    result: dict[str, set[str]] = {}
    for node_id, row in rows.items():
        neighbors = {str(value) for value in row.get("neighbors", []) if str(value) in keys}
        if node_id in neighbors:
            raise ValueError(f"Node {node_id} neighbors itself")
        result[node_id] = neighbors
    for node_id, neighbors in result.items():
        for neighbor in neighbors:
            if node_id not in result[neighbor]:
                raise ValueError(f"Adjacency is not reciprocal: {node_id} -> {neighbor}")
    return result


def _validate_partial_mapping(
    mapping: dict[str, str],
    graph_neighbors: dict[str, set[str]],
    source_neighbors: dict[str, set[str]],
) -> None:
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Seed mapping contains duplicate source nodes")
    for graph_id, source_id in mapping.items():
        if len(graph_neighbors[graph_id]) != len(source_neighbors[source_id]):
            raise ValueError(f"Seed degree mismatch: {graph_id} -> {source_id}")
        for other_graph, other_source in mapping.items():
            if graph_id == other_graph:
                continue
            if (other_graph in graph_neighbors[graph_id]) != (
                other_source in source_neighbors[source_id]
            ):
                raise ValueError(
                    f"Seed adjacency mismatch: {graph_id}->{source_id}, "
                    f"{other_graph}->{other_source}"
                )


def _propagate_unique_neighbors(
    mapping: dict[str, str],
    methods: dict[str, str],
    graph_neighbors: dict[str, set[str]],
    source_neighbors: dict[str, set[str]],
    *,
    method: str,
) -> None:
    changed = True
    while changed:
        changed = False
        used = set(mapping.values())
        for graph_id, source_id in sorted(list(mapping.items())):
            graph_unmatched = sorted(value for value in graph_neighbors[graph_id] if value not in mapping)
            source_unmatched = sorted(value for value in source_neighbors[source_id] if value not in used)
            if len(graph_unmatched) != 1 or len(source_unmatched) != 1:
                continue
            next_graph = graph_unmatched[0]
            next_source = source_unmatched[0]
            if not _assignment_consistent(
                next_graph,
                next_source,
                mapping,
                graph_neighbors,
                source_neighbors,
            ):
                continue
            mapping[next_graph] = next_source
            methods[next_graph] = method
            changed = True


def _paired_wl_labels(
    graph_neighbors: dict[str, set[str]],
    source_neighbors: dict[str, set[str]],
    mapping: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    reverse = {source: graph for graph, source in mapping.items()}
    graph_labels = {
        node: f"seed:{mapping[node]}" if node in mapping else f"degree:{len(neighbors)}"
        for node, neighbors in graph_neighbors.items()
    }
    source_labels = {
        node: f"seed:{node}" if node in reverse else f"degree:{len(neighbors)}"
        for node, neighbors in source_neighbors.items()
    }
    for _ in range(max(len(graph_neighbors), 1)):
        graph_signatures = {
            node: (graph_labels[node], tuple(sorted(graph_labels[value] for value in neighbors)))
            for node, neighbors in graph_neighbors.items()
        }
        source_signatures = {
            node: (source_labels[node], tuple(sorted(source_labels[value] for value in neighbors)))
            for node, neighbors in source_neighbors.items()
        }
        signature_values = sorted(
            set(graph_signatures.values()) | set(source_signatures.values()),
            key=repr,
        )
        palette = {signature: f"c{index}" for index, signature in enumerate(signature_values)}
        next_graph = {node: palette[signature] for node, signature in graph_signatures.items()}
        next_source = {node: palette[signature] for node, signature in source_signatures.items()}
        if next_graph == graph_labels and next_source == source_labels:
            break
        graph_labels = next_graph
        source_labels = next_source
    return graph_labels, source_labels


def _search_isomorphism(
    graph_neighbors: dict[str, set[str]],
    source_neighbors: dict[str, set[str]],
    seed_mapping: dict[str, str],
    graph_labels: dict[str, str],
    source_labels: dict[str, str],
) -> dict[str, str] | None:
    mapping = dict(seed_mapping)
    used = set(mapping.values())
    source_by_label: dict[str, set[str]] = defaultdict(set)
    for source_id, label in source_labels.items():
        source_by_label[label].add(source_id)

    def candidates(graph_id: str) -> list[str]:
        available = source_by_label[graph_labels[graph_id]] - used
        values: list[str] = []
        graph_unmapped_signature = Counter(
            graph_labels[neighbor]
            for neighbor in graph_neighbors[graph_id]
            if neighbor not in mapping
        )
        for source_id in sorted(available):
            if len(graph_neighbors[graph_id]) != len(source_neighbors[source_id]):
                continue
            if not _assignment_consistent(
                graph_id,
                source_id,
                mapping,
                graph_neighbors,
                source_neighbors,
            ):
                continue
            source_unmapped_signature = Counter(
                source_labels[neighbor]
                for neighbor in source_neighbors[source_id]
                if neighbor not in used
            )
            if graph_unmapped_signature != source_unmapped_signature:
                continue
            values.append(source_id)
        return values

    def solve() -> bool:
        if len(mapping) == len(graph_neighbors):
            return True
        choices: list[tuple[int, str, list[str]]] = []
        for graph_id in graph_neighbors:
            if graph_id in mapping:
                continue
            values = candidates(graph_id)
            if not values:
                return False
            choices.append((len(values), graph_id, values))
        _, graph_id, values = min(choices, key=lambda item: (item[0], item[1]))
        for source_id in values:
            mapping[graph_id] = source_id
            used.add(source_id)
            if solve():
                return True
            used.remove(source_id)
            del mapping[graph_id]
        return False

    return dict(mapping) if solve() else None


def _assignment_consistent(
    graph_id: str,
    source_id: str,
    mapping: dict[str, str],
    graph_neighbors: dict[str, set[str]],
    source_neighbors: dict[str, set[str]],
) -> bool:
    if source_id in mapping.values():
        return False
    if len(graph_neighbors[graph_id]) != len(source_neighbors[source_id]):
        return False
    for other_graph, other_source in mapping.items():
        if (other_graph in graph_neighbors[graph_id]) != (
            other_source in source_neighbors[source_id]
        ):
            return False
    return True


def _verify_isomorphism(
    mapping: dict[str, str],
    graph_neighbors: dict[str, set[str]],
    source_neighbors: dict[str, set[str]],
) -> bool:
    if set(mapping) != set(graph_neighbors):
        return False
    if set(mapping.values()) != set(source_neighbors):
        return False
    for graph_id, neighbors in graph_neighbors.items():
        mapped_neighbors = {mapping[value] for value in neighbors}
        if mapped_neighbors != source_neighbors[mapping[graph_id]]:
            return False
    return True


def _unfilter_scanline(
    scanline: bytearray,
    previous: bytes,
    bytes_per_pixel: int,
    filter_type: int,
) -> bytes:
    output = bytearray(len(scanline))
    for index, value in enumerate(scanline):
        left = output[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index]
        up_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _paeth(left, up, up_left)
        else:
            raise ValueError(f"Unsupported PNG filter {filter_type}")
        output[index] = (value + predictor) & 0xFF
    return bytes(output)


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_up_left = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left


def _validate_table(rows: Sequence[dict]) -> list[dict]:
    result: list[dict] = []
    colors: set[RGB] = set()
    provinces: set[str] = set()
    for raw in rows:
        row = dict(raw)
        province_id = str(row.get("province_id", "")).strip()
        rgb_raw = row.get("rgb")
        if not province_id:
            raise ValueError("Province table row has no province_id")
        if not isinstance(rgb_raw, (list, tuple)) or len(rgb_raw) != 3:
            raise ValueError(f"Province {province_id} has invalid rgb")
        color = tuple(int(value) for value in rgb_raw)
        if any(value < 0 or value > 255 for value in color):
            raise ValueError(f"Province {province_id} has out-of-range rgb {color}")
        if province_id in provinces:
            raise ValueError(f"Duplicate province_id {province_id}")
        if color in colors:
            raise ValueError(f"Duplicate rgb {color}")
        provinces.add(province_id)
        colors.add(color)
        row["province_id"] = province_id
        row["rgb"] = list(color)
        result.append(row)
    return result


def _graph_edges(rows: dict[str, dict]) -> set[tuple[str, str]]:
    return {
        tuple(sorted((node_id, str(neighbor))))
        for node_id, row in rows.items()
        for neighbor in row.get("neighbors", [])
        if str(neighbor) in rows and str(neighbor) != node_id
    }


def _relative_reference(base: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return target.resolve().as_posix()


def _rgb(value: dict) -> RGB:
    return int(value["r"]), int(value["g"]), int(value["b"])


def _normalized_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())
