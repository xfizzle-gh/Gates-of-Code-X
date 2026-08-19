#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _file_io(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path)}
    t0 = time.perf_counter()
    raw = path.read_bytes()
    read_ms = _ms(t0)
    t1 = time.perf_counter()
    parsed = json.loads(raw.decode("utf-8-sig"))
    parse_ms = _ms(t1)
    return {
        "exists": True,
        "path": str(path),
        "bytes": len(raw),
        "read_ms": read_ms,
        "parse_ms": parse_ms,
        "top_keys": len(parsed) if isinstance(parsed, dict) else 0,
    }


def _pick_order(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    current = str((snapshot.get("campaign") or {}).get("current_faction", ""))
    formations = {str(row.get("id", "")): row for row in snapshot.get("strategic_formations", [])}
    for row in snapshot.get("operational_orders", []):
        if not isinstance(row, dict):
            continue
        force = formations.get(str(row.get("formation_id", "")))
        if not force or str(force.get("faction", "")) != current:
            continue
        status = str((force.get("move_order") or {}).get("status", "")).lower()
        if status in {"draft", "committed", "active"}:
            continue
        nodes = list(row.get("path_node_ids") or [])
        edges = list(row.get("path_edge_ids") or [])
        if len(nodes) < 2 or len(edges) != len(nodes) - 1:
            continue
        return {
            "formation": str(row.get("formation_id", "")),
            "path_node_ids": nodes,
            "path_edge_ids": edges,
            "target_province_id": str(row.get("target_province_id", "")),
            "faction": str(row.get("faction", current)),
            "locked_stance": str(row.get("locked_stance", "operational")),
        }
    return None


def _install() -> None:
    from gates_of_codex.command_cycle_perf import install_command_cycle_perf_path
    from gates_of_codex.command_scoped_p2_auth import install_command_scoped_p2_auth
    from gates_of_codex.frontend_fastpath import install_frontend_fast_path
    from gates_of_codex.turn_cycle import install_frontend_turn_cycle_op

    install_frontend_fast_path()
    install_frontend_turn_cycle_op()
    install_command_cycle_perf_path()
    install_command_scoped_p2_auth()


def _apply(campaign: Path, snapshot: Path, commands: list[dict[str, Any]]) -> dict[str, Any]:
    from gates_of_codex.frontend_commands import apply_frontend_commands

    t0 = time.perf_counter()
    result = apply_frontend_commands(campaign, commands=commands, snapshot_path=snapshot)
    result = dict(result)
    result["wall_ms"] = _ms(t0)
    result["after_campaign"] = _file_io(campaign)
    result["after_snapshot"] = _file_io(snapshot)
    return result


def _summarize(name: str, result: dict[str, Any]) -> dict[str, Any]:
    timings = result.get("timings") or {}
    return {
        "name": name,
        "ok": bool(result.get("ok", False)),
        "ops": [str(row.get("op", "")) for row in result.get("results", []) if isinstance(row, dict)],
        "wall_ms": result.get("wall_ms"),
        "backend": {
            "load_ms": timings.get("load_ms"),
            "mutate_ms": timings.get("mutate_ms"),
            "save_ms": timings.get("save_ms"),
            "snapshot_ms": timings.get("snapshot_ms"),
            "total_ms": timings.get("total_ms"),
            "campaign_bytes": timings.get("campaign_bytes"),
            "snapshot_bytes": timings.get("snapshot_bytes"),
            "snapshot_fast_path": timings.get("snapshot_fast_path"),
            "runtime_patch_fast_path": timings.get("runtime_patch_fast_path"),
            "read_only_fast_path": timings.get("read_only_fast_path"),
            "turn_cycle": timings.get("turn_cycle"),
        },
        "campaign_io": result.get("after_campaign"),
        "snapshot_io": result.get("after_snapshot"),
        "pending_battle": result.get("pending_battle") is not None,
        "current_faction": result.get("current_faction"),
        "turn_number": result.get("turn_number"),
        "error": None if result.get("ok", False) else result.get("results", result.get("error")),
    }


def prepare_copy(source_campaign: Path, dest_dir: Path) -> dict[str, Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    campaign = dest_dir / "campaign.json"
    snapshot = dest_dir / "campaign_snapshot.json"
    commands = dest_dir / "frontend_commands.json"
    source_snapshot = source_campaign.parent / "campaign_snapshot.json"
    shutil.copy2(source_campaign, campaign)
    if source_snapshot.is_file():
        shutil.copy2(source_snapshot, snapshot)
    commands.write_text('{"commands":[]}\n', encoding="utf-8")
    session = dest_dir / ".goc-backend-session.json"
    if session.exists():
        session.unlink()
    from gates_of_codex.frontend import write_frontend_snapshot
    from gates_of_codex.frontend_fastpath import install_frontend_fast_path
    from gates_of_codex.state_io import load_campaign

    install_frontend_fast_path()
    t0 = time.perf_counter()
    state = load_campaign(campaign)
    write_frontend_snapshot(state, snapshot, campaign_path=campaign)
    rebound_ms = _ms(t0)
    return {
        "campaign": campaign,
        "snapshot": snapshot,
        "commands": commands,
        "rebind_ms": rebound_ms,
    }


def capture(campaign: Path, snapshot: Path) -> dict[str, Any]:
    _install()
    baseline_campaign = _file_io(campaign)
    baseline_snapshot = _file_io(snapshot)
    snap = json.loads(snapshot.read_text(encoding="utf-8-sig"))
    order = _pick_order(snap)
    operations: list[dict[str, Any]] = []

    if order is not None:
        issue = _apply(
            campaign,
            snapshot,
            [
                {
                    "op": "issue_move_order",
                    "formation": order["formation"],
                    "path_node_ids": order["path_node_ids"],
                    "path_edge_ids": order["path_edge_ids"],
                }
            ],
        )
        operations.append(_summarize("issue_move_order", issue))
        commit = _apply(
            campaign,
            snapshot,
            [
                {
                    "op": "commit_move_orders",
                    "faction": order["faction"],
                    "locked_stance": order["locked_stance"],
                }
            ],
        )
        operations.append(_summarize("commit_move_orders", commit))
    else:
        operations.append({"name": "issue_move_order", "ok": False, "error": "no legal operational_orders"})
        operations.append({"name": "commit_move_orders", "ok": False, "error": "skipped"})

    refresh = _apply(campaign, snapshot, [{"op": "refresh"}])
    operations.append(_summarize("refresh", refresh))

    end_turn = _apply(campaign, snapshot, [{"op": "end_player_round"}])
    operations.append(_summarize("end_player_round", end_turn))

    after_turn = json.loads(snapshot.read_text(encoding="utf-8-sig"))
    pending = after_turn.get("pending_battle")
    if pending is None:
        run_ai = _apply(campaign, snapshot, [{"op": "run_ai", "advance_turn": False}])
        operations.append(_summarize("run_ai", run_ai))
        after_ai = json.loads(snapshot.read_text(encoding="utf-8-sig"))
        pending = after_ai.get("pending_battle")
    else:
        operations.append({"name": "run_ai", "ok": True, "skipped": True, "reason": "pending_battle already present"})

    if pending is not None:
        auto = _apply(campaign, snapshot, [{"op": "auto_resolve"}])
        operations.append(_summarize("auto_resolve", auto))
    else:
        operations.append({"name": "auto_resolve", "ok": False, "error": "no pending_battle after turn/AI"})

    dominant = []
    for row in operations:
        backend = row.get("backend") or {}
        phases = {
            "load": backend.get("load_ms") or 0.0,
            "mutate": backend.get("mutate_ms") or 0.0,
            "save": backend.get("save_ms") or 0.0,
            "snapshot": backend.get("snapshot_ms") or 0.0,
        }
        winner = max(phases, key=phases.get) if any(phases.values()) else "unknown"
        dominant.append({"name": row.get("name"), "dominant_phase": winner, "phases": phases, "wall_ms": row.get("wall_ms")})

    return {
        "schema": "gates-of-codex.command-latency-capture",
        "schema_version": 1,
        "read_only_owner": True,
        "campaign_path": str(campaign),
        "snapshot_path": str(snapshot),
        "baseline": {"campaign": baseline_campaign, "snapshot": baseline_snapshot},
        "selected_order": order,
        "operations": operations,
        "dominant": dominant,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure command latency on a disposable campaign copy.")
    parser.add_argument("--source-campaign", default="")
    parser.add_argument("--copy-dir", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.source_campaign:
        source = Path(args.source_campaign)
    else:
        pointer = Path.home().joinpath("AppData/Local/GatesOfCodeX/last_campaign.json")
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        source = Path(str(payload["campaign_path"]))
    if not source.is_file():
        raise SystemExit(f"source campaign missing: {source}")
    dest = Path(args.copy_dir) if args.copy_dir else Path(args.out).with_suffix("").parent / "command-latency-copy"
    if dest.exists():
        shutil.rmtree(dest)
    prepared = prepare_copy(source, dest)
    payload = capture(prepared["campaign"], prepared["snapshot"])
    payload["source_campaign"] = str(source)
    payload["copy_dir"] = str(dest)
    payload["snapshot_rebind_ms"] = prepared.get("rebind_ms")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps({"out": str(out), "dominant": payload["dominant"], "baseline": payload["baseline"]}, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
