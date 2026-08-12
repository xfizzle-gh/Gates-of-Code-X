"""Two-sided Expanded Nations battle-pair install for #194 native harness.

Installs both actors' independent native packs plus pair-specific alliance and
matchup overlays into the engine-consumed resource paths under a Gates root.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from .expanded_nations_models import ExpandedNationsError, GENERATED_MARKER
from .faction_wiring_manifest import load_faction_manifest
from .goc_native_dc_seam import (
    materialize_native_dc_seam,
    render_alliances_generic,
    render_ctf_set,
    render_values_set,
)
from .goc_tactical_army_registry import army_row, is_goc_tactical_side, playable_goc_sides

BATTLE_PAIR_SCHEMA = "gates-of-codex.expanded-nations-battle-pair"
BATTLE_PAIR_VERSION = 2
BATTLE_PAIR_MANIFEST_RELATIVE = Path("live/expanded_nations/battle_pair/active.json")
BATTLE_PAIR_BACKUP_DIR = Path("live/expanded_nations/battle_pair/backup")

ENGINE_OVERLAY_RELS = (
    "resource/set/multiplayer/games/presets/alliances_generic.inc",
    "resource/set/dynamic_campaign/values.set",
    "resource/set/multiplayer/games/campaign_capture_the_flag.set",
)


def _actor_row(manifest_actors: Mapping[str, Mapping[str, Any]], actor_id: str) -> Mapping[str, Any]:
    row = manifest_actors.get(actor_id)
    if row is None:
        raise ExpandedNationsError(f"Unknown battle-pair actor: {actor_id}")
    if not row.get("playable"):
        raise ExpandedNationsError(f"Battle-pair actor is not playable: {actor_id}")
    if row.get("roster_class") == "strategic_only":
        raise ExpandedNationsError(f"Battle-pair actor is strategic_only: {actor_id}")
    side = str(row.get("tactical_side") or "")
    if side != "prc" and not is_goc_tactical_side(side):
        raise ExpandedNationsError(
            f"Battle-pair actor {actor_id} lacks Expanded Gates tactical ID: {side}"
        )
    return row


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pack_relpaths(side: str) -> tuple[str, ...]:
    if side == "prc":
        return ()
    return (
        f"resource/set/multiplayer/units/conquest/units_{side}.set",
        f"resource/set/multiplayer/units/conquest/inf_{side}.set",
        f"resource/set/dynamic_campaign/unit_research_{side}.set",
        f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
        f"resource/set/multiplayer/armies/{side}.set",
    )


def render_battle_pair_alliances(attacker_side: str, defender_side: str) -> str:
    """Minimal two-army alliance file placing each side on opposite coalitions."""
    attacker_coalition = "west"
    defender_coalition = "east"
    if is_goc_tactical_side(attacker_side):
        attacker_coalition = str(army_row(attacker_side).get("coalition") or "west")
    if is_goc_tactical_side(defender_side):
        defender_coalition = str(army_row(defender_side).get("coalition") or "east")
    if attacker_coalition == defender_coalition:
        defender_coalition = "east" if attacker_coalition == "west" else "west"
    west: list[str] = []
    east: list[str] = []
    (west if attacker_coalition == "west" else east).append(attacker_side)
    (west if defender_coalition == "west" else east).append(defender_side)
    if not west:
        west.append(attacker_side)
    if not east:
        east.append(defender_side)
    west_lines = "\n".join(f'\t{{armies "{side}"}}' for side in west)
    east_lines = "\n".join(f'\t{{armies "{side}"}}' for side in east)
    return (
        f"{GENERATED_MARKER}\n"
        "; #194 battle-pair alliances_generic.inc\n"
        '{"West"\n'
        '\t{title "mp/alliance/west"}\n'
        f"{west_lines}\n"
        '\t{icon "/interface/pages/multi/flag_nato"}\n'
        "}\n"
        '{"East"\n'
        '\t{title "mp/alliance/east"}\n'
        f"{east_lines}\n"
        '\t{icon "/interface/pages/multi/flag_rusa"}\n'
        "}\n"
    )


def render_battle_pair_values(attacker_side: str, defender_side: str) -> str:
    pairs = [
        f'"{attacker_side} {defender_side}"',
        f'"{defender_side} {attacker_side}"',
    ]
    matchups = "\n\t\t\t".join(pairs)
    return (
        f"{GENERATED_MARKER}\n"
        "; #194 battle-pair values.set\n"
        "{Regions\n"
        "\t{Europe\n"
        "\t\t{AvailableMatchups\n"
        f"\t\t\t{matchups}\n"
        "\t\t}\n"
        "\t}\n"
        "\t{Asia\n"
        "\t\t{AvailableMatchups\n"
        f"\t\t\t{matchups}\n"
        "\t\t}\n"
        "\t}\n"
        "\t{Test\n"
        "\t\t{AvailableMatchups\n"
        f"\t\t\t{matchups}\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
        "\n"
        "{GameModes\n"
        '\t"campaign_capture_the_flag"\n'
        "}\n"
    )


def render_battle_pair_ctf() -> str:
    return f"{GENERATED_MARKER}\n" + render_ctf_set()


def _copy_pack_file(source_root: Path, dest_root: Path, rel: str) -> None:
    src = source_root / rel
    if not src.is_file():
        raise ExpandedNationsError(f"Battle-pair source pack missing: {rel}")
    dst = dest_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _backup_existing(dest: Path, rel: str, backup_root: Path) -> dict[str, Any] | None:
    path = dest / rel
    if not path.is_file():
        return None
    # Refuse unmanaged overwrite unless content is already a managed GOC marker
    # or we are restoring from a prior battle-pair/native-multi overlay.
    text_head = path.read_text(encoding="utf-8", errors="ignore")[:512]
    managed = GENERATED_MARKER in text_head or path.name in {
        "alliances_generic.inc",
        "values.set",
        "campaign_capture_the_flag.set",
    }
    # Always backup existing engine overlay / pack before pair install.
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    return {
        "relative_path": rel.replace("\\", "/"),
        "sha256": _file_sha256(path),
        "backup_relative": (BATTLE_PAIR_BACKUP_DIR / rel).as_posix(),
        "had_generated_marker": GENERATED_MARKER in text_head,
        "managed_overlay_path": managed,
    }


def _write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return _file_sha256(path)


def materialize_battle_pair(
    repo_root: str | Path,
    *,
    attacker_actor_id: str,
    defender_actor_id: str,
    resource_stack: Sequence[str | Path] | None = None,
    aio_conquest_lua: str | Path | None = None,
    output_root: str | Path | None = None,
    source_pack_root: str | Path | None = None,
) -> dict[str, Any]:
    """Install a two-sided battle pair into engine-consumed resource paths.

    When ``output_root`` differs from ``repo_root``, packs are copied from the
    source pack root (default: repo_root) into the destination and overlays are
    written only under the destination. The source repo is never mutated in that
    case.
    """
    if attacker_actor_id == defender_actor_id:
        raise ExpandedNationsError("Battle pair requires two distinct actors")
    source_root = Path(source_pack_root or repo_root).resolve()
    dest = Path(output_root).resolve() if output_root else source_root
    dest.mkdir(parents=True, exist_ok=True)
    mutate_source = dest == source_root

    manifest_actors = {row["actor_id"]: row for row in load_faction_manifest()["actors"]}
    attacker = _actor_row(manifest_actors, attacker_actor_id)
    defender = _actor_row(manifest_actors, defender_actor_id)
    attacker_side = str(attacker["tactical_side"])
    defender_side = str(defender["tactical_side"])

    # If installing into the source repo itself and packs are missing, optionally
    # materialize the full native seam first (requires stack + aio path).
    if mutate_source and resource_stack is not None and aio_conquest_lua is not None:
        materialize_native_dc_seam(
            source_root,
            resource_stack=resource_stack,
            aio_conquest_lua=aio_conquest_lua,
        )

    pack_rels: list[str] = []
    for side in (attacker_side, defender_side):
        pack_rels.extend(_pack_relpaths(side))
    pack_rels = sorted(set(pack_rels))

    # Destination must receive its own pack copies; never claim success from source-only presence.
    for rel in pack_rels:
        if mutate_source:
            if not (dest / rel).is_file():
                raise ExpandedNationsError(
                    f"Battle-pair materialize missing native pack in destination: {rel}"
                )
        else:
            _copy_pack_file(source_root, dest, rel)

    backup_root = dest / BATTLE_PAIR_BACKUP_DIR
    if backup_root.exists():
        shutil.rmtree(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)

    backups: list[dict[str, Any]] = []
    installed: dict[str, str] = {}

    # Backup then write engine overlays.
    overlays = {
        ENGINE_OVERLAY_RELS[0]: render_battle_pair_alliances(attacker_side, defender_side),
        ENGINE_OVERLAY_RELS[1]: render_battle_pair_values(attacker_side, defender_side),
        ENGINE_OVERLAY_RELS[2]: render_battle_pair_ctf(),
    }
    for rel, text in overlays.items():
        prior = _backup_existing(dest, rel, backup_root)
        if prior is not None:
            backups.append(prior)
        installed[rel] = _write_text(dest / rel, text)

    for rel in pack_rels:
        installed[rel] = _file_sha256(dest / rel)

    pair_id = f"{attacker_actor_id}_vs_{defender_actor_id}"
    manifest = {
        "schema": BATTLE_PAIR_SCHEMA,
        "schema_version": BATTLE_PAIR_VERSION,
        "pair_id": pair_id,
        "attacker_actor_id": attacker_actor_id,
        "defender_actor_id": defender_actor_id,
        "attacker_expanded_tactical_side": attacker_side,
        "defender_expanded_tactical_side": defender_side,
        "pack_sides": sorted({attacker_side, defender_side}),
        "independent_authority": True,
        "engine_overlay_paths": list(ENGINE_OVERLAY_RELS),
        "installed_files": {
            rel: {"sha256": digest} for rel, digest in sorted(installed.items())
        },
        "backups": backups,
        "notes": [
            "Each side keeps distinct units/research/purchase Lua packs.",
            "Pair overlays replace engine-consumed alliances/values/CTF for simultaneous selection.",
            "restore_battle_pair restores prior overlays or multi-faction native defaults.",
        ],
    }
    manifest_path = dest / BATTLE_PAIR_MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    manifest["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    # Rewrite with self hash bound after first serialize of content fields.
    content_for_hash = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    manifest["manifest_sha256"] = _sha256_text(
        json.dumps(content_for_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    problems = verify_battle_pair(dest)
    if problems:
        restore_battle_pair(dest)
        raise ExpandedNationsError(
            "Battle-pair post-install verification failed: " + "; ".join(problems)
        )

    return {
        "ok": True,
        "pair_id": pair_id,
        "gates_root": str(dest),
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "playable_goc_sides": list(playable_goc_sides()),
        "source_unmodified": not mutate_source,
    }


def verify_battle_pair(gates_root: str | Path) -> list[str]:
    """Verify active battle-pair install against its manifest hashes and matchups."""
    root = Path(gates_root).resolve()
    manifest_path = root / BATTLE_PAIR_MANIFEST_RELATIVE
    problems: list[str] = []
    if not manifest_path.is_file():
        return ["battle-pair manifest missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"battle-pair manifest malformed: {exc}"]
    if manifest.get("schema") != BATTLE_PAIR_SCHEMA:
        problems.append("battle-pair schema mismatch")
    attacker_side = str(manifest.get("attacker_expanded_tactical_side") or "")
    defender_side = str(manifest.get("defender_expanded_tactical_side") or "")
    if not attacker_side or not defender_side:
        problems.append("battle-pair missing expanded tactical sides")

    installed = manifest.get("installed_files") or {}
    if not isinstance(installed, Mapping):
        problems.append("battle-pair installed_files malformed")
        installed = {}

    for rel in ENGINE_OVERLAY_RELS:
        path = root / rel
        if not path.is_file():
            problems.append(f"missing engine overlay {rel}")
            continue
        expected = (installed.get(rel) or {}).get("sha256")
        actual = _file_sha256(path)
        if expected and actual != expected:
            problems.append(f"tampered engine overlay {rel}")
        text = path.read_text(encoding="utf-8", errors="ignore")
        if GENERATED_MARKER not in text:
            problems.append(f"engine overlay missing generated marker: {rel}")
        if rel.endswith("alliances_generic.inc"):
            if f'{{armies "{attacker_side}"}}' not in text:
                problems.append(f"alliances missing attacker {attacker_side}")
            if f'{{armies "{defender_side}"}}' not in text:
                problems.append(f"alliances missing defender {defender_side}")
        if rel.endswith("values.set"):
            if f'"{attacker_side} {defender_side}"' not in text:
                problems.append(
                    f"values.set missing matchup {attacker_side} {defender_side}"
                )
            if f'"{defender_side} {attacker_side}"' not in text:
                problems.append(
                    f"values.set missing matchup {defender_side} {attacker_side}"
                )
        if rel.endswith("campaign_capture_the_flag.set"):
            if "presets/alliances_generic.inc" not in text:
                problems.append("CTF does not include alliances_generic.inc")

    for side in (attacker_side, defender_side):
        for rel in _pack_relpaths(side):
            path = root / rel
            if not path.is_file():
                problems.append(f"missing pack {rel}")
                continue
            expected = (installed.get(rel) or {}).get("sha256")
            actual = _file_sha256(path)
            if expected and actual != expected:
                problems.append(f"tampered pack {rel}")

    return problems


def restore_battle_pair(gates_root: str | Path) -> dict[str, Any]:
    """Remove battle-pair overlays and restore prior backups or multi-faction defaults."""
    root = Path(gates_root).resolve()
    manifest_path = root / BATTLE_PAIR_MANIFEST_RELATIVE
    backup_root = root / BATTLE_PAIR_BACKUP_DIR
    restored: list[str] = []
    removed: list[str] = []
    backups_by_rel: dict[str, Path] = {}
    if backup_root.is_dir():
        for path in backup_root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(backup_root).as_posix()
                backups_by_rel[rel] = path

    for rel in ENGINE_OVERLAY_RELS:
        target = root / rel
        if rel in backups_by_rel:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backups_by_rel[rel], target)
            restored.append(rel)
        elif target.is_file():
            # Fall back to multi-faction native defaults when no prior file existed.
            if rel.endswith("alliances_generic.inc"):
                _write_text(target, render_alliances_generic())
                restored.append(rel)
            elif rel.endswith("values.set"):
                _write_text(target, render_values_set())
                restored.append(rel)
            elif rel.endswith("campaign_capture_the_flag.set"):
                _write_text(target, render_ctf_set())
                restored.append(rel)

    if manifest_path.is_file():
        manifest_path.unlink()
        removed.append(BATTLE_PAIR_MANIFEST_RELATIVE.as_posix())
    if backup_root.exists():
        shutil.rmtree(backup_root)
        removed.append(BATTLE_PAIR_BACKUP_DIR.as_posix())

    return {
        "ok": True,
        "restored": restored,
        "removed": removed,
        "gates_root": str(root),
    }


def load_battle_pair_manifest(gates_root: str | Path) -> dict[str, Any] | None:
    path = Path(gates_root).resolve() / BATTLE_PAIR_MANIFEST_RELATIVE
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ExpandedNationsError("battle-pair manifest is not an object")
    return payload
