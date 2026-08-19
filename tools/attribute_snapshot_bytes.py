#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _encoded_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _count(value: Any) -> int | None:
    if isinstance(value, (list, dict, str)):
        return len(value)
    return None


def _dict_field_bytes(row: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = sorted(
        ((str(key), _encoded_bytes(value), _count(value), type(value).__name__) for key, value in row.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return [
        {"key": key, "bytes": size, "count": count, "kind": kind}
        for key, size, count, kind in ranked
    ]


def _record_field_bytes(rows: list[Any]) -> list[dict[str, Any]]:
    field_bytes: dict[str, int] = defaultdict(int)
    field_items: dict[str, int] = defaultdict(int)
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            field_bytes[str(key)] += _encoded_bytes(value)
            if isinstance(value, list):
                field_items[str(key)] += len(value)
    ranked = sorted(field_bytes.items(), key=lambda item: item[1], reverse=True)
    return [
        {"key": key, "bytes": size, "list_items": field_items.get(key, 0)}
        for key, size in ranked
    ]


def _order_field_bytes(orders: list[Any]) -> dict[str, Any]:
    field_bytes: dict[str, int] = defaultdict(int)
    field_items: dict[str, int] = defaultdict(int)
    formations: set[str] = set()
    destinations: set[str] = set()
    origins: set[str] = set()
    for row in orders:
        if not isinstance(row, dict):
            continue
        formations.add(str(row.get("formation_id", "")))
        destinations.add(str(row.get("target_province_id", "")))
        origins.add(str(row.get("origin_province_id", "")))
        for key, value in row.items():
            field_bytes[str(key)] += _encoded_bytes(value)
            if isinstance(value, list):
                field_items[str(key)] += len(value)
    ranked = sorted(field_bytes.items(), key=lambda item: item[1], reverse=True)
    return {
        "count": len(orders),
        "unique_formations": len(formations - {""}),
        "unique_origins": len(origins - {""}),
        "unique_destinations": len(destinations - {""}),
        "field_bytes": [
            {"key": key, "bytes": size, "list_items": field_items.get(key, 0)}
            for key, size in ranked
        ],
    }


def attribute_snapshot(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    keys = []
    for key, value in payload.items():
        keys.append(
            {
                "key": str(key),
                "bytes": _encoded_bytes(value),
                "kind": type(value).__name__,
                "count": _count(value),
            }
        )
    keys.sort(key=lambda row: int(row["bytes"]), reverse=True)
    orders = payload.get("operational_orders", [])
    campaign = payload.get("campaign", {})
    provinces = payload.get("provinces", [])
    compact = _encoded_bytes(payload)
    return {
        "path": str(path),
        "file_bytes": len(raw),
        "compact_bytes": compact,
        "top_keys": keys,
        "campaign": _dict_field_bytes(campaign) if isinstance(campaign, dict) else [],
        "provinces": _record_field_bytes(provinces if isinstance(provinces, list) else []),
        "operational_orders": _order_field_bytes(orders if isinstance(orders, list) else []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="PASS 1: snapshot JSON byte attribution. Read-only.")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--fixture", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    owner = attribute_snapshot(Path(args.snapshot))
    payload = {
        "schema": "gates-of-codex.overmap-snapshot-bytes",
        "schema_version": 1,
        "read_only": True,
        "owner": owner,
    }
    if args.fixture:
        payload["fixture"] = attribute_snapshot(Path(args.fixture))
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
