from __future__ import annotations

import json
from collections import Counter
from importlib.resources import files
from pathlib import Path

from .europe import load_goe_europe_graph
from .map_layout import load_marker_layout


AUDIT_SCHEMA_VERSION = 1
MARKER_SOURCE_PATH = "src/gates_of_codex/data/goe_marker_layout.json"
GRAPH_SOURCE_GLOB = "src/gates_of_codex/data/goe_graph_*.b85"


def build_goe_source_audit(*, include_mappings: bool = True) -> dict:
    graph = load_goe_europe_graph()
    marker_layout = load_marker_layout()
    graph_rows = graph.get("provinces", {})
    marker_rows = marker_layout.get("provinces", [])
    if len(graph_rows) != 517:
        raise ValueError(f"Expected 517 bundled graph provinces, found {len(graph_rows)}")
    if len(marker_rows) != 517:
        raise ValueError(f"Expected 517 extracted marker records, found {len(marker_rows)}")

    colors = [_rgb_key(row.get("id_color", {})) for row in marker_rows]
    if len(set(colors)) != len(colors):
        duplicates = sorted(color for color, count in Counter(colors).items() if count > 1)
        raise ValueError(f"Extracted marker source contains duplicate RGB ids: {duplicates[:5]}")

    mappings, method_counts = _map_graph_to_marker(graph_rows, marker_rows)
    matched = sum(1 for row in mappings if row["marker_province_id"])
    unmatched = len(mappings) - matched
    payload = {
        "schema": "gates-of-codex.goe-province-source-audit",
        "schema_version": AUDIT_SCHEMA_VERSION,
        "map_id": graph.get("map_id", "goe_europe"),
        "province_count": len(graph_rows),
        "source_inventory": {
            "bundled_graph": {
                "path": GRAPH_SOURCE_GLOB,
                "record_count": len(graph_rows),
                "fields": ["province_id", "display_name", "neighbors", "x", "y", "metadata"],
                "provenance": "GoE-derived 517-node graph stored as compressed package data",
                "classification": "extracted_reference_data",
            },
            "marker_id_database": {
                "path": MARKER_SOURCE_PATH,
                "source_label": marker_layout.get("source", "goe province_database_newestV7 marker/idcolor extract"),
                "method": marker_layout.get("method", "mapchart_hoi4_color_id"),
                "record_count": len(marker_rows),
                "unique_rgb_count": len(set(colors)),
                "fields": ["id", "display_name", "x", "y", "id_color", "neighbors", "map_region"],
                "provenance": "extracted GoE marker anchors and IdColor records",
                "classification": "extracted_reference_data",
            },
            "id_texture": {
                "asset_name": "province_idnew_map",
                "width": 1314,
                "height": 1513,
                "format": "RGB24",
                "province_id_color_count": 517,
                "repository_path": None,
                "status": "owner-authorized interim GoE-derived asset for generic importer in #51",
                "provenance": "GoE Unity binary inspection recorded in issues #49 and #53",
                "classification": "extracted_binary_metadata",
            },
        },
        "mapping_coverage": {
            "graph_records": len(graph_rows),
            "marker_records": len(marker_rows),
            "mapped_graph_records": matched,
            "unmapped_graph_records": unmatched,
            "mapping_methods": dict(sorted(method_counts.items())),
            "unmapped_placement": "neighbor_average in PR #50 marker presentation only",
            "authoritative_click_target": "color-ID texture pixels in #51, not marker points",
        },
        "field_availability": _field_availability(),
        "scenario_design_separation": {
            "modern_control_profile": {
                "value": "modern_europe_v1",
                "source": "src/gates_of_codex/control.py",
                "classification": "new_scenario_design",
                "goe_ownership_claimed": False,
            },
            "formation_deployments": {
                "source": "src/gates_of_codex/formations.py",
                "classification": "new_scenario_design",
                "goe_deployment_claimed": False,
            },
            "strategic_capitals_and_objectives": {
                "source": "src/gates_of_codex/strategic.py",
                "classification": "new_scenario_design",
                "goe_metadata_claimed": False,
            },
        },
        "required_authoring": [
            "country and neutral-actor geographic ownership",
            "capital designations",
            "ports and coastal access",
            "rail and logistics corridors",
            "terrain tags including river, mountain, forest, urban, and industrial",
            "disputed, demilitarized, and special-zone designations",
            "scenario-specific ownership and deployment overrides",
        ],
    }
    if include_mappings:
        payload["province_mappings"] = mappings
    return payload


def write_goe_source_audit(
    output: str | Path,
    summary: str | Path,
    *,
    include_mappings: bool = True,
) -> dict:
    payload = build_goe_source_audit(include_mappings=include_mappings)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_path = Path(summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(render_goe_source_summary(payload), encoding="utf-8")
    return payload


def render_goe_source_summary(payload: dict) -> str:
    coverage = payload["mapping_coverage"]
    fields = payload["field_availability"]
    lines = [
        "# Gates of Europa province-source audit",
        "",
        "## Confirmed extracted sources",
        "",
        f"- Bundled graph: `{GRAPH_SOURCE_GLOB}`, {payload['province_count']} province records.",
        f"- Marker/ID database: `{MARKER_SOURCE_PATH}`, 517 anchors and 517 unique RGB IDs.",
        "- Unity ID texture metadata: `province_idnew_map`, 1314×1513, RGB24, 517 ID colors.",
        "- The current marker display is temporary. #51 must use color-ID pixels for authoritative province selection.",
        "",
        "## Graph-to-marker mapping coverage",
        "",
        f"- Graph records: {coverage['graph_records']}",
        f"- Extracted marker records: {coverage['marker_records']}",
        f"- Graph records mapped to an extracted marker record: {coverage['mapped_graph_records']}",
        f"- Graph records without a defensible marker-record mapping: {coverage['unmapped_graph_records']}",
        f"- Mapping methods: {_format_counts(coverage['mapping_methods'])}",
        "- Unmapped graph records are placed by neighbor averaging only for the temporary PR #50 presentation. They do not receive invented RGB IDs.",
        "",
        "## Metadata availability",
        "",
        "| Field | Status | Provenance | Campaign treatment |",
        "|---|---|---|---|",
    ]
    for field_name in sorted(fields):
        field = fields[field_name]
        lines.append(
            f"| {field_name} | `{field['status']}` | {field['provenance']} | {field['campaign_treatment']} |"
        )
    lines.extend([
        "",
        "## Extracted data versus scenario design",
        "",
        "The extracted sources establish province IDs, names, adjacency, marker anchors, unique RGB IDs, and an unlabeled numeric `map_region` value. They do not establish a complete modern ownership scenario, capitals, ports, rail, terrain, or special zones.",
        "",
        "Current `modern_europe_v1` ownership, formation anchors, capitals, objectives, PRC/KPA deployment assumptions, and coalition structure are new Gates of CodeX scenario design. They must not be cited as original GoE metadata.",
        "",
        "## Required follow-up authoring",
        "",
    ])
    lines.extend(f"- {value}" for value in payload["required_authoring"])
    lines.extend([
        "",
        "## Swap and rendering boundary",
        "",
        "The interim GoE-derived ID texture must be consumed through the generic manifest/import interface in #51. Gameplay must not depend on 1314×1513 dimensions, the current RGB assignments, or Unity source formatting. A future project-owned map replaces the manifest, texture, and lookup table without changing campaign rules.",
        "",
    ])
    return "\n".join(lines)


def load_committed_goe_audit_manifest() -> dict:
    package_root = files("gates_of_codex")
    repository_root = Path(str(package_root)).resolve().parents[2]
    path = repository_root / "docs/audits/goe-province-metadata.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _map_graph_to_marker(graph_rows: dict, marker_rows: list[dict]) -> tuple[list[dict], Counter[str]]:
    by_id = {row["id"]: row for row in marker_rows}
    by_name = {
        str(row.get("display_name", "")).strip().lower(): row
        for row in marker_rows
        if str(row.get("display_name", "")).strip()
    }
    matched: dict[str, str] = {}
    methods: dict[str, str] = {}
    evidence: dict[str, str] = {}
    for graph_id, graph_row in graph_rows.items():
        if graph_id in by_id:
            matched[graph_id] = graph_id
            methods[graph_id] = "exact_id"
            evidence[graph_id] = graph_id
            continue
        graph_name = str(graph_row.get("display_name", graph_id)).strip().lower()
        if graph_name in by_name:
            matched[graph_id] = by_name[graph_name]["id"]
            methods[graph_id] = "exact_display_name"
            evidence[graph_id] = str(graph_row.get("display_name", graph_id))

    changed = True
    while changed:
        changed = False
        for graph_id, marker_id in list(matched.items()):
            graph_neighbors = [
                value
                for value in graph_rows[graph_id].get("neighbors", [])
                if value in graph_rows
            ]
            marker_neighbors = [
                value
                for value in by_id[marker_id].get("neighbors", [])
                if value in by_id
            ]
            unmatched_graph = [value for value in graph_neighbors if value not in matched]
            unmatched_marker = [value for value in marker_neighbors if value not in matched.values()]
            if len(unmatched_graph) == 1 and len(unmatched_marker) == 1:
                next_graph = unmatched_graph[0]
                next_marker = unmatched_marker[0]
                matched[next_graph] = next_marker
                methods[next_graph] = "unique_neighbor_inference"
                evidence[next_graph] = f"{graph_id}->{marker_id}"
                changed = True

    rows: list[dict] = []
    method_counts: Counter[str] = Counter()
    for graph_id in sorted(graph_rows):
        graph_row = graph_rows[graph_id]
        marker_id = matched.get(graph_id, "")
        marker = by_id.get(marker_id)
        method = methods.get(graph_id, "unmapped_neighbor_average")
        method_counts[method] += 1
        rows.append({
            "province_id": graph_id,
            "display_name": graph_row.get("display_name", graph_id),
            "graph_source": GRAPH_SOURCE_GLOB,
            "graph_coordinates": {
                "x": graph_row.get("x"),
                "y": graph_row.get("y"),
                "source": "bundled graph record",
            },
            "neighbors": sorted(graph_row.get("neighbors", [])),
            "neighbors_source": "bundled graph record",
            "marker_province_id": marker_id or None,
            "marker_mapping_method": method,
            "marker_mapping_evidence": evidence.get(graph_id),
            "marker_anchor": (
                {"x": marker.get("x"), "y": marker.get("y")}
                if marker is not None
                else None
            ),
            "id_color": dict(marker.get("id_color", {})) if marker is not None else None,
            "marker_map_region": marker.get("map_region") if marker is not None else None,
            "marker_source": MARKER_SOURCE_PATH if marker is not None else None,
            "mapping_confidence": (
                "high"
                if method in {"exact_id", "exact_display_name"}
                else "medium"
                if method == "unique_neighbor_inference"
                else "low"
            ),
            "country_id": None,
            "country_source": "not present in extracted graph or marker/ID database",
            "country_classification": "requires_scenario_authoring",
            "capital_status": None,
            "port_status": None,
            "rail_status": None,
            "terrain_tags": [],
            "special_zone_tags": [],
        })
    return rows, method_counts


def _field_availability() -> dict[str, dict[str, str]]:
    return {
        "province_id": {
            "status": "available",
            "provenance": "bundled graph and extracted marker database",
            "campaign_treatment": "preserve exact existing graph IDs",
        },
        "display_name": {
            "status": "available",
            "provenance": "bundled graph and extracted marker database",
            "campaign_treatment": "preserve source value; record mapping ambiguity",
        },
        "adjacency": {
            "status": "available",
            "provenance": "bundled graph plus extracted marker neighbor records",
            "campaign_treatment": "preserve existing reciprocal graph contract",
        },
        "marker_anchor": {
            "status": "available_for_all_marker_records",
            "provenance": "province_database_newestV7 marker extract",
            "campaign_treatment": "temporary labels/counters only",
        },
        "id_color": {
            "status": "available_for_all_marker_records",
            "provenance": "province_database_newestV7 IdColor extract",
            "campaign_treatment": "generic color-ID renderer lookup in #51",
        },
        "country_ownership": {
            "status": "not_found",
            "provenance": "not present in bundled graph or marker/ID extract",
            "campaign_treatment": "author separately as scenario data",
        },
        "capital_status": {
            "status": "not_found",
            "provenance": "not present in inspected extracted sources",
            "campaign_treatment": "author separately as scenario data",
        },
        "ports_coastal": {
            "status": "not_found",
            "provenance": "not present in inspected extracted sources",
            "campaign_treatment": "author from a defensible geographic source",
        },
        "rail_logistics": {
            "status": "not_found",
            "provenance": "not present in inspected extracted sources",
            "campaign_treatment": "author from a defensible logistics source",
        },
        "terrain": {
            "status": "not_found",
            "provenance": "not present in inspected extracted sources",
            "campaign_treatment": "author stable province tags separately",
        },
        "regional_grouping": {
            "status": "numeric_value_unresolved",
            "provenance": "marker database `map_region` field",
            "campaign_treatment": "do not assign country meaning without source semantics",
        },
        "special_zones": {
            "status": "not_found",
            "provenance": "not present in inspected extracted sources",
            "campaign_treatment": "author separately per scenario",
        },
        "scenario_overrides": {
            "status": "not_found_in_extracted_sources",
            "provenance": "current repository values are Gates of CodeX design",
            "campaign_treatment": "keep separate from immutable geography",
        },
    }


def _rgb_key(value: dict) -> tuple[int, int, int]:
    return int(value.get("r", -1)), int(value.get("g", -1)), int(value.get("b", -1))


def _format_counts(values: dict) -> str:
    return ", ".join(f"{key}={values[key]}" for key in sorted(values)) or "none"
