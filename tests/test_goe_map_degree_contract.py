from __future__ import annotations

import json
import unittest
from collections import Counter

from gates_of_codex.europe import load_goe_europe_graph
from gates_of_codex.goe_strategic_map import (
    build_goe_source_nodes,
    duplicate_marker_ids,
)
from gates_of_codex.map_layout import load_marker_layout


class GoEMapDegreeContractTests(unittest.TestCase):
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
        graph_edges = sum(len(row.get("neighbors", [])) for row in graph.values()) // 2
        source_edges = sum(len(row.get("neighbors", [])) for row in source.values()) // 2
        diagnostics = {
            "graph_degree_distribution": graph_distribution,
            "raw_marker_degree_distribution": raw_distribution,
            "reconstructed_degree_distribution": source_distribution,
            "graph_edge_count": graph_edges,
            "reconstructed_edge_count": source_edges,
            "duplicate_marker_ids": duplicate_marker_ids(),
        }
        self.assertEqual(
            graph_distribution,
            source_distribution,
            msg=json.dumps(diagnostics, indent=2, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
