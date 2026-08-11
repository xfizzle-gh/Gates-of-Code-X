"""Production Gates-owned tactical army token registry (#201 architecture)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable, Mapping

from .faction_wiring_models import FactionWiringError

REGISTRY_SCHEMA = "gates-of-codex.goc-tactical-army-registry"
SAFE_ARMY_RE = re.compile(r"^goc_[a-z][a-z0-9_]*$")
CORE_TACTICAL_SIDES = frozenset({"nato", "ukr", "rusa", "prc"})


class GocArmyRegistryError(FactionWiringError):
    pass


@lru_cache(maxsize=1)
def load_goc_army_registry() -> dict[str, Any]:
    raw = files("gates_of_codex").joinpath("data/goc_tactical_army_registry.json").read_text(
        encoding="utf-8"
    )
    payload = json.loads(raw)
    validate_goc_army_registry(payload)
    return payload


def validate_goc_army_registry(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise GocArmyRegistryError("Unsupported GOC army registry schema")
    armies = payload.get("armies")
    if not isinstance(armies, dict) or not armies:
        raise GocArmyRegistryError("GOC army registry requires a non-empty armies object")
    lo, hi = payload.get("engine_id_range", [0, 99])
    used_ids: dict[int, str] = {}
    reserved: set[int] = set()
    for band in (payload.get("reserved_bands") or {}).values():
        if isinstance(band, dict):
            reserved.update(int(x) for x in band.get("ids") or [])
    for token, row in armies.items():
        if not SAFE_ARMY_RE.fullmatch(token):
            raise GocArmyRegistryError(f"Invalid GOC army token: {token}")
        if not isinstance(row, dict):
            raise GocArmyRegistryError(f"Army row for {token} must be an object")
        numeric_id = row.get("numeric_id")
        if not isinstance(numeric_id, int) or isinstance(numeric_id, bool):
            raise GocArmyRegistryError(f"Army {token} numeric_id must be an int")
        if numeric_id < int(lo) or numeric_id > int(hi):
            raise GocArmyRegistryError(f"Army {token} id {numeric_id} outside engine range")
        if numeric_id in reserved:
            raise GocArmyRegistryError(
                f"Army {token} id {numeric_id} collides with reserved band"
            )
        if numeric_id in used_ids:
            raise GocArmyRegistryError(
                f"Duplicate numeric army id {numeric_id}: {used_ids[numeric_id]} and {token}"
            )
        used_ids[numeric_id] = token
        actor_id = row.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id:
            raise GocArmyRegistryError(f"Army {token} missing actor_id")
        if "playable" not in row:
            raise GocArmyRegistryError(f"Army {token} missing playable flag")


def registered_goc_sides() -> frozenset[str]:
    return frozenset(load_goc_army_registry()["armies"].keys())


def supported_tactical_sides() -> frozenset[str]:
    return CORE_TACTICAL_SIDES | registered_goc_sides()


def is_goc_tactical_side(side: str) -> bool:
    return side in registered_goc_sides()


def army_row(side: str) -> dict[str, Any]:
    armies = load_goc_army_registry()["armies"]
    if side not in armies:
        raise GocArmyRegistryError(f"Unknown GOC army token: {side}")
    return dict(armies[side])


def army_numeric_id(side: str) -> int:
    return int(army_row(side)["numeric_id"])


def actor_id_for_army(side: str) -> str:
    return str(army_row(side)["actor_id"])


def research_relative_for_side(side: str) -> Path:
    if side not in supported_tactical_sides():
        raise GocArmyRegistryError(f"Unsupported tactical side for research path: {side}")
    return Path(f"resource/set/dynamic_campaign/unit_research_{side}.set")


def side_family_for(side: str) -> frozenset[str]:
    """Player-side family used to classify inherited purchase definitions."""
    if side in CORE_TACTICAL_SIDES:
        families = {
            "nato": frozenset({"nato", "frg"}),
            "ukr": frozenset({"ukr"}),
            "rusa": frozenset({"rusa", "sov", "csa"}),
            "prc": frozenset({"prc"}),
        }
        return families[side]
    if is_goc_tactical_side(side):
        # Custom Gates armies are identity-isolated: only their own token is "player family".
        return frozenset({side})
    raise GocArmyRegistryError(f"Unsupported tactical side family: {side}")


def campaign_faction_token_for_side(side: str) -> str:
    """Map engine/DC army token to campaign Faction token (nato/ukr/rusa/prc/neutral).

    Production GOC armies keep distinct engine tokens for Dynamic Conquest identity
    while province/force ownership stays on the four core campaign factions.
    """
    token = str(side or "").strip().lower()
    if token in CORE_TACTICAL_SIDES or token == "neutral":
        return token
    if is_goc_tactical_side(token):
        coalition = str(army_row(token).get("coalition") or "").strip().lower()
        if coalition == "west":
            return "nato"
        if coalition == "east":
            return "rusa"
        raise GocArmyRegistryError(
            f"GOC army {token} missing west/east coalition for campaign faction mapping"
        )
    raise GocArmyRegistryError(f"Unsupported tactical side for campaign faction: {token}")


def render_army_set(side: str) -> str:
    row = army_row(side)
    numeric_id = int(row["numeric_id"])
    return (
        "{army\n"
        f"\t{{id {numeric_id}}}\n"
        f'\t{{title "mp/army/{side}"}}\n'
        f'\t{{icon "/interface/pages/multi/flag_{side}"}}\n'
        "}\n"
    )


def audit_numeric_ids_against_stack(army_roots: Iterable[str | Path]) -> list[str]:
    """Return collision messages for registry IDs found under foreign army names."""
    registry = load_goc_army_registry()
    owned = {
        int(row["numeric_id"]): token for token, row in registry["armies"].items()
    }
    collisions: list[str] = []
    for root in army_roots:
        armies_dir = Path(root) / "resource" / "set" / "multiplayer" / "armies"
        if not armies_dir.is_dir():
            continue
        for path in armies_dir.glob("*.set"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"\{id\s+(\d+)\}", text)
            if not match:
                continue
            numeric_id = int(match.group(1))
            if numeric_id not in owned:
                continue
            token = owned[numeric_id]
            if path.stem != token:
                collisions.append(
                    f"id {numeric_id} owned by registry token {token} but found as "
                    f"{path.stem} under {root}"
                )
    return collisions
