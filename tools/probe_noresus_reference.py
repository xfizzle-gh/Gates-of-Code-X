from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import statistics
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


KEY_PATHS = (
    "mod.info",
    "READ ME FIRST.txt",
    "datamap_reset.sql",
    "mappoints_att.inc",
    "mappoints_def.inc",
    "mp.txt",
    "units_prod.txt",
    "player_rank_values.txt",
    "all_maps.txt",
    "new_maps.txt",
    "CE_maps.txt",
    "NORESUS CONQUEST ENHANCED.rar",
    "resource/script/multiplayer/modes/conquest.lua",
    "resource/script/multiplayer/modes/bot.ai_logic.lua",
    "resource/script/multiplayer/modes/bot.strategies.lua",
)

NESTED_DB_NAMES = (
    "noresus-project.db",
    "noresus-save.db",
    "noresus-anag.db",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_mod_info(path: Path) -> dict[str, str | None]:
    text = path.read_text(encoding="utf-8", errors="replace")

    def match(field: str) -> str | None:
        found = re.search(rf'\{{{re.escape(field)}\s+"([^"]*)"\}}', text)
        return found.group(1) if found else None

    return {
        "name": match("name"),
        "desc": match("desc"),
        "min_game_version": match("minGameVersion"),
        "max_game_version": match("maxGameVersion"),
    }


def _table_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for (name,) in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ):
        if name == "sqlite_sequence":
            continue
        columns = [
            {"name": row[1], "type": row[2]}
            for row in connection.execute(f'PRAGMA table_info("{name}")')
        ]
        count = connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        tables[name] = {"row_count": count, "columns": columns}
    return tables


def inspect_nested_archive(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "present": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256(path) if path.is_file() else "",
        "zip_compatible": False,
        "entries": {},
        "sqlite": {},
        "config": {},
    }
    if not path.is_file() or not zipfile.is_zipfile(path):
        return result
    result["zip_compatible"] = True
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = archive.read(info.filename)
            result["entries"][info.filename] = {
                "bytes": info.file_size,
                "sha256": sha256_bytes(data),
            }

        if "conquest.txt" in archive.namelist():
            text = archive.read("conquest.txt").decode("utf-8", errors="replace")
            config: dict[str, str] = {}
            for raw in text.splitlines():
                if not raw.strip() or "," not in raw:
                    continue
                key, value = raw.split(",", 1)
                config[key.strip()] = value.strip()
            result["config"] = config

        for db_name in NESTED_DB_NAMES:
            if db_name not in archive.namelist():
                continue
            data = archive.read(db_name)
            with tempfile.NamedTemporaryFile(suffix=".db") as handle:
                handle.write(data)
                handle.flush()
                connection = sqlite3.connect(handle.name)
                try:
                    result["sqlite"][db_name] = _table_summary(connection)
                finally:
                    connection.close()
    return result


def inspect_datamap_reset(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False}
    script = path.read_text(encoding="utf-8", errors="replace")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(script)
        rows = connection.execute(
            "SELECT cod, regione, nazione, confini, fazione, capitale, fronte, "
            "ic1, ic2, ic3, ic4, ic5 FROM datamap ORDER BY cod"
        ).fetchall()
    finally:
        connection.close()

    nation_counts = Counter(row[2] for row in rows)
    faction_counts = Counter(row[4] for row in rows)
    front_counts = Counter(row[6] for row in rows)
    degrees: list[int] = []
    isolated: list[dict[str, Any]] = []
    xs: list[int] = []
    ys: list[int] = []
    for row in rows:
        neighbors = [
            part.strip()
            for part in str(row[3] or "").strip(" ,").split(",")
            if part.strip() and part.strip() != "0"
        ]
        degrees.append(len(neighbors))
        if not neighbors:
            isolated.append({"id": row[0], "name": row[1]})
        for value in row[7:12]:
            numbers = re.findall(r"-?\d+", str(value or ""))
            if len(numbers) >= 2:
                xs.append(int(numbers[0]))
                ys.append(int(numbers[1]))

    return {
        "present": True,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "region_count": len(rows),
        "nation_counts": dict(nation_counts.most_common()),
        "faction_counts": {str(k): v for k, v in sorted(faction_counts.items())},
        "front_counts": {str(k): v for k, v in sorted(front_counts.items())},
        "capital_count": sum(bool(row[5]) for row in rows),
        "adjacency": {
            "average_degree": round(sum(degrees) / len(degrees), 6) if degrees else 0,
            "median_degree": statistics.median(degrees) if degrees else 0,
            "max_degree": max(degrees) if degrees else 0,
            "isolated": isolated,
        },
        "map_coordinate_range": {
            "x": [min(xs), max(xs)] if xs else [],
            "y": [min(ys), max(ys)] if ys else [],
            "sample_points": len(xs),
        },
    }


def inspect_units_prod(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False}
    rows = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip() or raw.lstrip().startswith("--"):
            continue
        fields = raw.split("\t")
        if len(fields) == 6:
            rows.append(fields)
    return {
        "present": True,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "row_count": len(rows),
        "side_counts": dict(Counter(row[0] for row in rows).most_common()),
        "field_count": 6,
    }


def _extract_lua_number(text: str, table: str, field: str) -> int | None:
    table_match = re.search(
        rf"local\s+{re.escape(table)}\s*=\s*\{{(.*?)\n\}}",
        text,
        flags=re.S,
    )
    if not table_match:
        return None
    match = re.search(rf"\b{re.escape(field)}\s*=\s*(\d+)\s*\*\s*1000", table_match.group(1))
    if match:
        return int(match.group(1))
    match = re.search(rf"\b{re.escape(field)}\s*=\s*(\d+)", table_match.group(1))
    return int(match.group(1)) if match else None


def inspect_tactical_scripts(root: Path) -> dict[str, Any]:
    conquest = root / "resource/script/multiplayer/modes/conquest.lua"
    strategies = root / "resource/script/multiplayer/modes/bot.strategies.lua"
    ai_logic = root / "resource/script/multiplayer/modes/bot.ai_logic.lua"
    result: dict[str, Any] = {}
    if conquest.is_file():
        text = conquest.read_text(encoding="utf-8", errors="replace")
        wave_match = re.search(r"local\s+WaveUnit\s*=\s*\{(.*?)\n\}", text, flags=re.S)
        wave_min = wave_max = None
        if wave_match:
            min_match = re.search(r"\bMin\s*=\s*(\d+)", wave_match.group(1))
            max_match = re.search(r"\bMax\s*=\s*(\d+)", wave_match.group(1))
            wave_min = int(min_match.group(1)) if min_match else None
            wave_max = int(max_match.group(1)) if max_match else None
        result["conquest"] = {
            "sha256": sha256(conquest),
            "wave_units": {"min": wave_min, "max": wave_max},
            "spawn_seconds": {
                "first_defender_min": _extract_lua_number(text, "StartSpawnTime", "DefenseMin"),
                "first_defender_max": _extract_lua_number(text, "StartSpawnTime", "DefenseMax"),
                "first_attacker_min": _extract_lua_number(text, "StartSpawnTime", "AttackMin"),
                "first_attacker_max": _extract_lua_number(text, "StartSpawnTime", "AttackMax"),
                "between_waves_min": _extract_lua_number(text, "SpawnCooldownTime", "DCGWaveOffMin"),
                "between_waves_max": _extract_lua_number(text, "SpawnCooldownTime", "DCGWaveOffMax"),
                "between_spawns_min": _extract_lua_number(text, "SpawnCooldownTime", "DCGMin"),
                "between_spawns_max": _extract_lua_number(text, "SpawnCooldownTime", "DCGMax"),
            },
            "wave_counter_enabled": "enableWaveCounter = true" in text,
        }
    if ai_logic.is_file():
        text = ai_logic.read_text(encoding="utf-8", errors="replace")
        result["ai_logic"] = {
            "sha256": sha256(ai_logic),
            "has_strategy_force_counts": "forceUnitCountMax" in text,
            "mentions_division_roster_specific_values": "division roster specific values" in text.lower(),
        }
    if strategies.is_file():
        text = strategies.read_text(encoding="utf-8", errors="replace")
        mappings: dict[str, list[int]] = {}
        for battalion_type in ("INF", "MOT", "MEC", "LT", "MT", "HT", "ART"):
            match = re.search(
                rf'neBattalionType\s*==\s*"{battalion_type}".*?PickRandomNumber\(\{{([^}}]+)\}}\)',
                text,
                flags=re.S,
            )
            if match:
                mappings[battalion_type] = [
                    int(value) for value in re.findall(r"\d+", match.group(1))
                ]
        result["strategies"] = {
            "sha256": sha256(strategies),
            "battalion_type_strategy_indexes": mappings,
        }
    return result


def inspect_readme(root: Path) -> dict[str, bool]:
    text = ""
    nested_archive = root / "NORESUS CONQUEST ENHANCED.rar"
    if nested_archive.is_file() and zipfile.is_zipfile(nested_archive):
        with zipfile.ZipFile(nested_archive) as archive:
            if "READ ME FIRST.txt" in archive.namelist():
                text = archive.read("READ ME FIRST.txt").decode("utf-8", errors="replace")
    if not text and (root / "READ ME FIRST.txt").is_file():
        text = (root / "READ ME FIRST.txt").read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    return {
        "describes_external_strategic_layer": "strategic" in lowered and "tactical" in lowered,
        "describes_generated_noresus_battle": "noresus battle" in lowered,
        "describes_automatic_goh_launch": "starts goh" in lowered or "start goh" in lowered,
        "describes_return_and_update": "return to the europa map" in lowered and "updating everything" in lowered,
        "describes_mod_activation": "automatically activate the mods" in lowered,
    }


def build_report(root: Path) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir():
        raise SystemExit(f"NORESUS reference root does not exist: {root}")

    mod_info = root / "mod.info"
    if not mod_info.is_file():
        raise SystemExit(f"Reference root is missing mod.info: {root}")

    files = sorted(path for path in root.rglob("*") if path.is_file())
    extensions: Counter[str] = Counter()
    top_level: Counter[str] = Counter()
    total_bytes = 0

    for path in files:
        relative = path.relative_to(root)
        total_bytes += path.stat().st_size
        suffix = path.suffix.lower() or "<none>"
        extensions[suffix] += 1
        top_level[relative.parts[0]] += 1

    key_files: dict[str, object] = {}
    for relative_name in KEY_PATHS:
        path = root / relative_name
        if not path.is_file():
            key_files[relative_name] = {"present": False}
            continue
        key_files[relative_name] = {
            "present": True,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }

    nested = inspect_nested_archive(root / "NORESUS CONQUEST ENHANCED.rar")
    return {
        "identity": parse_mod_info(mod_info),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "top_level_counts": dict(top_level.most_common()),
        "extension_counts": dict(extensions.most_common()),
        "key_files": key_files,
        "strategic_map": inspect_datamap_reset(root / "datamap_reset.sql"),
        "unit_catalog": inspect_units_prod(root / "units_prod.txt"),
        "nested_runtime": nested,
        "readme_contract": inspect_readme(root),
        "tactical_scripts": inspect_tactical_scripts(root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a clean-room metadata and schema report for a local NORESUS Strategic Map "
            "Workshop installation without copying third-party content into the repository."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Path to Workshop item 3180617465 or an equivalent local reference snapshot.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Defaults to stdout.",
    )
    args = parser.parse_args()

    report = build_report(args.root)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
