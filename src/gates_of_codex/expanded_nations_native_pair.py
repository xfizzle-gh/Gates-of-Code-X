"""#194 native battle-pair installer using the owner-proven #201 GoH recipe.

This is intentionally separate from the earlier evidence-only battle-pair
materializer. It stages a real final Gates Workshop layer: required parent
conquest files are materialized, roster includes are self-contained, the full
parent Code:X/AIO Dynamic Conquest surfaces are preserved, and selected-pair
cross-side personnel breeds are projected transactionally into the final layer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Mapping, Sequence

from .expanded_nations_battle_pair import restore_battle_pair as restore_legacy_pair
from .expanded_nations_breeds import project_actor_breed_files
from .expanded_nations_models import ExpandedNationsError, GENERATED_MARKER
from .faction_wiring_compiler import FactionWiringCompiler
from .faction_wiring_manifest import load_faction_manifest
from .goc_tactical_army_registry import army_row, is_goc_tactical_side
from .modstack import KNOWN_WORKSHOP_ORDER

SCHEMA = "gates-of-codex.expanded-nations-native-pair"
VERSION = 2
MANIFEST_REL = Path("live/expanded_nations/native_pair/active.json")
BACKUP_REL = Path("live/expanded_nations/native_pair/backup")

ROSTER_REL = "resource/set/multiplayer/units/roster_conquest.set"
CONQUEST_LUA_REL = "resource/script/multiplayer/modes/conquest.lua"
VALUES_REL = "resource/set/dynamic_campaign/values.set"
CTF_REL = "resource/set/multiplayer/games/campaign_capture_the_flag.set"
ALLIANCES_REL = "resource/set/multiplayer/games/presets/alliances_generic.inc"

# Exact final-layer parent conquest set from the native #201 win. In
# particular: no inf_frg_era1960, no inf_sov_era1960, no units_frg_era1960.
PARENT_NAMES = (
    "settings.set",
    "inf_ukr.set",
    "inf_rusa.set",
    "inf_nato.set",
    "inf_prc_era1960.set",
    "inf_csa_era1960.set",
    "units_ukr.set",
    "units_rusa.set",
    "units_nato.set",
    "units_sov_era1960.set",
    "units_csa_era1960.set",
    "units_prc_era1960.set",
)
PARENT_RELS = tuple(
    f"resource/set/multiplayer/units/conquest/{name}" for name in PARENT_NAMES
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _actor(actor_id: str) -> Mapping[str, Any]:
    actors = {row["actor_id"]: row for row in load_faction_manifest()["actors"]}
    row = actors.get(actor_id)
    if not row or not row.get("playable") or row.get("roster_class") == "strategic_only":
        raise ExpandedNationsError(f"Actor is not native-pair playable: {actor_id}")
    side = str(row.get("tactical_side") or "")
    if side != "prc" and not is_goc_tactical_side(side):
        raise ExpandedNationsError(f"Actor lacks Gates tactical side: {actor_id} -> {side}")
    return row


def _resolved_pair_actors(
    roots: Sequence[Path],
    expected: Mapping[str, str],
    resolved_payload: Mapping[str, Any] | None = None,
) -> dict[str, Mapping[str, Any]]:
    payload = dict(resolved_payload) if resolved_payload is not None else FactionWiringCompiler(roots).compile()
    if int(payload.get("error_count") or 0) != 0:
        raise ExpandedNationsError(
            f"Resolved actor catalog has {payload.get('error_count')} error(s); refuse native pair"
        )
    by_id = {str(row.get("actor_id")): row for row in payload.get("actors", [])}
    resolved: dict[str, Mapping[str, Any]] = {}
    for actor_id, tactical_side in expected.items():
        row = by_id.get(actor_id)
        if row is None:
            raise ExpandedNationsError(f"Resolved actor catalog missing {actor_id}")
        if not row.get("playable"):
            raise ExpandedNationsError(f"Resolved native-pair actor is not playable: {actor_id}")
        if str(row.get("tactical_side") or "") != tactical_side:
            raise ExpandedNationsError(
                f"Resolved actor tactical side drift: {actor_id} -> {row.get('tactical_side')} expected {tactical_side}"
            )
        components = {str(item) for item in (row.get("components") or [])}
        if tactical_side != "prc" and not components:
            raise ExpandedNationsError(f"Resolved actor lacks approved components: {actor_id}")
        resolved[actor_id] = row
    return resolved


def _pack_rels(side: str) -> tuple[str, ...]:
    if side == "prc":
        return ()
    return (
        f"resource/set/multiplayer/units/conquest/units_{side}.set",
        f"resource/set/multiplayer/units/conquest/inf_{side}.set",
        f"resource/set/dynamic_campaign/unit_research_{side}.set",
        f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
        f"resource/set/multiplayer/armies/{side}.set",
        f"resource/interface/pages/multi/flag_{side}.tga",
    )


def _roots(workshop_root: Path) -> list[Path]:
    roots = [workshop_root / item for item in KNOWN_WORKSHOP_ORDER]
    missing = [str(path) for path in roots if not path.is_dir()]
    if missing:
        raise ExpandedNationsError(
            "Missing required read-only parent Workshop layer(s): " + ", ".join(missing)
        )
    return roots


def _find(roots: Sequence[Path], rel: str) -> Path:
    for root in reversed(roots):
        path = root / rel
        if path.is_file():
            return path
    raise ExpandedNationsError(f"Required parent runtime file not found: {rel}")


def _assignment(attacker: str, defender: str) -> tuple[str, str]:
    def coalition(side: str, default: str) -> str:
        if is_goc_tactical_side(side):
            return str(army_row(side).get("coalition") or default)
        return default

    left = coalition(attacker, "west")
    right = coalition(defender, "east")
    if left == right:
        right = "east" if left == "west" else "west"
    return left, right


def _alliances(attacker: str, defender: str) -> str:
    left, right = _assignment(attacker, defender)
    west = ["nato", "ukr"]
    east = ["rusa", "prc"]
    (west if left == "west" else east).append(attacker)
    (west if right == "west" else east).append(defender)

    def block(title: str, rows: Sequence[str], icon: str) -> str:
        armies = "\n".join(f'\t{{armies "{x}"}}' for x in dict.fromkeys(rows))
        return (
            f'{{"{title}"\n\t{{title "mp/alliance/{title.lower()}"}}\n'
            f"{armies}\n\t{{icon \"{icon}\"}}\n}}\n"
        )

    return (
        f"{GENERATED_MARKER}\n; native #194 pair; #201 Core-preserving alliance recipe\n"
        + block("West", west, "/interface/pages/multi/flag_nato")
        + block("East", east, "/interface/pages/multi/flag_rusa")
    )


def _roster(attacker: str, defender: str) -> str:
    inf = [x for x in PARENT_NAMES if x.startswith("inf_")]
    units = [x for x in PARENT_NAMES if x.startswith("units_")]
    sides = tuple(dict.fromkeys((attacker, defender)))
    lines = [
        ";sdl",
        GENERATED_MARKER,
        "; native #194 final-layer roster; exact #201 include contract",
        "{units",
        '\t(include "conquest/settings.set")',
        "",
    ]
    lines += [f'\t(include "conquest/{x}")' for x in inf]
    lines += [f'\t(include "conquest/inf_{x}.set")' for x in sides if x != "prc"]
    lines.append("")
    lines += [f'\t(include "conquest/{x}")' for x in units]
    lines += [f'\t(include "conquest/units_{x}.set")' for x in sides if x != "prc"]
    lines += ["}", ""]
    return "\n".join(lines)


def _values(parent: str, attacker: str, defender: str) -> str:
    lines = parent.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    out: list[str] = []
    blocks = 0
    for line in lines:
        out.append(line)
        if re.match(r"^\s*\{AvailableMatchups\b", line):
            match = re.match(r"^(\s*)", line)
            indent = (match.group(1) if match else "") + "\t"
            out += [f'{indent}"{attacker} {defender}"', f'{indent}"{defender} {attacker}"']
            blocks += 1
    if blocks == 0:
        raise ExpandedNationsError("Parent values.set has no AvailableMatchups block")
    return (
        f"{GENERATED_MARKER}\n; pair matchups injected into full effective parent values.set\n"
        + "\n".join(out)
        + "\n"
    )


def _patch_table(text: str, name: str, pair: Sequence[str], assigned: set[str]) -> str:
    rx = re.compile(rf"(local\s+{re.escape(name)}\s*=\s*\{{)(.*?)(\}})", re.DOTALL)
    m = rx.search(text)
    if not m:
        raise ExpandedNationsError(f"Full production conquest.lua lacks {name}")
    body = m.group(2)
    for side in pair:
        body = re.sub(rf"(?:^|,\s*){re.escape(side)}\s*=\s*true\s*", "", body)
    body = re.sub(r"^\s*,\s*", "", body.strip())
    body = re.sub(r",\s*$", "", body)
    add = ", ".join(f"{side} = true" for side in pair if side in assigned)
    if add:
        body = f"{body}, {add}" if body else add
    replacement = m.group(1) + body + m.group(3)
    return text[: m.start()] + replacement + text[m.end() :]


def _conquest(parent: str, attacker: str, defender: str) -> str:
    if "local nationMap" not in parent:
        raise ExpandedNationsError("Committed conquest.lua is not the full AIO-derived runtime")
    left, right = _assignment(attacker, defender)
    west = {s for s, c in ((attacker, left), (defender, right)) if c == "west"}
    east = {attacker, defender} - west
    text = _patch_table(parent, "westNations", (attacker, defender), west)
    text = _patch_table(text, "eastNations", (attacker, defender), east)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _backup(gates: Path, rel: str, backup_root: Path) -> dict[str, Any] | None:
    target = gates / rel
    if not target.is_file():
        return None
    backup = backup_root / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    return {"relative_path": rel, "sha256": _sha(target)}


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return _sha(path)


def _write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha(path)


def _copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return _sha(dst)


def _project_pair_breeds(
    resolved: Mapping[str, Mapping[str, Any]],
    roots: Sequence[Path],
    actor_sides: Mapping[str, str],
) -> dict[str, dict[Path, bytes]]:
    result: dict[str, dict[Path, bytes]] = {}
    for actor_id, side in actor_sides.items():
        if side == "prc":
            continue
        actor = resolved[actor_id]
        components = {str(item) for item in (actor.get("components") or [])}
        cross_side_member_units = [
            unit
            for unit in (actor.get("units") or [])
            if str(unit.get("source_side") or "").lower() != side.lower()
            and isinstance(unit.get("members"), Mapping)
            and bool(unit.get("members"))
            and str(unit.get("component_id") or "") in components
        ]
        if not cross_side_member_units:
            raise ExpandedNationsError(
                f"Native-pair actor {actor_id}/{side} has no authorized personnel-bearing source units"
            )
        outputs = project_actor_breed_files(actor, roots)
        if not outputs:
            raise ExpandedNationsError(
                f"Native-pair actor {actor_id}/{side} projected zero personnel breed files"
            )
        prefix = f"resource/set/breed/mp/{side}/"
        for relative in outputs:
            if not relative.as_posix().startswith(prefix):
                raise ExpandedNationsError(
                    f"Breed projection escaped actor namespace: {actor_id}: {relative.as_posix()}"
                )
        result[side] = outputs
    return result


def install_native_pair(
    source_repo: str | Path,
    gates_root: str | Path,
    workshop_root: str | Path,
    attacker_actor: str,
    defender_actor: str,
    *,
    resolved_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = Path(source_repo).resolve()
    gates = Path(gates_root).resolve()
    workshop = Path(workshop_root).resolve()
    gates.mkdir(parents=True, exist_ok=True)
    if source == gates:
        raise ExpandedNationsError("Source checkout and live Gates root must differ")

    legacy = gates / "live/expanded_nations/battle_pair/active.json"
    if legacy.is_file():
        restore_legacy_pair(gates)
    if (gates / MANIFEST_REL).is_file():
        restore_native_pair(gates)

    arow, drow = _actor(attacker_actor), _actor(defender_actor)
    attacker, defender = str(arow["tactical_side"]), str(drow["tactical_side"])
    roots = _roots(workshop)
    actor_sides = {attacker_actor: attacker, defender_actor: defender}
    resolved = _resolved_pair_actors(roots, actor_sides, resolved_payload)
    breed_outputs = _project_pair_breeds(resolved, roots, actor_sides)

    parent = {rel: _find(roots, rel) for rel in PARENT_RELS}
    parent[VALUES_REL] = _find(roots, VALUES_REL)
    parent[CTF_REL] = _find(roots, CTF_REL)

    ctf_parent = parent[CTF_REL].read_text(encoding="utf-8-sig", errors="replace")
    for token in ('include "presets/alliances_generic.inc"', "{settings", "{presets", "{bots"):
        if token not in ctf_parent:
            raise ExpandedNationsError(f"Effective parent CTF is incomplete; missing {token}")
    ctf = f"{GENERATED_MARKER}\n; full effective parent AIO CTF preserved\n" + ctf_parent

    values = _values(
        parent[VALUES_REL].read_text(encoding="utf-8-sig", errors="replace"),
        attacker,
        defender,
    )
    lua_src = source / CONQUEST_LUA_REL
    if not lua_src.is_file():
        raise ExpandedNationsError(f"Missing committed production conquest.lua: {lua_src}")
    lua = _conquest(lua_src.read_text(encoding="utf-8-sig", errors="replace"), attacker, defender)

    pack_rels = sorted(set(_pack_rels(attacker) + _pack_rels(defender)))
    for rel in pack_rels:
        if not (source / rel).is_file():
            raise ExpandedNationsError(f"Missing committed pair pack: {rel}")

    backup_root = gates / BACKUP_REL
    if backup_root.exists():
        shutil.rmtree(backup_root)
    backup_root.mkdir(parents=True)
    backups: list[dict[str, Any]] = []
    installed: dict[str, str] = {}
    touched: list[str] = []

    def prep(rel: str) -> None:
        row = _backup(gates, rel, backup_root)
        if row:
            backups.append(row)
        touched.append(rel)

    try:
        for rel in PARENT_RELS:
            prep(rel)
            installed[rel] = _copy(parent[rel], gates / rel)
        for rel in pack_rels:
            prep(rel)
            installed[rel] = _copy(source / rel, gates / rel)
        for side, outputs in sorted(breed_outputs.items()):
            for relative, data in sorted(outputs.items(), key=lambda item: item[0].as_posix()):
                rel = relative.as_posix()
                prep(rel)
                installed[rel] = _write_bytes(gates / rel, data)
        for rel, text in (
            (CONQUEST_LUA_REL, lua),
            (CTF_REL, ctf),
            (ALLIANCES_REL, _alliances(attacker, defender)),
            (VALUES_REL, values),
            (ROSTER_REL, _roster(attacker, defender)),
        ):
            prep(rel)
            installed[rel] = _write(gates / rel, text)

        manifest = {
            "schema": SCHEMA,
            "schema_version": VERSION,
            "native_recipe": "#201-final-layer-v1",
            "pair_id": f"{attacker_actor}_vs_{defender_actor}",
            "attacker_actor": attacker_actor,
            "defender_actor": defender_actor,
            "attacker_side": attacker,
            "defender_side": defender,
            "source_repo": str(source),
            "workshop_root": str(workshop),
            "parent_roots": [str(x) for x in roots],
            "parent_sources": [
                {"relative_path": rel, "source_path": str(path), "sha256": _sha(path)}
                for rel, path in sorted(parent.items())
            ],
            "breed_files": {
                side: [relative.as_posix() for relative in sorted(outputs, key=lambda path: path.as_posix())]
                for side, outputs in sorted(breed_outputs.items())
            },
            "breed_counts": {side: len(outputs) for side, outputs in sorted(breed_outputs.items())},
            "installed_files": {rel: {"sha256": digest} for rel, digest in sorted(installed.items())},
            "backups": backups,
        }
        path = gates / MANIFEST_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        problems = verify_native_pair(gates)
        if problems:
            raise ExpandedNationsError("Native-pair verification failed: " + "; ".join(problems))
    except Exception:
        temp = {
            "schema": SCHEMA,
            "schema_version": VERSION,
            "installed_files": {rel: {"sha256": installed.get(rel, "")} for rel in touched},
            "backups": backups,
        }
        path = gates / MANIFEST_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(temp), encoding="utf-8")
        restore_native_pair(gates)
        raise

    return {"ok": True, "manifest_path": str(gates / MANIFEST_REL), "manifest": manifest}


def _includes(text: str) -> list[str]:
    return [m.group(1).replace("\\", "/") for m in re.finditer(r'\(include\s+"([^"]+)"\)', text)]


def verify_native_pair(gates_root: str | Path) -> list[str]:
    gates = Path(gates_root).resolve()
    path = gates / MANIFEST_REL
    if not path.is_file():
        return ["native-pair manifest missing"]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"native-pair manifest malformed: {exc}"]
    problems: list[str] = []
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("schema_version") != VERSION
        or manifest.get("native_recipe") != "#201-final-layer-v1"
    ):
        problems.append("native-pair recipe/schema mismatch")
    installed = manifest.get("installed_files") or {}
    for rel, meta in installed.items():
        target = gates / rel
        if not target.is_file():
            problems.append(f"missing installed file {rel}")
        elif meta.get("sha256") and _sha(target) != meta["sha256"]:
            problems.append(f"tampered installed file {rel}")

    breed_files = manifest.get("breed_files") or {}
    for side in (str(manifest.get("attacker_side") or ""), str(manifest.get("defender_side") or "")):
        if side.startswith("goc_"):
            rows = breed_files.get(side) or []
            if not rows:
                problems.append(f"native pair missing personnel breed projection for {side}")
            for rel in rows:
                if not str(rel).startswith(f"resource/set/breed/mp/{side}/"):
                    problems.append(f"breed manifest path escaped {side}: {rel}")
                if rel not in installed:
                    problems.append(f"breed manifest path not transactionally installed: {rel}")

    roster = gates / ROSTER_REL
    if roster.is_file():
        text = roster.read_text(encoding="utf-8", errors="replace")
        base = gates / "resource/set/multiplayer/units"
        for include in _includes(text):
            if not (base / include).is_file():
                problems.append(f"unresolved roster include {include}")
        for banned in ("inf_frg_era1960.set", "inf_sov_era1960.set", "units_frg_era1960.set"):
            if banned in text:
                problems.append(f"roster regressed to #201-excluded include {banned}")

    ctf = gates / CTF_REL
    if ctf.is_file():
        text = ctf.read_text(encoding="utf-8", errors="replace")
        for token in ('include "presets/alliances_generic.inc"', "{settings", "{presets", "{bots"):
            if token not in text:
                problems.append(f"CTF lost parent runtime token {token}")

    attacker, defender = str(manifest.get("attacker_side") or ""), str(manifest.get("defender_side") or "")
    values = (gates / VALUES_REL).read_text(encoding="utf-8", errors="replace") if (gates / VALUES_REL).is_file() else ""
    for pair in (f'"{attacker} {defender}"', f'"{defender} {attacker}"'):
        if pair not in values:
            problems.append(f"values missing {pair}")
    alliances = (gates / ALLIANCES_REL).read_text(encoding="utf-8", errors="replace") if (gates / ALLIANCES_REL).is_file() else ""
    for side in ("nato", "ukr", "rusa", "prc", attacker, defender):
        if f'{{armies "{side}"}}' not in alliances:
            problems.append(f"alliances missing {side}")
    return problems


def restore_native_pair(gates_root: str | Path) -> dict[str, Any]:
    gates = Path(gates_root).resolve()
    path = gates / MANIFEST_REL
    backup_root = gates / BACKUP_REL
    if not path.is_file():
        return {"ok": True, "restored": [], "removed": [], "gates_root": str(gates)}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    installed = manifest.get("installed_files") or {}
    backups = {row["relative_path"]: row for row in manifest.get("backups") or []}
    restored: list[str] = []
    removed: list[str] = []
    for rel in sorted(installed):
        target = gates / rel
        if rel in backups:
            backup = backup_root / rel
            if not backup.is_file():
                raise ExpandedNationsError(f"Missing native-pair backup for {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored.append(rel)
        elif target.is_file():
            expected = (installed.get(rel) or {}).get("sha256")
            if expected and _sha(target) != expected:
                raise ExpandedNationsError(f"Refusing to delete tampered native-pair file {rel}")
            target.unlink()
            removed.append(rel)
    path.unlink()
    if backup_root.exists():
        shutil.rmtree(backup_root)
    return {"ok": True, "restored": restored, "removed": removed, "gates_root": str(gates)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gates-of-codex-native-pair")
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    install.add_argument("--source-repo", required=True)
    install.add_argument("--gates-root", required=True)
    install.add_argument("--workshop-root", required=True)
    install.add_argument("--attacker", required=True)
    install.add_argument("--defender", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--gates-root", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--gates-root", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "install":
            result = install_native_pair(args.source_repo, args.gates_root, args.workshop_root, args.attacker, args.defender)
        elif args.command == "verify":
            problems = verify_native_pair(args.gates_root)
            result = {"ok": not problems, "problems": problems}
        else:
            result = restore_native_pair(args.gates_root)
    except ExpandedNationsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
