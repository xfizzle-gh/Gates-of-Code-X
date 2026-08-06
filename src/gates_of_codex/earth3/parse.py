"""Deterministic Earth3 dataset loader."""

from __future__ import annotations

import re
from pathlib import Path

from .aoh_json import parse_aoh_json
from .archive import Earth3Archive, Earth3ArchiveError, open_earth3_archive
from .model import Earth3City, Earth3Dataset, Earth3Province

_PART_INDEX = re.compile(r"^(?P<stem>.+?)(?:_(?P<idx>\d+))?\.json$", re.IGNORECASE)


def load_earth3_dataset(archive_path: str | Path) -> Earth3Dataset:
    with open_earth3_archive(archive_path) as archive:
        return load_earth3_dataset_from_archive(archive)


def load_earth3_dataset_from_archive(archive: Earth3Archive) -> Earth3Dataset:
    config = parse_aoh_json(archive.read_text("Earth3/Config.json"))
    if not isinstance(config, dict):
        raise ValueError("Earth3 Config.json must be an object")

    details_raw = parse_aoh_json(archive.read_text("Earth3/data/ProvinceDetails.json"))
    names_raw = parse_aoh_json(archive.read_text("Earth3/data/ProvinceNamePoints.json"))
    if not isinstance(details_raw, list) or not isinstance(names_raw, list):
        raise ValueError("ProvinceDetails/NamePoints must be arrays")

    details_by_id = _index_by_pid(details_raw, "ProvinceDetails")
    names_by_id = _index_by_pid(names_raw, "ProvinceNamePoints")

    rings = _load_province_rings(archive)
    directed, undirected, adj_stats = _load_adjacency(archive)
    cities = _load_cities(archive)

    declared = int(config.get("NumOfProvinces", len(rings)))
    if declared != len(rings):
        raise ValueError(
            f"NumOfProvinces={declared} does not match polygon count={len(rings)}"
        )

    missing_details = sorted(set(rings) - set(details_by_id))
    if missing_details:
        raise ValueError(
            f"ProvinceDetails missing {len(missing_details)} ids; sample={missing_details[:12]}"
        )

    provinces: dict[int, Earth3Province] = {}
    for source_id in sorted(rings):
        ring = rings[source_id]
        if len(ring) < 3:
            raise ValueError(f"province {source_id} has fewer than 3 vertices")
        detail = details_by_id[source_id]
        name = names_by_id.get(source_id, {})
        label_x = float(name.get("cx", name.get("fX", ring[0][0])))
        label_y = float(name.get("cy", name.get("fY", ring[0][1])))
        provinces[source_id] = Earth3Province(
            source_id=source_id,
            ring=ring,
            label_x=label_x,
            label_y=label_y,
            continent_id=int(detail.get("co", -1)),
            terrain_id=int(detail.get("tr", -1)),
            region_id=int(detail.get("re", -1)),
            growth=float(detail.get("gr", 0.0)),
            base_development=int(detail.get("bd", 0)),
        )

    # Validate adjacency endpoints against known province IDs.
    max_id = max(provinces) if provinces else -1
    for pid, nbs in directed.items():
        if pid < 0 or pid > max_id or pid not in provinces:
            raise ValueError(f"adjacency endpoint out of range: pid={pid}")
        for nb in nbs:
            if nb < 0 or nb > max_id or nb not in provinces:
                raise ValueError(f"adjacency endpoint out of range: {pid}->{nb}")

    bg_x = int(config.get("BackgroundSize_X", 8))
    bg_y = int(config.get("BackgroundSize_Y", 4))
    return Earth3Dataset(
        provinces=provinces,
        adjacency=undirected,
        directed_adjacency=directed,
        source_directed_edge_count=adj_stats["source_directed_edge_count"],
        undirected_edge_count=adj_stats["undirected_edge_count"],
        one_way_source_pairs=adj_stats["one_way_source_pairs"],
        mutual_source_pairs=adj_stats["mutual_source_pairs"],
        cities=cities,
        background_size=(bg_x, bg_y),
        background_tile=(2220, 2150),
        num_of_provinces_declared=declared,
        source_label=str(config.get("Name", "Earth3")),
    )


def _index_by_pid(rows: list[object], label: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{label}[{index}] is not an object")
        if "pid" not in row:
            raise ValueError(f"{label}[{index}] missing pid")
        pid = int(row["pid"])
        if pid in out:
            raise ValueError(f"{label} duplicate pid={pid}")
        out[pid] = row
    return out


def _load_province_rings(archive: Earth3Archive) -> dict[int, tuple[tuple[float, float], ...]]:
    members = [
        name
        for name in archive.list_prefix("Earth3/data/ProvincePoints")
        if name.endswith(".json") and "Cut" not in name
    ]
    if not members:
        raise ValueError("no ProvincePoints JSON members found")
    ordered = _order_part_files(members)
    rings: dict[int, tuple[tuple[float, float], ...]] = {}
    next_id = 0
    for member in ordered:
        payload = parse_aoh_json(archive.read_text(member))
        rows = _extract_data_array(payload, member)
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{member} contains non-object province row")
            xs = row.get("pX")
            ys = row.get("pY")
            if not isinstance(xs, list) or not isinstance(ys, list):
                raise ValueError(f"{member} province missing pX/pY arrays at id={next_id}")
            if len(xs) != len(ys):
                raise ValueError(
                    f"{member} pX/pY length mismatch at id={next_id}: {len(xs)}!={len(ys)}"
                )
            if len(xs) < 3:
                raise ValueError(f"{member} polygon too small at id={next_id}")
            ring = tuple((float(x), float(y)) for x, y in zip(xs, ys, strict=True))
            rings[next_id] = ring
            next_id += 1
    return rings


def _load_adjacency(
    archive: Earth3Archive,
) -> tuple[dict[int, set[int]], dict[int, set[int]], dict[str, object]]:
    """Load adjacency; return (directed, undirected-symmetric, stats).

    Earth3 stores most undirected edges as a single directed record. That is
    expected, not a geometry defect. Stats separate one-way storage from true
    mutual pairs.
    """
    members = [
        name
        for name in archive.list_prefix("Earth3/data/ProvinceNeighboringProvinces")
        if name.endswith(".json")
    ]
    if not members:
        raise ValueError("no ProvinceNeighboringProvinces JSON members found")
    ordered = _order_part_files(members)
    directed: dict[int, set[int]] = {}
    seen_pairs: set[tuple[int, int]] = set()
    for member in ordered:
        payload = parse_aoh_json(archive.read_text(member))
        if not isinstance(payload, list):
            raise ValueError(f"{member} must be an array")
        for row in payload:
            if not isinstance(row, dict):
                raise ValueError(f"{member} adjacency row is not an object")
            if "pid" not in row or "wp" not in row:
                raise ValueError(f"{member} adjacency row missing pid/wp")
            pid = int(row["pid"])
            wp = int(row["wp"])
            pair = (pid, wp)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            directed.setdefault(pid, set()).add(wp)

    undirected: dict[int, set[int]] = {}
    one_way: list[tuple[int, int]] = []
    mutual: list[tuple[int, int]] = []
    undirected_pairs: set[tuple[int, int]] = set()
    for pid, nbs in directed.items():
        for wp in nbs:
            undirected.setdefault(pid, set()).add(wp)
            undirected.setdefault(wp, set()).add(pid)
            a, b = (pid, wp) if pid < wp else (wp, pid)
            undirected_pairs.add((a, b))
            if pid in directed.get(wp, set()):
                if pid < wp:
                    mutual.append((pid, wp))
            else:
                one_way.append((pid, wp))
    one_way.sort()
    mutual.sort()
    stats: dict[str, object] = {
        "source_directed_edge_count": sum(len(v) for v in directed.values()),
        "undirected_edge_count": len(undirected_pairs),
        "one_way_source_pairs": tuple(one_way),
        "mutual_source_pairs": tuple(mutual),
    }
    return directed, undirected, stats


def _load_cities(archive: Earth3Archive) -> tuple[Earth3City, ...]:
    try:
        raw = archive.read_text("Earth3/cities/cities.json")
    except Earth3ArchiveError:
        return ()
    payload = parse_aoh_json(raw)
    if not isinstance(payload, list):
        raise ValueError("Earth3/cities/cities.json must be an array")
    cities: list[Earth3City] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"cities[{index}] is not an object")
        cities.append(
            Earth3City(
                name=str(row.get("Name", row.get("name", ""))),
                x=float(row["x"]),
                y=float(row["y"]),
                province_id=int(row["p"]),
                source_index=index,
            )
        )
    return tuple(cities)


def _extract_data_array(payload: object, member: str) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("Data", payload.get("data"))
        if isinstance(data, list):
            return data
    raise ValueError(f"{member} does not contain a Data array")


def _order_part_files(members: list[str]) -> list[str]:
    """Order ProvincePoints.json, _1, _2... deterministically by numeric suffix."""

    def sort_key(name: str) -> tuple[str, int]:
        base = name.rsplit("/", 1)[-1]
        match = _PART_INDEX.match(base)
        if not match:
            return base.lower(), 10**9
        stem = match.group("stem").lower()
        idx = match.group("idx")
        return stem, 0 if idx is None else int(idx) + 1

    return sorted(members, key=sort_key)
