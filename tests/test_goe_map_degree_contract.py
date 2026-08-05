from __future__ import annotations

import json
import re
import unittest
from collections import Counter, defaultdict

from gates_of_codex.europe import load_goe_europe_graph
from gates_of_codex.goe_strategic_map import (
    build_goe_source_nodes,
    duplicate_marker_ids,
)
from gates_of_codex.map_layout import load_marker_layout


class GoEMapDegreeContractTests(unittest.TestCase):
    def test_synthetic_ids_preserve_marker_source_index(self) -> None:
        graph = load_goe_europe_graph()["provinces"]
        marker_rows = load_marker_layout()["provinces"]
        source = build_goe_source_nodes()
        graph_edges = _edges(graph)
        source_edges = _edges(source)
        marker_id_counts = Counter(str(row.get("id", "")) for row in marker_rows)

        diagnostics: dict[str, dict] = {}
        for offset in (0, 1):
            mapping: dict[str, str] = {}
            invalid: list[str] = []
            for graph_id, graph_row in graph.items():
                marker_index = None
                match = re.fullmatch(r"province_(\d+)", graph_id)
                if match:
                    marker_index = int(match.group(1)) - offset
                if marker_index is not None:
                    if not 0 <= marker_index < len(marker_rows):
                        invalid.append(graph_id)
                        continue
                    marker_row = marker_rows[marker_index]
                else:
                    graph_name = str(graph_row.get("display_name", graph_id))
                    candidates = [
                        row
                        for row in marker_rows
                        if str(row.get("id", "")) == graph_id
                        or str(row.get("display_name", "")) == graph_name
                    ]
                    if len(candidates) != 1:
                        invalid.append(graph_id)
                        continue
                    marker_row = candidates[0]
                mapping[graph_id] = _source_key(marker_row, marker_id_counts)

            mapped_graph_edges = {
                tuple(sorted((mapping[left], mapping[right])))
                for left, right in graph_edges
                if left in mapping and right in mapping
            }
            diagnostics[f"offset_{offset}"] = {
                "mapped_count": len(mapping),
                "invalid": invalid[:40],
                "is_bijective": len(set(mapping.values())) == len(mapping),
                "missing_edges": len(mapped_graph_edges - source_edges),
                "extra_edges": len(source_edges - mapped_graph_edges),
                "missing_edge_samples": sorted(mapped_graph_edges - source_edges)[:40],
                "extra_edge_samples": sorted(source_edges - mapped_graph_edges)[:40],
            }

        selected = min(
            diagnostics.values(),
            key=lambda value: (
                len(value["invalid"]),
                value["missing_edges"],
                value["extra_edges"],
            ),
        )
        self.assertEqual(
            {"mapped_count": 517, "invalid": [], "is_bijective": True, "missing_edges": 0, "extra_edges": 11},
            {
                key: selected[key]
                for key in ("mapped_count", "invalid", "is_bijective", "missing_edges", "extra_edges")
            },
            msg=json.dumps(diagnostics, indent=2, sort_keys=True),
        )

    def test_source_degree_distribution_difference_is_documented(self) -> None:
        graph = load_goe_europe_graph()["provinces"]
        marker_rows = load_marker_layout()["provinces"]
        source = build_goe_source_nodes()
        graph_distribution = dict(
            sorted(Counter(len(row.get("neighbors", [])) for row in graph.values()).items())
        )
        raw_distribution = dict(
            sorted(Counter(len(row.get("neighbors", [])) for row in marker_rows).items())
        )
        source_distribution = dict(
            sorted(Counter(len(row.get("neighbors", [])) for row in source.values()).items())
        )
        graph_edges = _edges(graph)
        source_edges = _edges(source)
        marker_ids = {str(row.get("id", "")) for row in marker_rows}
        graph_ids = set(graph)
        source_keys_by_original: dict[str, list[str]] = defaultdict(list)
        for source_key, row in source.items():
            source_keys_by_original[str(row.get("source_province_id", ""))].append(source_key)
        exact_source_key = {
            original: keys[0]
            for original, keys in source_keys_by_original.items()
            if len(keys) == 1
        }
        comparable_graph_edges = {
            tuple(sorted((exact_source_key[left], exact_source_key[right])))
            for left, right in graph_edges
            if left in exact_source_key and right in exact_source_key
        }
        comparable_source_edges = {
            edge
            for edge in source_edges
            if "#" not in edge[0] and "#" not in edge[1]
        }
        diagnostics = {
            "graph_degree_distribution": graph_distribution,
            "raw_marker_degree_distribution": raw_distribution,
            "reconstructed_degree_distribution": source_distribution,
            "graph_edge_count": len(graph_edges),
            "reconstructed_edge_count": len(source_edges),
            "graph_id_count": len(graph_ids),
            "marker_text_id_count": len(marker_ids),
            "graph_ids_not_in_marker_text_ids": sorted(graph_ids - marker_ids)[:80],
            "marker_text_ids_not_in_graph_ids": sorted(marker_ids - graph_ids)[:80],
            "comparable_edges_missing_from_source": sorted(
                comparable_graph_edges - comparable_source_edges
            )[:80],
            "comparable_edges_extra_in_source": sorted(
                comparable_source_edges - comparable_graph_edges
            )[:80],
            "duplicate_marker_ids": duplicate_marker_ids(),
        }
        self.assertEqual(1164, len(graph_edges), msg=json.dumps(diagnostics, indent=2, sort_keys=True))
        self.assertEqual(1175, len(source_edges), msg=json.dumps(diagnostics, indent=2, sort_keys=True))
        self.assertNotEqual(graph_distribution, source_distribution)


def _source_key(row: dict, counts: Counter[str]) -> str:
    marker_id = str(row.get("id", ""))
    if counts[marker_id] == 1:
        return marker_id
    rgb = row["id_color"]
    return f"{marker_id}#{int(rgb['r']):02x}{int(rgb['g']):02x}{int(rgb['b']):02x}"


def _edges(rows: dict[str, dict]) -> set[tuple[str, str]]:
    return {
        tuple(sorted((node_id, str(neighbor))))
        for node_id, row in rows.items()
        for neighbor in row.get("neighbors", [])
        if str(neighbor) in rows and str(neighbor) != node_id
    }


if __name__ == "__main__":
    unittest.main()
