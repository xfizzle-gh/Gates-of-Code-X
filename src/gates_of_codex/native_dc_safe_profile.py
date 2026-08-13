"""Bounded native Dynamic Conquest create-menu staging for Gates-owned armies.

GoH v1.065 native acceptance proved the #201 final-layer recipe with a small
custom-faction picker.  The production all-faction registration later diverged
from that proof: dozens of GOC army definitions remained live at once and the
create dialog could native-crash while cycling ``btn_army_next``.

This module deliberately composes the already-reviewed #194/#201 native-pair
installer and adds the missing create-menu safety boundary:

* only the selected tactical pair's ``goc_*`` army files remain visible to the
  engine while the profile is active;
* full parent ``values.set`` / CTF behavior remains owned by
  ``expanded_nations_native_pair`` (no three-region rewrite or CTF stub);
* every visible parent ``AvailableMatchups`` block must contain the selected
  pair in both directions;
* required Dynamic Conquest picker presentation is copied at runtime from the
  installed parent stack into actor-scoped names; parent bytes are never
  committed to Gates;
* all removals/copies are transactional and restore to the exact pre-profile
  live state.

The profile intentionally does not renumber tactical army IDs.  #201 already
proved that army IDs and ``nationMap`` IDs are distinct engine namespaces; this
fix removes unproven picker cardinality/orphan-army variables instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable, Sequence

from .expanded_nations_models import ExpandedNationsError
from .expanded_nations_native_pair import (
    ALLIANCES_REL,
    CTF_REL,
    MANIFEST_REL as NATIVE_PAIR_MANIFEST_REL,
    ROSTER_REL,
    VALUES_REL,
    install_native_pair,
    restore_native_pair,
    verify_native_pair,
)
from .goc_tactical_army_registry import army_row

SCHEMA = "gates-of-codex.native-dc-safe-profile"
VERSION = 1
MANIFEST_REL = Path("live/expanded_nations/native_dc_safe_profile/active.json")
BACKUP_REL = Path("live/expanded_nations/native_dc_safe_profile/backup")

# Read-only parents in effective mod precedence order.  Search in reverse so
# AIO wins over Code:X, and Code:X wins over West81.
_PARENT_WORKSHOP_IDS = ("2897299509", "3261086933", "3636883799")

_DC_ART_ROOT = Path("resource/interface/pages/main/dynamic_campaign")
_REQUIRED_ART_TEMPLATES = (
    "selected_army_{side}.tga",
    "icon_{side}.tga",
)
_OPTIONAL_FLAG_TEMPLATES = (
    "flag_{side}.tga",
    "flag_{side}.png",
)
_GOC_ARMY_RE = re.compile(r"^goc_[a-z0-9_]+\.set$", re.IGNORECASE)
_ALLIANCE_GOC_RE = re.compile(r'\{armies\s+"(goc_[^"]+)"\}')
_ROSTER_GOC_RE = re.compile(r'conquest/(?:inf_|units_)(goc_[a-z0-9_]+)\.set')


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_file(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return _sha(target)


def _selected_goc_sides(native_manifest: dict[str, Any]) -> tuple[str, ...]:
    sides: list[str] = []
    for key in ("attacker_side", "defender_side"):
        side = str(native_manifest.get(key) or "")
        if side.startswith("goc_") and side not in sides:
            sides.append(side)
    if not sides:
        raise ExpandedNationsError("Safe native DC profile requires at least one Gates tactical side")
    return tuple(sides)


def _donor_candidates(side: str) -> tuple[str, ...]:
    coalition = str(army_row(side).get("coalition") or "").lower()
    if coalition == "west":
        return ("nato", "ukr")
    if coalition == "east":
        return ("rusa", "prc")
    raise ExpandedNationsError(f"Unknown tactical coalition for picker art: {side}")


def _parent_roots(workshop_root: Path) -> tuple[Path, ...]:
    roots = tuple(workshop_root / item for item in _PARENT_WORKSHOP_IDS)
    missing = [str(path) for path in roots if not path.is_dir()]
    if missing:
        raise ExpandedNationsError(
            "Missing required parent Workshop layer(s) for native DC presentation: "
            + ", ".join(missing)
        )
    return roots


def _find_parent_art(
    roots: Sequence[Path],
    side: str,
    template: str,
) -> tuple[Path, str] | None:
    for donor in _donor_candidates(side):
        relative = _DC_ART_ROOT / template.format(side=donor)
        for root in reversed(roots):
            candidate = root / relative
            if candidate.is_file():
                return candidate, donor
    return None


def _backup_existing(gates: Path, relative: Path, backup_root: Path) -> dict[str, Any] | None:
    target = gates / relative
    if not target.is_file():
        return None
    backup = backup_root / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    return {
        "relative_path": relative.as_posix(),
        "sha256": _sha(target),
    }


def _matching_brace_block(text: str, marker_start: int) -> str:
    brace = text.rfind("{", 0, marker_start + 1)
    if brace < 0:
        raise ExpandedNationsError("AvailableMatchups marker is not inside a brace block")
    depth = 0
    quoted = False
    escaped = False
    for index in range(brace, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace : index + 1]
    raise ExpandedNationsError("Unterminated AvailableMatchups block in values.set")


def _available_matchup_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for match in re.finditer(r"\{AvailableMatchups\b", text):
        blocks.append(_matching_brace_block(text, match.start()))
    return blocks


def _restore_overlay_files(
    gates: Path,
    installed: dict[str, dict[str, Any]],
    backups: Iterable[dict[str, Any]],
    backup_root: Path,
) -> tuple[list[str], list[str]]:
    backup_by_rel = {str(row["relative_path"]): row for row in backups}
    restored: list[str] = []
    removed: list[str] = []
    for rel in sorted(installed, reverse=True):
        target = gates / rel
        if rel in backup_by_rel:
            backup = backup_root / rel
            if not backup.is_file():
                raise ExpandedNationsError(f"Missing safe-profile backup for {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored.append(rel)
        elif target.is_file():
            expected = str((installed.get(rel) or {}).get("sha256") or "")
            if expected and _sha(target) != expected:
                raise ExpandedNationsError(f"Refusing to delete tampered safe-profile file {rel}")
            target.unlink()
            removed.append(rel)
    return restored, removed


def install_safe_profile(
    source_repo: str | Path,
    gates_root: str | Path,
    workshop_root: str | Path,
    attacker_actor: str,
    defender_actor: str,
) -> dict[str, Any]:
    """Install a bounded #201-compatible create-menu profile into live Gates."""

    source = Path(source_repo).resolve()
    gates = Path(gates_root).resolve()
    workshop = Path(workshop_root).resolve()
    manifest_path = gates / MANIFEST_REL
    backup_root = gates / BACKUP_REL

    if manifest_path.is_file():
        raise ExpandedNationsError(
            "A safe native DC profile is already active; restore it before installing another"
        )
    if (gates / NATIVE_PAIR_MANIFEST_REL).is_file():
        raise ExpandedNationsError(
            "A native pair is already active outside the safe profile; restore it first"
        )
    if not source.is_dir() or not gates.is_dir() or not workshop.is_dir():
        raise ExpandedNationsError("Source repo, Gates root, and Workshop root must all exist")

    pair_result = install_native_pair(
        source,
        gates,
        workshop,
        attacker_actor,
        defender_actor,
    )
    native_manifest = dict(pair_result["manifest"])
    selected = _selected_goc_sides(native_manifest)
    parent_roots = _parent_roots(workshop)

    backups: list[dict[str, Any]] = []
    installed: dict[str, dict[str, Any]] = {}
    quarantined: list[str] = []
    art_sources: dict[str, dict[str, str]] = {}

    try:
        armies_root = gates / "resource/set/multiplayer/armies"
        for path in sorted(armies_root.glob("goc_*.set")):
            if not path.is_file() or not _GOC_ARMY_RE.fullmatch(path.name):
                continue
            side = path.stem
            if side in selected:
                continue
            rel = path.relative_to(gates)
            row = _backup_existing(gates, rel, backup_root)
            if row is not None:
                backups.append(row)
            installed[rel.as_posix()] = {"sha256": ""}
            path.unlink()
            quarantined.append(side)

        for side in selected:
            side_sources: dict[str, str] = {}
            templates = list(_REQUIRED_ART_TEMPLATES)
            found_flags = [
                item
                for item in (
                    _find_parent_art(parent_roots, side, template)
                    for template in _OPTIONAL_FLAG_TEMPLATES
                )
                if item is not None
            ]
            if not found_flags:
                raise ExpandedNationsError(
                    f"Cannot resolve Dynamic Conquest flag donor for {side}"
                )

            art_items: list[tuple[str, Path, str]] = []
            for template in templates:
                found = _find_parent_art(parent_roots, side, template)
                if found is None:
                    raise ExpandedNationsError(
                        f"Cannot resolve required Dynamic Conquest art {template} for {side}"
                    )
                source_path, donor = found
                art_items.append((template, source_path, donor))
            for template, found in zip(_OPTIONAL_FLAG_TEMPLATES, found_flags):
                source_path, donor = found
                art_items.append((template, source_path, donor))

            for template, source_path, donor in art_items:
                target_rel = _DC_ART_ROOT / template.format(side=side)
                row = _backup_existing(gates, target_rel, backup_root)
                if row is not None:
                    backups.append(row)
                digest = _copy_file(source_path, gates / target_rel)
                rel = target_rel.as_posix()
                installed[rel] = {"sha256": digest}
                side_sources[rel] = str(source_path)
            art_sources[side] = side_sources

        manifest = {
            "schema": SCHEMA,
            "schema_version": VERSION,
            "native_recipe": "#201-bounded-create-menu-v1",
            "source_repo": str(source),
            "gates_root": str(gates),
            "workshop_root": str(workshop),
            "attacker_actor": attacker_actor,
            "defender_actor": defender_actor,
            "attacker_side": native_manifest.get("attacker_side"),
            "defender_side": native_manifest.get("defender_side"),
            "selected_goc_sides": list(selected),
            "army_ids": {side: int(army_row(side)["numeric_id"]) for side in selected},
            "quarantined_goc_armies": quarantined,
            "art_sources": art_sources,
            "installed_files": installed,
            "backups": backups,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        problems = verify_safe_profile(gates)
        if problems:
            raise ExpandedNationsError(
                "Safe native DC profile verification failed: " + "; ".join(problems)
            )
    except Exception:
        try:
            _restore_overlay_files(gates, installed, backups, backup_root)
        finally:
            if manifest_path.is_file():
                manifest_path.unlink()
            if backup_root.exists():
                shutil.rmtree(backup_root)
            restore_native_pair(gates)
        raise

    return {
        "ok": True,
        "manifest_path": str(manifest_path),
        "selected_goc_sides": list(selected),
        "quarantined_goc_armies": quarantined,
        "army_ids": manifest["army_ids"],
    }


def verify_safe_profile(gates_root: str | Path) -> list[str]:
    gates = Path(gates_root).resolve()
    manifest_path = gates / MANIFEST_REL
    if not manifest_path.is_file():
        return ["safe native DC profile manifest missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"safe native DC profile manifest malformed: {exc}"]

    problems: list[str] = []
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("schema_version") != VERSION
        or manifest.get("native_recipe") != "#201-bounded-create-menu-v1"
    ):
        problems.append("safe native DC profile schema/recipe mismatch")

    pair_problems = verify_native_pair(gates)
    problems.extend(f"native-pair: {item}" for item in pair_problems)

    selected = tuple(str(item) for item in manifest.get("selected_goc_sides") or [])
    selected_set = set(selected)
    if not selected:
        problems.append("safe profile has no selected GOC sides")

    armies_root = gates / "resource/set/multiplayer/armies"
    live_goc_armies = {
        path.stem
        for path in armies_root.glob("goc_*.set")
        if path.is_file() and _GOC_ARMY_RE.fullmatch(path.name)
    }
    if live_goc_armies != selected_set:
        problems.append(
            "live GOC army set is not bounded to selected pair: "
            f"expected={sorted(selected_set)} actual={sorted(live_goc_armies)}"
        )

    alliances_path = gates / ALLIANCES_REL
    alliances = alliances_path.read_text(encoding="utf-8", errors="replace") if alliances_path.is_file() else ""
    alliance_goc = set(_ALLIANCE_GOC_RE.findall(alliances))
    if alliance_goc != selected_set:
        problems.append(
            "alliance GOC picker set is not bounded to selected pair: "
            f"expected={sorted(selected_set)} actual={sorted(alliance_goc)}"
        )

    roster_path = gates / ROSTER_REL
    roster = roster_path.read_text(encoding="utf-8", errors="replace") if roster_path.is_file() else ""
    roster_goc = set(_ROSTER_GOC_RE.findall(roster))
    if roster_goc != selected_set:
        problems.append(
            "roster GOC include set is not bounded to selected pair: "
            f"expected={sorted(selected_set)} actual={sorted(roster_goc)}"
        )

    values_path = gates / VALUES_REL
    values = values_path.read_text(encoding="utf-8", errors="replace") if values_path.is_file() else ""
    blocks = _available_matchup_blocks(values) if values else []
    # The effective Code:X/AIO parent controls the region count.  Do not encode
    # the old eight-region fixture as a runtime invariant: owner stack v1.065
    # currently exposes three blocks.  The safety contract is that at least one
    # parent block exists and the selected pair is injected into every block.
    if not blocks:
        problems.append("values.set exposes no AvailableMatchups blocks")
    attacker = str(manifest.get("attacker_side") or "")
    defender = str(manifest.get("defender_side") or "")
    forward = f'"{attacker} {defender}"'
    reverse = f'"{defender} {attacker}"'
    for index, block in enumerate(blocks, start=1):
        if forward not in block or reverse not in block:
            problems.append(
                f"values.set AvailableMatchups block {index} lacks selected pair in both directions"
            )

    ctf_path = gates / CTF_REL
    ctf = ctf_path.read_text(encoding="utf-8", errors="replace") if ctf_path.is_file() else ""
    for token in (
        'include "presets/alliances_generic.inc"',
        "{settings",
        "{presets",
        "{bots",
    ):
        if token not in ctf:
            problems.append(f"full parent CTF token missing: {token}")

    installed = manifest.get("installed_files") or {}
    for rel, metadata in installed.items():
        if not metadata.get("sha256"):
            # Quarantined files are represented by an empty hash because their
            # active state is intentional absence, validated by live_goc_armies.
            continue
        target = gates / rel
        if not target.is_file():
            problems.append(f"missing safe-profile installed file {rel}")
        elif _sha(target) != metadata["sha256"]:
            problems.append(f"tampered safe-profile installed file {rel}")

    for side in selected:
        selected_art = _DC_ART_ROOT / f"selected_army_{side}.tga"
        icon_art = _DC_ART_ROOT / f"icon_{side}.tga"
        flag_tga = _DC_ART_ROOT / f"flag_{side}.tga"
        flag_png = _DC_ART_ROOT / f"flag_{side}.png"
        for required in (selected_art, icon_art):
            if not (gates / required).is_file():
                problems.append(f"missing Dynamic Conquest picker art {required.as_posix()}")
        if not (gates / flag_tga).is_file() and not (gates / flag_png).is_file():
            problems.append(f"missing Dynamic Conquest picker flag for {side}")

    return problems


def restore_safe_profile(gates_root: str | Path) -> dict[str, Any]:
    gates = Path(gates_root).resolve()
    manifest_path = gates / MANIFEST_REL
    backup_root = gates / BACKUP_REL
    restored: list[str] = []
    removed: list[str] = []

    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        installed = manifest.get("installed_files") or {}
        backups = manifest.get("backups") or []
        overlay_restored, overlay_removed = _restore_overlay_files(
            gates,
            installed,
            backups,
            backup_root,
        )
        restored.extend(overlay_restored)
        removed.extend(overlay_removed)
        manifest_path.unlink()
        if backup_root.exists():
            shutil.rmtree(backup_root)

    pair_result = restore_native_pair(gates)
    restored.extend(str(item) for item in pair_result.get("restored") or [])
    removed.extend(str(item) for item in pair_result.get("removed") or [])
    return {
        "ok": True,
        "restored": sorted(set(restored)),
        "removed": sorted(set(removed)),
        "gates_root": str(gates),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gates-of-codex-native-dc-safe-profile")
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
            result = install_safe_profile(
                args.source_repo,
                args.gates_root,
                args.workshop_root,
                args.attacker,
                args.defender,
            )
        elif args.command == "verify":
            problems = verify_safe_profile(args.gates_root)
            result = {"ok": not problems, "problems": problems}
        else:
            result = restore_safe_profile(args.gates_root)
    except (ExpandedNationsError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
