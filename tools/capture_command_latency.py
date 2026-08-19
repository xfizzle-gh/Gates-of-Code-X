#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
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
    return {
        "exists": True,
        "path": str(path),
        "bytes": len(raw),
        "read_ms": read_ms,
        "parse_ms": _ms(t1),
        "top_keys": len(parsed) if isinstance(parsed, dict) else 0,
    }


def _occupied_factions(snapshot: dict[str, Any]) -> dict[str, set[str]]:
    occupied: dict[str, set[str]] = {}
    for row in snapshot.get("battalions", []):
        if not isinstance(row, dict):
            continue
        occupied.setdefault(str(row.get("province_id", "")), set()).add(str(row.get("faction", "")))
    return occupied


def _pick_order(snapshot: dict[str, Any], *, hostile_destination: bool = False) -> dict[str, Any] | None:
    current = str((snapshot.get("campaign") or {}).get("current_faction", ""))
    formations = {str(row.get("id", "")): row for row in snapshot.get("strategic_formations", [])}
    occupied = _occupied_factions(snapshot)
    candidates: list[dict[str, Any]] = []
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
        target = str(row.get("target_province_id", ""))
        occupants = occupied.get(target, set())
        hostile = bool(occupants - {str(row.get("faction", current))})
        if hostile_destination and not hostile:
            continue
        candidates.append({
            "formation": str(row.get("formation_id", "")),
            "path_node_ids": nodes,
            "path_edge_ids": edges,
            "target_province_id": target,
            "faction": str(row.get("faction", current)),
            "locked_stance": str(row.get("locked_stance", "operational")),
            "hop_count": int(row.get("hop_count") or len(edges)),
            "hostile_destination": hostile,
        })
    if not candidates:
        return None
    if hostile_destination:
        candidates.sort(key=lambda row: int(row.get("hop_count", 99)))
    return candidates[0]


def _install() -> None:
    from gates_of_codex.command_cycle_perf import install_command_cycle_perf_path
    from gates_of_codex.command_scoped_p2_auth import install_command_scoped_p2_auth
    from gates_of_codex.frontend_fastpath import install_frontend_fast_path
    from gates_of_codex.turn_cycle import install_frontend_turn_cycle_op

    install_frontend_fast_path()
    install_frontend_turn_cycle_op()
    install_command_cycle_perf_path()
    install_command_scoped_p2_auth()


def _fresh_copy(source_campaign: Path, dest_dir: Path) -> dict[str, Path]:
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)
    campaign = dest_dir / "campaign.json"
    snapshot = dest_dir / "campaign_snapshot.json"
    commands = dest_dir / "frontend_commands.json"
    shutil.copy2(source_campaign, campaign)
    sibling = source_campaign.parent / "campaign_snapshot.json"
    if sibling.is_file():
        shutil.copy2(sibling, snapshot)
    commands.write_text('{"commands":[]}\n', encoding="utf-8")
    session = dest_dir / ".goc-backend-session.json"
    if session.exists():
        session.unlink()
    from gates_of_codex.frontend import write_frontend_snapshot
    from gates_of_codex.state_io import load_campaign

    write_frontend_snapshot(load_campaign(campaign), snapshot, campaign_path=campaign)
    return {"campaign": campaign, "snapshot": snapshot, "commands": commands}


def _clone_prepared(src: Path, dest: Path) -> dict[str, Path]:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    session = dest / ".goc-backend-session.json"
    if session.exists():
        session.unlink()
    return {
        "campaign": dest / "campaign.json",
        "snapshot": dest / "campaign_snapshot.json",
        "commands": dest / "frontend_commands.json",
    }


def _apply_inprocess(campaign: Path, snapshot: Path, commands: list[dict[str, Any]]) -> dict[str, Any]:
    from gates_of_codex.frontend_commands import apply_frontend_commands

    t0 = time.perf_counter()
    result = dict(apply_frontend_commands(campaign, commands=commands, snapshot_path=snapshot))
    result["wall_ms"] = _ms(t0)
    result["mode"] = "in_process"
    return result


def _parse_subprocess_payload(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("ok" in parsed or "timings" in parsed):
            return parsed
    return {}


def _apply_subprocess(
    python: Path,
    campaign: Path,
    snapshot: Path,
    commands_path: Path,
    commands: list[dict[str, Any]],
) -> dict[str, Any]:
    commands_path.write_text(json.dumps({"commands": commands}, indent=2) + "\n", encoding="utf-8")
    t0 = time.perf_counter()
    completed = subprocess.run(
        [
            str(python),
            "-m",
            "gates_of_codex",
            "apply-frontend",
            str(campaign),
            "--snapshot",
            str(snapshot),
            "--commands",
            str(commands_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    wall = _ms(t0)
    payload = _parse_subprocess_payload(completed.stdout)
    payload["wall_ms"] = wall
    payload["mode"] = "subprocess"
    payload["returncode"] = completed.returncode
    if "ok" not in payload:
        payload["ok"] = completed.returncode == 0
        payload["error"] = (completed.stderr or completed.stdout)[-800:]
    return payload


def _summarize(name: str, result: dict[str, Any], snapshot: Path) -> dict[str, Any]:
    timings = result.get("timings") or {}
    return {
        "name": name,
        "mode": result.get("mode"),
        "ok": bool(result.get("ok", False)),
        "ops": [str(row.get("op", "")) for row in result.get("results", []) if isinstance(row, dict)],
        "wall_ms": result.get("wall_ms"),
        "backend": {
            "load_ms": timings.get("load_ms"),
            "mutate_ms": timings.get("mutate_ms"),
            "save_ms": timings.get("save_ms"),
            "snapshot_ms": timings.get("snapshot_ms"),
            "total_ms": timings.get("total_ms"),
            "snapshot_fast_path": timings.get("snapshot_fast_path"),
            "runtime_patch_fast_path": timings.get("runtime_patch_fast_path"),
        },
        "snapshot_io": _file_io(snapshot),
        "pending_battle": result.get("pending_battle") is not None
        if "pending_battle" in result
        else None,
        "error": None if result.get("ok", False) else result.get("error", result.get("results")),
    }


def _godot_reload(godot: Path, repo: Path, snapshot: Path, out_path: Path) -> dict[str, Any]:
    if not godot.is_file():
        return {"ok": False, "error": "godot missing"}
    t0 = time.perf_counter()
    completed = subprocess.run(
        [
            str(godot),
            "--headless",
            "--path",
            str(repo / "godot"),
            "--audio-driver",
            "Dummy",
            "-s",
            "res://scripts/tools/map_command_reload_latency.gd",
            "--",
            f"--snapshot={snapshot}",
            f"--out={out_path}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    wall = _ms(t0)
    if out_path.is_file():
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        payload["subprocess_wall_ms"] = wall
        return payload
    return {"ok": False, "error": completed.stderr[-400:] or completed.stdout[-400:], "subprocess_wall_ms": wall}


def _has_pending(snapshot: Path) -> bool:
    payload = json.loads(snapshot.read_text(encoding="utf-8-sig"))
    return payload.get("pending_battle") is not None


def _current_faction(snapshot: Path) -> str:
    payload = json.loads(snapshot.read_text(encoding="utf-8-sig"))
    return str((payload.get("campaign") or {}).get("current_faction", ""))


def capture(source_campaign: Path, work: Path, python: Path, godot: Path, repo: Path) -> dict[str, Any]:
    _install()
    base = _fresh_copy(source_campaign, work / "base")
    snapshot0 = json.loads(base["snapshot"].read_text(encoding="utf-8-sig"))
    order = _pick_order(snapshot0)
    isolated: list[dict[str, Any]] = []

    def measure(name: str, commands: list[dict[str, Any]], prepared: Path | None = None) -> dict[str, Any]:
        in_dir = work / f"{name}-inprocess"
        sub_dir = work / f"{name}-subprocess"
        src = prepared or base["campaign"].parent
        in_paths = _clone_prepared(src, in_dir)
        in_result = _apply_inprocess(in_paths["campaign"], in_paths["snapshot"], commands)
        in_row = _summarize(name, in_result, in_paths["snapshot"])
        sub_paths = _clone_prepared(src, sub_dir)
        sub_result = _apply_subprocess(python, sub_paths["campaign"], sub_paths["snapshot"], sub_paths["commands"], commands)
        sub_row = _summarize(name, sub_result, sub_paths["snapshot"])
        launch_ms = None
        if in_row.get("wall_ms") is not None and sub_row.get("wall_ms") is not None:
            launch_ms = round(float(sub_row["wall_ms"]) - float(in_row["wall_ms"]), 3)
        godot_row = _godot_reload(godot, repo, in_paths["snapshot"], work / f"{name}-godot.json")
        row = {
            "name": name,
            "commands": commands,
            "in_process": in_row,
            "subprocess": sub_row,
            "subprocess_overhead_ms": launch_ms,
            "godot_reload": godot_row,
        }
        isolated.append(row)
        return row

    if order is not None:
        batch = [
            {
                "op": "issue_move_order",
                "formation": order["formation"],
                "path_node_ids": order["path_node_ids"],
                "path_edge_ids": order["path_edge_ids"],
            },
            {
                "op": "commit_move_orders",
                "faction": order["faction"],
                "locked_stance": order["locked_stance"],
            },
        ]
        measure("move_click_batch", batch)
        measure(
            "issue_move_order_only",
            [{"op": "issue_move_order", "formation": order["formation"], "path_node_ids": order["path_node_ids"], "path_edge_ids": order["path_edge_ids"]}],
        )
        measure(
            "commit_move_orders_only",
            [{"op": "commit_move_orders", "faction": order["faction"], "locked_stance": order["locked_stance"]}],
        )
    else:
        isolated.append({"name": "move_click_batch", "ok": False, "error": "no legal operational_orders"})

    measure("refresh", [{"op": "refresh"}])
    measure("end_turn", [{"op": "end_turn"}])
    faction = _current_faction(base["snapshot"])
    measure("run_ai", [{"op": "run_ai", "faction": faction, "advance_turn": True}])

    prelude = _clone_prepared(base["campaign"].parent, work / "prelude")
    contact_ready = None
    prelude_ops: list[str] = []
    contact_order = _pick_order(json.loads(prelude["snapshot"].read_text(encoding="utf-8-sig")), hostile_destination=True)
    if contact_order is not None:
        _apply_inprocess(
            prelude["campaign"],
            prelude["snapshot"],
            [
                {
                    "op": "issue_move_order",
                    "formation": contact_order["formation"],
                    "path_node_ids": contact_order["path_node_ids"],
                    "path_edge_ids": contact_order["path_edge_ids"],
                },
                {
                    "op": "commit_move_orders",
                    "faction": contact_order["faction"],
                    "locked_stance": contact_order["locked_stance"],
                },
            ],
        )
        prelude_ops.append("issue+commit_hostile_route")
        hops = max(1, int(contact_order.get("hop_count", 1)))
        _apply_inprocess(
            prelude["campaign"],
            prelude["snapshot"],
            [{"op": "advance_operational_tick", "count": hops}],
        )
        prelude_ops.append(f"advance_operational_tick:{hops}")
    for _i in range(8):
        if _has_pending(prelude["snapshot"]):
            contact_ready = prelude["campaign"].parent
            break
        _apply_inprocess(prelude["campaign"], prelude["snapshot"], [{"op": "end_player_round"}])
        prelude_ops.append("end_player_round")
        if _has_pending(prelude["snapshot"]):
            contact_ready = prelude["campaign"].parent
            break
    if contact_ready is not None:
        measure("auto_resolve", [{"op": "auto_resolve"}], prepared=contact_ready)
    else:
        isolated.append({"name": "auto_resolve", "ok": False, "error": "prelude did not produce pending_battle", "prelude_ops": prelude_ops})

    loop_dir = work / "realistic-loop"
    loop_paths = _clone_prepared(base["campaign"].parent, loop_dir)
    loop_t0 = time.perf_counter()
    loop_trace: list[dict[str, Any]] = []
    if order is not None:
        loop_trace.append(
            _summarize(
                "move_click_batch",
                _apply_inprocess(
                    loop_paths["campaign"],
                    loop_paths["snapshot"],
                    [
                        {
                            "op": "issue_move_order",
                            "formation": order["formation"],
                            "path_node_ids": order["path_node_ids"],
                            "path_edge_ids": order["path_edge_ids"],
                        },
                        {
                            "op": "commit_move_orders",
                            "faction": order["faction"],
                            "locked_stance": order["locked_stance"],
                        },
                    ],
                ),
                loop_paths["snapshot"],
            )
        )
    loop_trace.append(
        _summarize(
            "end_turn",
            _apply_inprocess(loop_paths["campaign"], loop_paths["snapshot"], [{"op": "end_turn"}]),
            loop_paths["snapshot"],
        )
    )
    loop_trace.append(
        _summarize(
            "run_ai",
            _apply_inprocess(
                loop_paths["campaign"],
                loop_paths["snapshot"],
                [{"op": "run_ai", "faction": _current_faction(loop_paths["snapshot"]), "advance_turn": True}],
            ),
            loop_paths["snapshot"],
        )
    )
    if not _has_pending(loop_paths["snapshot"]):
        loop_trace.append(
            _summarize(
                "end_player_round_until_contact",
                _apply_inprocess(loop_paths["campaign"], loop_paths["snapshot"], [{"op": "end_player_round"}]),
                loop_paths["snapshot"],
            )
        )
    if _has_pending(loop_paths["snapshot"]):
        loop_trace.append(
            _summarize(
                "auto_resolve",
                _apply_inprocess(loop_paths["campaign"], loop_paths["snapshot"], [{"op": "auto_resolve"}]),
                loop_paths["snapshot"],
            )
        )
    loop_godot = _godot_reload(godot, repo, loop_paths["snapshot"], work / "loop-godot.json")
    return {
        "schema": "gates-of-codex.command-latency-capture",
        "schema_version": 2,
        "provisional_v1_note": "v1 table mixed non-production command shapes and in-process-only apply.",
        "read_only_owner": True,
        "source_campaign": str(source_campaign),
        "selected_order": order,
        "isolated": isolated,
        "realistic_loop": {
            "wall_ms": _ms(loop_t0),
            "trace": loop_trace,
            "godot_reload": loop_godot,
            "pending_battle_at_end": _has_pending(loop_paths["snapshot"]),
        },
        "prelude_ops_to_contact": prelude_ops,
        "notes": [
            "move_click_batch is the player-facing move click: issue+commit in one apply.",
            "end_turn is the exact main.gd button payload. Live E is remapped by main_perf to end_player_round; that remap is used only as contact prelude.",
            "run_ai uses faction + advance_turn:true.",
            "auto_resolve is timed after a separate prelude that is not included in its wall.",
            "subprocess_overhead_ms = subprocess wall - in-process wall.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Production-shaped command latency capture. Mutates a copy only.")
    parser.add_argument("--source-campaign", default="")
    parser.add_argument("--copy-dir", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--godot", default="")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    if args.source_campaign:
        source = Path(args.source_campaign)
    else:
        pointer = Path.home() / "AppData/Local/GatesOfCodeX/last_campaign.json"
        source = Path(str(json.loads(pointer.read_text(encoding="utf-8"))["campaign_path"]))
    dest = Path(args.copy_dir) if args.copy_dir else Path(args.out).parent / "command-latency-work"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    godot = Path(args.godot) if args.godot else Path(r"C:\Users\paulf\tools\godot\Godot_v4.7-stable_win64.exe")
    payload = capture(source, dest, Path(args.python), godot, Path(args.repo))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "out": str(out),
        "isolated": [
            {
                "name": row.get("name"),
                "in_process_ms": (row.get("in_process") or {}).get("wall_ms"),
                "subprocess_ms": (row.get("subprocess") or {}).get("wall_ms"),
                "overhead_ms": row.get("subprocess_overhead_ms"),
                "godot_ms": (row.get("godot_reload") or {}).get("first_visible_ms")
                or (row.get("godot_reload") or {}).get("total_ms"),
            }
            for row in payload.get("isolated", [])
            if isinstance(row, dict)
        ],
        "realistic_loop_ms": payload.get("realistic_loop", {}).get("wall_ms"),
    }
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
