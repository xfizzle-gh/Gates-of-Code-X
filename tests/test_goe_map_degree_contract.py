from __future__ import annotations

import json
import unittest
from collections import Counter, defaultdict

from gates_of_codex.europe import load_goe_europe_graph
from gates_of_codex.goe_strategic_map import (
    build_goe_source_nodes,
    duplicate_marker_ids,
)
from gates_of_codex.map_layout import load_marker_layout


class GoEMapDegreeContractTests(unittest.TestCase):
    def test_source_record_order_aligns_with_campaign_graph(self) -> None:
        graph = load_goe_europe_graph()["provinces"]
        marker_rows = load_marker_layout()["provinces"]
        graph_rows = list(graph.items())
        self.assertEqual(517, len(graph_rows))
        self.assertEqual(517, len(marker_rows))

        marker_id_counts = Counter(str(row.get("id", "")) for row in marker_rows)
        exact_seed_positions: list[int] = []
        order_mapping: dict[str, str] = {}
        for index, ((graph_id, graph_row), marker_row) in enumerate(zip(graph_rows, marker_rows)):
            marker_id = str(marker_row.get("id", ""))
            graph_name = str(graph_row.get("display_name", graph_id))
            if graph_id == marker_id or graph_name == marker_id:
                exact_seed_positions.append(index)
            source_key = marker_id
            if marker_id_counts[marker_id] > 1:
                rgb = marker_row["id_color"]
                source_key = f"{marker_id}#{int(rgb['r']):02x}{int(rgb['g']):02x}{int(rgb['b']):02x}"
            order_mapping[graph_id] = source_key

        source = build_goe_source_nodes()
        graph_edges = _edges(graph)
        source_edges = _edges(source)
        mapped_graph_edges = {
            tuple(sorted((order_mapping[left], order_mapping[right])))
            for left, right in graph_edges
        }
        diagnostics = {
            "exact_seed_count": len(exact_seed_positions),
            "first_exact_seed_positions": exact_seed_positions[:40],
            "last_exact_seed_positions": exact_seed_positions[-40:],
            "order_mapping_is_bijective": len(set(order_mapping.values())) == 517,
            "order_mapping_missing_edges": len(mapped_graph_edges - source_edges),
            "order_mapping_extra_edges": len(source_edges - mapped_graph_edges),
            "missing_edge_samples": sorted(mapped_graph_edges - source_edges)[:40],
            "extra_edge_samples": sorted(source_edges - mapped_graph_edges)[:40],
        }
        self.assertEqual(
            517,
            len(exact_seed_positions),
            msg=json.dumps(diagnostics, indent=2, sort_keys=True),
        )

    def test_source_degree_distribution_matches_campaign_graph(self) -> None:
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
        self.assertEqual(
            graph_distribution,
            source_distribution,
            msg=json.dumps(diagnostics, indent=2, sort_keys=True),
        )


def _edges(rows: dict[str, dict]) -> set[tuple[str, str]]:
    return {
        tuple(sorted((node_id, str(neighbor))))
        for node_id, row in rows.items()
        for neighbor in row.get("neighbors", [])
        if str(neighbor) in rows and str(neighbor) != node_id
    }


if __name__ == "__main__":
    unittest.main()
