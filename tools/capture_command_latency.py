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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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


def _player_visible(sub_row: dict[str, Any], godot_row: dict[str, Any]) -> dict[str, Any]:
    sub_ms = sub_row.get("wall_ms")
    reload_ms = godot_row.get("reload_to_visible_ms")
    if reload_ms is None:
        reload_ms = godot_row.get("total_ms")
    input_ms = None
    if sub_ms is not None and reload_ms is not None:
        input_ms = round(float(sub_ms) + float(reload_ms), 3)
    return {
        "subprocess_ms": sub_ms,
        "godot_reload_to_visible_ms": reload_ms,
        "godot_draw_ms": godot_row.get("draw_ms"),
        "input_to_visible_ms": input_ms,
        "note": "input_to_visible_ms = subprocess apply + full Godot reload; draw_ms is only the last frame.",
    }


def _place_at_node(state: Any, force: Any, node: dict[str, Any]) -> None:
    from gates_of_codex.operational_schema import FormationOperationalPosition, PositionMode

    node_id = str(node.get("node_id") or "")
    province_id = str(node.get("province_id") or force.province_id)
    force.position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value,
        node_id=node_id,
        edge_id=None,
        progress_milli=0,
        facing_node_id=None,
    )
    force.province_id = province_id
    force.movement_state = "at_anchor"
    force.move_order = None
    for battalion_id in force.battalion_ids:
        battalion = state.battalions.get(battalion_id)
        if battalion is not None:
            battalion.province_id = province_id


def _create_prepared_contact_on_pair(
    state: Any,
    *,
    attacker_id: str,
    defender_id: str,
    path_node_ids: list[str],
    path_edge_ids: list[str],
) -> dict[str, Any]:
    from gates_of_codex.operational_movement import (
        activate_committed_orders,
        advance_operational_tick,
        commit_move_orders,
        issue_move_order,
    )
    from gates_of_codex.operational_schema import FormationStance

    defender = state.strategic_formations[defender_id]
    defender.stance = FormationStance.AMBUSH.value
    defender.ambush_ready_tick = 0
    issue_move_order(
        state,
        attacker_id,
        path_node_ids=list(path_node_ids),
        path_edge_ids=list(path_edge_ids),
        order_id="ord-latency-contact",
    )
    commit_move_orders(state)
    activate_committed_orders(state)
    ticks = 0
    while state.pending_battle is None and ticks < 20:
        advance_operational_tick(state)
        ticks += 1
    if state.pending_battle is None:
        raise RuntimeError("prepared node contact did not create pending_battle")
    return {"ticks_advanced": ticks, "attacker": attacker_id, "defender": defender_id}


def _usable_edges(graph: dict[str, Any]) -> list[tuple[str, str, str]]:
    edges: list[tuple[str, str, str]] = []
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        if edge.get("traversal_enabled") is False:
            continue
        edge_id = str(edge.get("edge_id") or "")
        left = str(edge.get("a") or "")
        right = str(edge.get("b") or "")
        if edge_id and left and right:
            edges.append((edge_id, left, right))
    return edges


def _prepare_owner_size_contact(src: Path, dest: Path) -> dict[str, Any]:
    from gates_of_codex.diplomacy import are_allied
    from gates_of_codex.frontend import write_frontend_snapshot
    from gates_of_codex.operational_contact import formation_at_node_id
    from gates_of_codex.operational_position import load_operational_graph_for_state
    from gates_of_codex.state_io import load_campaign, save_campaign

    started = time.perf_counter()
    paths = _clone_prepared(src, dest)
    state = load_campaign(paths["campaign"])
    graph = load_operational_graph_for_state(state)
    if graph is None:
        raise RuntimeError("operational graph unavailable")
    player = state.selected_faction or state.current_faction
    occupied: dict[str, list[Any]] = {}
    attackers: list[Any] = []
    defenders: list[Any] = []
    for force in state.strategic_formations.values():
        node_id = formation_at_node_id(force)
        if node_id:
            occupied.setdefault(node_id, []).append(force)
        if force.faction == player:
            attackers.append(force)
        elif not are_allied(state, player, force.faction):
            defenders.append(force)
    nodes_by_id = {
        str(row.get("node_id")): row
        for row in graph.get("nodes") or []
        if isinstance(row, dict) and row.get("node_id")
    }
    pair: dict[str, Any] | None = None
    for edge_id, left, right in _usable_edges(graph):
        for origin, dest_node in ((left, right), (right, left)):
            for attacker in occupied.get(origin, []):
                if attacker.faction != player:
                    continue
                for defender in occupied.get(dest_node, []):
                    if are_allied(state, attacker.faction, defender.faction):
                        continue
                    pair = {
                        "attacker": attacker,
                        "defender": defender,
                        "path_node_ids": [origin, dest_node],
                        "path_edge_ids": [edge_id],
                        "placed": False,
                    }
                    break
                if pair is not None:
                    break
            if pair is not None:
                break
        if pair is not None:
            break
    if pair is None:
        if not attackers or not defenders:
            raise RuntimeError("no attacker/defender pair for synthetic contact")
        occupied_nodes = set(occupied)
        chosen: tuple[str, str, str] | None = None
        for edge_id, left, right in _usable_edges(graph):
            if left in nodes_by_id and right in nodes_by_id and left not in occupied_nodes and right not in occupied_nodes:
                chosen = (edge_id, left, right)
                break
        if chosen is None:
            unused = [node_id for node_id in nodes_by_id if node_id not in occupied_nodes]
            park = 0
            for edge_id, left, right in _usable_edges(graph):
                if left not in nodes_by_id or right not in nodes_by_id:
                    continue
                for occupant in list(occupied.get(left, [])) + list(occupied.get(right, [])):
                    if park >= len(unused):
                        break
                    _place_at_node(state, occupant, nodes_by_id[unused[park]])
                    park += 1
                chosen = (edge_id, left, right)
                break
        if chosen is None:
            raise RuntimeError("no traversable edge for synthetic contact")
        edge_id, origin, dest_node = chosen
        attacker = attackers[0]
        defender = defenders[0]
        _place_at_node(state, attacker, nodes_by_id[origin])
        _place_at_node(state, defender, nodes_by_id[dest_node])
        pair = {
            "attacker": attacker,
            "defender": defender,
            "path_node_ids": [origin, dest_node],
            "path_edge_ids": [edge_id],
            "placed": True,
        }
    contact = _create_prepared_contact_on_pair(
        state,
        attacker_id=pair["attacker"].strategic_formation_id,
        defender_id=pair["defender"].strategic_formation_id,
        path_node_ids=pair["path_node_ids"],
        path_edge_ids=pair["path_edge_ids"],
    )
    save_campaign(state, paths["campaign"])
    write_frontend_snapshot(state, paths["snapshot"], campaign_path=paths["campaign"])
    return {
        "paths": paths,
        "setup_ms": _ms(started),
        "kind": "owner_size_prepared_contact",
        "placed": bool(pair["placed"]),
        "path_node_ids": pair["path_node_ids"],
        "path_edge_ids": pair["path_edge_ids"],
        **contact,
    }


def _prepare_s10_contact(dest: Path) -> dict[str, Any]:
    from gates_of_codex.frontend import write_frontend_snapshot
    from gates_of_codex.state_io import save_campaign
    from tests.test_s10_frontend_presentation_contract import _create_prepared_contact, _state

    started = time.perf_counter()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    state = _state(dest)
    _create_prepared_contact(state)
    if state.pending_battle is None:
        raise RuntimeError("S10 prepared contact did not create pending_battle")
    campaign = dest / "campaign.json"
    snapshot = dest / "campaign_snapshot.json"
    commands = dest / "frontend_commands.json"
    save_campaign(state, campaign)
    write_frontend_snapshot(state, snapshot, campaign_path=campaign)
    commands.write_text('{"commands":[]}\n', encoding="utf-8")
    return {
        "paths": {"campaign": campaign, "snapshot": snapshot, "commands": commands},
        "setup_ms": _ms(started),
        "kind": "s10_prepared_contact",
        "placed": False,
        "attacker": "sf-n",
        "defender": "sf-r",
        "ticks_advanced": 2,
    }


def capture(source_campaign: Path, work: Path, python: Path, godot: Path, repo: Path) -> dict[str, Any]:
    _install()
    base = _fresh_copy(source_campaign, work / "base")
    snapshot0 = json.loads(base["snapshot"].read_text(encoding="utf-8-sig"))
    order = _pick_order(snapshot0)
    isolated: list[dict[str, Any]] = []

    def measure(name: str, commands: list[dict[str, Any]], prepared: Path | None = None) -> dict[str, Any]:
        src = prepared or base["campaign"].parent
        in_paths = _clone_prepared(src, work / f"{name}-inprocess")
        in_result = _apply_inprocess(in_paths["campaign"], in_paths["snapshot"], commands)
        in_row = _summarize(name, in_result, in_paths["snapshot"])
        sub_paths = _clone_prepared(src, work / f"{name}-subprocess")
        sub_result = _apply_subprocess(
            python, sub_paths["campaign"], sub_paths["snapshot"], sub_paths["commands"], commands
        )
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
            "player_visible": _player_visible(sub_row, godot_row),
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
            [{
                "op": "issue_move_order",
                "formation": order["formation"],
                "path_node_ids": order["path_node_ids"],
                "path_edge_ids": order["path_edge_ids"],
            }],
        )
        measure(
            "commit_move_orders_only",
            [{"op": "commit_move_orders", "faction": order["faction"], "locked_stance": order["locked_stance"]}],
        )
    else:
        isolated.append({"name": "move_click_batch", "ok": False, "error": "no legal operational_orders"})

    measure("refresh", [{"op": "refresh"}])
    measure("end_player_round", [{"op": "end_player_round"}])
    measure("end_turn_diagnostic", [{"op": "end_turn"}])

    owner_setup: dict[str, Any] | None = None
    try:
        owner_setup = _prepare_owner_size_contact(base["campaign"].parent, work / "owner-contact")
        row = measure("auto_resolve", [{"op": "auto_resolve"}], prepared=owner_setup["paths"]["campaign"].parent)
        row["contact_setup"] = {key: value for key, value in owner_setup.items() if key != "paths"}
    except Exception as exc:
        isolated.append({
            "name": "auto_resolve",
            "ok": False,
            "error": f"owner-size prepared contact failed: {exc}",
        })

    try:
        s10_setup = _prepare_s10_contact(work / "s10-contact")
        row = measure("auto_resolve_s10", [{"op": "auto_resolve"}], prepared=s10_setup["paths"]["campaign"].parent)
        row["contact_setup"] = {key: value for key, value in s10_setup.items() if key != "paths"}
    except Exception as exc:
        isolated.append({
            "name": "auto_resolve_s10",
            "ok": False,
            "error": f"S10 prepared contact failed: {exc}",
        })

    loop_paths = _clone_prepared(base["campaign"].parent, work / "realistic-loop")
    loop_t0 = time.perf_counter()
    loop_trace: list[dict[str, Any]] = []
    if order is not None:
        loop_trace.append(
            _summarize(
                "move_click_batch",
                _apply_subprocess(
                    python,
                    loop_paths["campaign"],
                    loop_paths["snapshot"],
                    loop_paths["commands"],
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
            "end_player_round",
            _apply_subprocess(
                python,
                loop_paths["campaign"],
                loop_paths["snapshot"],
                loop_paths["commands"],
                [{"op": "end_player_round"}],
            ),
            loop_paths["snapshot"],
        )
    )
    if _has_pending(loop_paths["snapshot"]):
        loop_trace.append(
            _summarize(
                "auto_resolve",
                _apply_subprocess(
                    python,
                    loop_paths["campaign"],
                    loop_paths["snapshot"],
                    loop_paths["commands"],
                    [{"op": "auto_resolve"}],
                ),
                loop_paths["snapshot"],
            )
        )
    loop_godot = _godot_reload(godot, repo, loop_paths["snapshot"], work / "loop-godot.json")
    loop_sub_ms = 0.0
    for step in loop_trace:
        if step.get("wall_ms") is not None:
            loop_sub_ms += float(step["wall_ms"])
    return {
        "schema": "gates-of-codex.command-latency-capture",
        "schema_version": 3,
        "read_only_owner": True,
        "source_campaign": str(source_campaign),
        "selected_order": order,
        "isolated": isolated,
        "realistic_loop": {
            "wall_ms": _ms(loop_t0),
            "subprocess_sum_ms": round(loop_sub_ms, 3),
            "trace": loop_trace,
            "godot_reload": loop_godot,
            "player_visible": _player_visible(
                {"wall_ms": round(loop_sub_ms, 3)},
                loop_godot,
            ),
            "pending_battle_at_end": _has_pending(loop_paths["snapshot"]),
        },
        "notes": [
            "move_click_batch is the player-facing move click: issue+commit in one apply.",
            "end_player_round is the live End Turn / E payload from main_perf.gd.",
            "end_turn_diagnostic is not the player-facing End Turn.",
            "auto_resolve uses _create_prepared_contact-style setup; setup time is excluded.",
            "auto_resolve_s10 uses tests.test_s10_frontend_presentation_contract._create_prepared_contact.",
            "input_to_visible_ms = subprocess apply + full Godot reload, not the final draw_ms.",
            "realistic_loop is move + end_player_round, then auto_resolve only if contact exists.",
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
                "input_to_visible_ms": (row.get("player_visible") or {}).get("input_to_visible_ms"),
                "godot_reload_ms": (row.get("player_visible") or {}).get("godot_reload_to_visible_ms"),
                "godot_draw_ms": (row.get("player_visible") or {}).get("godot_draw_ms"),
            }
            for row in payload.get("isolated", [])
            if isinstance(row, dict)
        ],
        "realistic_loop_ms": payload.get("realistic_loop", {}).get("wall_ms"),
        "realistic_input_to_visible_ms": (payload.get("realistic_loop", {}).get("player_visible") or {}).get(
            "input_to_visible_ms"
        ),
    }
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
