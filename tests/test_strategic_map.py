from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from gates_of_codex.europe import load_goe_europe_graph
from gates_of_codex.goe_strategic_map import (
    build_goe_source_nodes,
    build_interim_goe_province_table,
    duplicate_marker_ids,
    resolve_goe_graph_mapping,
)
from gates_of_codex.strategic_map import (
    decode_png_rgb,
    extract_color_adjacency,
    import_strategic_map,
    owner_color_lookup,
    resolve_graph_mapping,
)


RGB = tuple[int, int, int]


class StrategicMapTests(unittest.TestCase):
    def test_small_graph_mapping_is_bijective_and_deterministic(self) -> None:
        graph = {
            "alpha": {"display_name": "Alpha", "neighbors": ["beta", "gamma"]},
            "beta": {"display_name": "Beta", "neighbors": ["alpha", "gamma"]},
            "gamma": {"display_name": "Gamma", "neighbors": ["alpha", "beta", "delta"]},
            "delta": {"display_name": "Delta", "neighbors": ["gamma"]},
        }
        source = {
            "s4": {"display_name": "unmatched", "neighbors": ["s3"]},
            "s2": {"display_name": "Beta", "neighbors": ["s1", "s3"]},
            "s3": {"display_name": "unmatched", "neighbors": ["s1", "s2", "s4"]},
            "s1": {"display_name": "Alpha", "neighbors": ["s2", "s3"]},
        }
        first = resolve_graph_mapping(graph, source)
        second = resolve_graph_mapping(graph, source)
        self.assertTrue(first.verified)
        self.assertEqual(first.graph_to_source, second.graph_to_source)
        self.assertEqual(
            {"alpha": "s1", "beta": "s2", "gamma": "s3", "delta": "s4"},
            first.graph_to_source,
        )
        self.assertEqual(4, len(set(first.graph_to_source.values())))

    def test_duplicate_marker_text_id_does_not_drop_an_rgb_node(self) -> None:
        duplicates = duplicate_marker_ids()
        source_nodes = build_goe_source_nodes()
        self.assertEqual(517, len(source_nodes))
        self.assertEqual(1, len(duplicates))
        duplicate_rows = next(iter(duplicates.values()))
        self.assertEqual(2, len(duplicate_rows))
        self.assertNotEqual(duplicate_rows[0]["rgb"], duplicate_rows[1]["rgb"])
        suffixed = [key for key in source_nodes if "#" in key]
        self.assertEqual(2, len(suffixed))

    def test_actual_goe_graph_resolves_all_517_records(self) -> None:
        graph = load_goe_europe_graph()["provinces"]
        source = build_goe_source_nodes()
        result = resolve_goe_graph_mapping()
        self.assertTrue(result.verified)
        self.assertEqual(517, len(result.graph_to_source))
        self.assertEqual(517, len(set(result.graph_to_source.values())))
        for province_id, source_id in result.graph_to_source.items():
            mapped_neighbors = sorted(
                result.graph_to_source[neighbor]
                for neighbor in graph[province_id].get("neighbors", [])
            )
            self.assertEqual(source[source_id]["neighbors"], mapped_neighbors)

    def test_interim_table_has_one_rgb_per_campaign_province(self) -> None:
        table = build_interim_goe_province_table()
        self.assertEqual(517, len(table))
        self.assertEqual(517, len({row["province_id"] for row in table}))
        self.assertEqual(517, len({tuple(row["rgb"]) for row in table}))
        self.assertTrue(all(row["source_province_id"] for row in table))
        self.assertTrue(all(row["source_node_key"] for row in table))
        self.assertTrue(all(row["mapping_method"] for row in table))

    def test_png_decode_pixel_lookup_adjacency_and_import(self) -> None:
        colors = {
            "alpha": (10, 20, 30),
            "beta": (40, 50, 60),
            "gamma": (70, 80, 90),
        }
        pixels = [
            colors["alpha"], colors["alpha"], colors["beta"], colors["beta"],
            colors["alpha"], colors["gamma"], colors["gamma"], colors["beta"],
        ]
        graph = {
            "alpha": {"neighbors": ["beta", "gamma"]},
            "beta": {"neighbors": ["alpha", "gamma"]},
            "gamma": {"neighbors": ["alpha", "beta"]},
        }
        table = [
            {"province_id": province_id, "display_name": province_id.title(), "rgb": list(color)}
            for province_id, color in colors.items()
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Map Fixture With Spaces"
            source = root / "source id map.png"
            copied = root / "runtime" / "province id map.png"
            manifest_path = root / "runtime" / "map manifest.json"
            _write_rgb_png(source, 4, 2, pixels)
            before = hashlib.sha256(source.read_bytes()).hexdigest()

            image = decode_png_rgb(source)
            self.assertEqual((4, 2), (image.width, image.height))
            self.assertEqual(colors["alpha"], image.color_at(0, 0))
            self.assertEqual(colors["gamma"], image.color_at(1, 1))
            self.assertEqual(colors["beta"], image.color_at(3, 1))
            adjacency = extract_color_adjacency(
                image,
                recognized_colors=set(colors.values()),
            )
            self.assertEqual(
                {
                    tuple(sorted((colors["alpha"], colors["beta"]))),
                    tuple(sorted((colors["alpha"], colors["gamma"]))),
                    tuple(sorted((colors["beta"], colors["gamma"]))),
                },
                adjacency,
            )

            manifest = import_strategic_map(
                source,
                table,
                manifest_path,
                map_id="mini_theatre",
                provenance="project_owned_fixture",
                ignored_colors=(),
                expected_graph=graph,
                texture_output=copied,
            )
            ownership_colors = owner_color_lookup(
                table,
                {"alpha": "nato", "beta": "rusa", "gamma": "neutral"},
                {"nato": (1, 2, 3), "rusa": (4, 5, 6)},
            )
            after = hashlib.sha256(source.read_bytes()).hexdigest()

            self.assertEqual(before, after)
            self.assertEqual(4, manifest["id_texture"]["width"])
            self.assertEqual(2, manifest["id_texture"]["height"])
            self.assertEqual("nearest", manifest["id_texture"]["sampling"])
            self.assertEqual(3, manifest["province_count"])
            self.assertEqual(3, manifest["adjacency"]["edge_count"])
            self.assertEqual([], manifest["adjacency"]["missing_edges"])
            self.assertEqual([], manifest["adjacency"]["extra_edges"])
            self.assertEqual((1, 2, 3), ownership_colors[colors["alpha"]])
            self.assertEqual((4, 5, 6), ownership_colors[colors["beta"]])
            self.assertEqual((112, 119, 128), ownership_colors[colors["gamma"]])
            self.assertTrue(copied.is_file())
            persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("mini_theatre", persisted["map_id"])
            self.assertNotIn("1314", json.dumps(persisted))

    def test_import_rejects_duplicate_missing_and_orphan_colors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_path = root / "id.png"
            _write_rgb_png(image_path, 2, 1, [(1, 0, 0), (2, 0, 0)])
            with self.assertRaisesRegex(ValueError, "Duplicate rgb"):
                import_strategic_map(
                    image_path,
                    [
                        {"province_id": "a", "rgb": [1, 0, 0]},
                        {"province_id": "b", "rgb": [1, 0, 0]},
                    ],
                    root / "duplicate.json",
                    map_id="duplicate",
                    provenance="fixture",
                    ignored_colors=(),
                )
            with self.assertRaisesRegex(ValueError, "orphan colors"):
                import_strategic_map(
                    image_path,
                    [{"province_id": "a", "rgb": [1, 0, 0]}],
                    root / "orphan.json",
                    map_id="orphan",
                    provenance="fixture",
                    ignored_colors=(),
                )
            with self.assertRaisesRegex(ValueError, "missing from ID map"):
                import_strategic_map(
                    image_path,
                    [
                        {"province_id": "a", "rgb": [1, 0, 0]},
                        {"province_id": "b", "rgb": [2, 0, 0]},
                        {"province_id": "c", "rgb": [3, 0, 0]},
                    ],
                    root / "missing.json",
                    map_id="missing",
                    provenance="fixture",
                    ignored_colors=(),
                )


def _write_rgb_png(path: Path, width: int, height: int, pixels: list[RGB]) -> None:
    if len(pixels) != width * height:
        raise ValueError("pixel count does not match dimensions")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for color in pixels[y * width : (y + 1) * width]:
            raw.extend(color)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    payload = signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(bytes(raw))) + _png_chunk(b"IEND", b"")
    path.write_bytes(payload)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


if __name__ == "__main__":
    unittest.main()
