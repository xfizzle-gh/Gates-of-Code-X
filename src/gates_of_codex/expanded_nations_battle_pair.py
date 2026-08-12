"""Two-sided Expanded Nations battle-pair staging for #194 native harness.

Stages independent native packs for two playable Expanded-mode actors so both
sides can appear simultaneously with distinct roster/research/AI authority.
This is separate from single-actor ``activate`` projections.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .expanded_nations_models import ExpandedNationsError
from .faction_wiring_compiler import FactionWiringCompiler
from .faction_wiring_manifest import load_faction_manifest
from .goc_native_dc_seam import (
    materialize_native_dc_seam,
    render_alliances_generic,
    render_ctf_set,
    render_values_set,
)
from .goc_tactical_army_registry import army_row, is_goc_tactical_side, playable_goc_sides
from .modstack import normalize_stack


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


def render_battle_pair_alliances(attacker_side: str, defender_side: str) -> str:
    """Minimal two-army alliance file placing each side on opposite coalitions."""
    attacker_coalition = "west"
    defender_coalition = "east"
    if is_goc_tactical_side(attacker_side):
        attacker_coalition = str(army_row(attacker_side).get("coalition") or "west")
    if is_goc_tactical_side(defender_side):
        defender_coalition = str(army_row(defender_side).get("coalition") or "east")
    # If both map to same coalition, force defender to the opposite menu column.
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


def materialize_battle_pair(
    repo_root: str | Path,
    *,
    attacker_actor_id: str,
    defender_actor_id: str,
    resource_stack: Sequence[str | Path],
    aio_conquest_lua: str | Path,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    """Materialize independent native packs + pair-specific alliances/values.

    Writes into ``output_root`` (default: repo_root) so both sides keep distinct
    ``units_*/inf_*/unit_research_*/conquest.*.lua`` authority simultaneously.
    """
    if attacker_actor_id == defender_actor_id:
        raise ExpandedNationsError("Battle pair requires two distinct actors")
    root = Path(repo_root).resolve()
    dest = Path(output_root).resolve() if output_root else root
    dest.mkdir(parents=True, exist_ok=True)

    manifest_actors = {row["actor_id"]: row for row in load_faction_manifest()["actors"]}
    attacker = _actor_row(manifest_actors, attacker_actor_id)
    defender = _actor_row(manifest_actors, defender_actor_id)
    attacker_side = str(attacker["tactical_side"])
    defender_side = str(defender["tactical_side"])

    # Ensure full native packs exist for every playable goc side under dest/repo.
    seam = materialize_native_dc_seam(
        dest if dest == root else root,
        resource_stack=resource_stack,
        aio_conquest_lua=aio_conquest_lua,
    )

    # Pair-specific overlays for simultaneous two-sided selection.
    alliances = render_battle_pair_alliances(attacker_side, defender_side)
    values = render_battle_pair_values(attacker_side, defender_side)
    ctf = render_ctf_set()
    pair_dir = dest / "live" / "expanded_nations" / "battle_pairs" / f"{attacker_actor_id}_vs_{defender_actor_id}"
    pair_dir.mkdir(parents=True, exist_ok=True)
    (pair_dir / "alliances_generic.inc").write_text(alliances, encoding="utf-8", newline="\n")
    (pair_dir / "values.set").write_text(values, encoding="utf-8", newline="\n")
    (pair_dir / "campaign_capture_the_flag.set").write_text(ctf, encoding="utf-8", newline="\n")
    manifest = {
        "schema": "gates-of-codex.expanded-nations-battle-pair",
        "schema_version": 1,
        "attacker_actor_id": attacker_actor_id,
        "defender_actor_id": defender_actor_id,
        "attacker_expanded_tactical_side": attacker_side,
        "defender_expanded_tactical_side": defender_side,
        "pack_sides": sorted({attacker_side, defender_side}),
        "independent_authority": True,
        "notes": [
            "Each side keeps distinct units/research/purchase Lua packs.",
            "Pair overlays provide simultaneous alliance/matchup selection.",
            "Single-actor activate projections remain available separately.",
        ],
        "seam_unit_counts": seam.get("unit_counts") or {},
    }
    (pair_dir / "pair_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Verify required pack files exist for both sides.
    missing: list[str] = []
    for side in (attacker_side, defender_side):
        if side == "prc":
            continue
        for rel in (
            f"resource/set/multiplayer/units/conquest/units_{side}.set",
            f"resource/set/multiplayer/units/conquest/inf_{side}.set",
            f"resource/set/dynamic_campaign/unit_research_{side}.set",
            f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
        ):
            if not (root / rel).is_file() and not (dest / rel).is_file():
                missing.append(rel)
    if missing:
        raise ExpandedNationsError(
            "Battle-pair materialize missing native packs: " + ", ".join(missing)
        )

    return {
        "ok": True,
        "pair_dir": str(pair_dir),
        "manifest": manifest,
        "playable_goc_sides": list(playable_goc_sides()),
    }
