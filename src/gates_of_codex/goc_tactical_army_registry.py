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


def _band_ids(band: Mapping[str, Any]) -> set[int]:
    ids: set[int] = set()
    if "ids" in band:
        ids.update(int(x) for x in (band.get("ids") or []))
    if "start" in band and "end" in band:
        start = int(band["start"])
        end = int(band["end"])
        if end < start:
            raise GocArmyRegistryError(f"Invalid band range {start}-{end}")
        ids.update(range(start, end + 1))
    return ids


def validate_goc_army_registry(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise GocArmyRegistryError("Unsupported GOC army registry schema")
    armies = payload.get("armies")
    if not isinstance(armies, dict) or not armies:
        raise GocArmyRegistryError("GOC army registry requires a non-empty armies object")
    lo, hi = payload.get("engine_id_range", [0, 99])
    production_band = payload.get("production_band")
    if not isinstance(production_band, dict):
        raise GocArmyRegistryError("GOC army registry requires production_band")
    try:
        prod_lo = int(production_band["start"])
        prod_hi = int(production_band["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GocArmyRegistryError("production_band requires integer start/end") from exc
    if prod_lo < int(lo) or prod_hi > int(hi) or prod_hi < prod_lo:
        raise GocArmyRegistryError(
            f"production_band {prod_lo}-{prod_hi} outside engine range {lo}-{hi}"
        )
    used_ids: dict[int, str] = {}
    reserved: set[int] = set()
    for band in (payload.get("reserved_bands") or {}).values():
        if isinstance(band, dict):
            reserved |= _band_ids(band)
    # Optional documented sub-bands must sit inside production_band and outside reserved.
    for name, band in (payload.get("allocation_sub_bands") or {}).items():
        if not isinstance(band, dict):
            raise GocArmyRegistryError(f"allocation_sub_bands.{name} must be an object")
        for numeric_id in _band_ids(band):
            if numeric_id < prod_lo or numeric_id > prod_hi:
                raise GocArmyRegistryError(
                    f"allocation_sub_bands.{name} id {numeric_id} outside production_band"
                )
            if numeric_id in reserved:
                raise GocArmyRegistryError(
                    f"allocation_sub_bands.{name} id {numeric_id} collides with reserved band"
                )
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
        if numeric_id < prod_lo or numeric_id > prod_hi:
            raise GocArmyRegistryError(
                f"Army {token} id {numeric_id} outside production_band {prod_lo}-{prod_hi}"
            )
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
        nation_map = row.get("nation_map_id")
        if not isinstance(nation_map, int) or isinstance(nation_map, bool):
            raise GocArmyRegistryError(f"Army {token} missing integer nation_map_id")
        if nation_map < 1 or nation_map > 99:
            raise GocArmyRegistryError(f"Army {token} nation_map_id out of range")


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


def playable_goc_sides() -> tuple[str, ...]:
    armies = load_goc_army_registry()["armies"]
    return tuple(
        sorted(
            token
            for token, row in armies.items()
            if bool(row.get("playable"))
        )
    )


def nation_map_id(side: str) -> int:
    row = army_row(side)
    value = row.get("nation_map_id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise GocArmyRegistryError(f"Army {side} missing integer nation_map_id")
    return value


_ARMY_ID_RE = re.compile(r"\{id\s+(\d+)\}")
_ARMY_SET_IN_PAK_RE = re.compile(
    r"(?:^|/)(?:resource/)?set/multiplayer/armies/([^/]+)\.set$",
    re.IGNORECASE,
)


def iter_stack_army_definitions(
    roots: Iterable[str | Path],
) -> list[dict[str, Any]]:
    """Enumerate army token→id mappings from loose files and ZIP-format .pak archives.

    Covers the accepted five-layer authority model: Vanilla (PAK), West81, Code:X,
    AIO, and Gates. Non-ZIP containers are reported as unscanned.
    """
    import zipfile

    found: list[dict[str, Any]] = []
    for root in roots:
        root_path = Path(root)
        label = str(root_path)
        armies_dir = root_path / "resource" / "set" / "multiplayer" / "armies"
        if armies_dir.is_dir():
            for path in sorted(armies_dir.glob("*.set")):
                text = path.read_text(encoding="utf-8", errors="ignore")
                match = _ARMY_ID_RE.search(text)
                if not match:
                    continue
                found.append(
                    {
                        "root": label,
                        "source": "loose",
                        "path": str(path),
                        "token": path.stem,
                        "numeric_id": int(match.group(1)),
                    }
                )
        pak_candidates: list[Path] = []
        direct = root_path / "resource" / "gamelogic.pak"
        if direct.is_file():
            pak_candidates.append(direct)
        resource_dir = root_path / "resource"
        if resource_dir.is_dir():
            pak_candidates.extend(sorted(resource_dir.glob("*.pak")))
        if root_path.is_dir():
            pak_candidates.extend(sorted(root_path.glob("*.pak")))
        seen_pak: set[Path] = set()
        for pak in pak_candidates:
            resolved = pak.resolve()
            if resolved in seen_pak or not pak.is_file():
                continue
            seen_pak.add(resolved)
            try:
                archive = zipfile.ZipFile(pak)
            except zipfile.BadZipFile:
                found.append(
                    {
                        "root": label,
                        "source": "pak_unreadable",
                        "path": str(pak),
                        "token": "",
                        "numeric_id": -1,
                        "note": "not_zip_or_corrupt",
                    }
                )
                continue
            with archive:
                for name in archive.namelist():
                    normalized = name.replace("\\", "/")
                    match_name = _ARMY_SET_IN_PAK_RE.search(normalized)
                    if not match_name:
                        continue
                    token = match_name.group(1)
                    try:
                        text = archive.read(name).decode("utf-8", errors="ignore")
                    except KeyError:
                        continue
                    match = _ARMY_ID_RE.search(text)
                    if not match:
                        continue
                    found.append(
                        {
                            "root": label,
                            "source": "pak",
                            "path": f"{pak}!{normalized}",
                            "token": token,
                            "numeric_id": int(match.group(1)),
                        }
                    )
    return found


def audit_numeric_ids_against_stack(army_roots: Iterable[str | Path]) -> list[str]:
    """Return collision messages for registry IDs found under foreign army names."""
    registry = load_goc_army_registry()
    owned = {
        int(row["numeric_id"]): token for token, row in registry["armies"].items()
    }
    collisions: list[str] = []
    for entry in iter_stack_army_definitions(army_roots):
        if entry.get("source") == "pak_unreadable":
            continue
        numeric_id = int(entry["numeric_id"])
        if numeric_id not in owned:
            continue
        token = owned[numeric_id]
        found_token = str(entry.get("token") or "")
        if found_token != token:
            collisions.append(
                f"id {numeric_id} owned by registry token {token} but found as "
                f"{found_token or '<unknown>'} under {entry['path']}"
            )
    return collisions


def collect_stack_army_id_inventory(
    army_roots: Iterable[str | Path],
) -> dict[str, Any]:
    """Build a deterministic inventory used as collision-audit evidence."""
    entries = iter_stack_army_definitions(army_roots)
    by_id: dict[int, list[dict[str, str]]] = {}
    unscanned: list[str] = []
    for entry in entries:
        if entry.get("source") == "pak_unreadable":
            unscanned.append(str(entry["path"]))
            continue
        numeric_id = int(entry["numeric_id"])
        by_id.setdefault(numeric_id, []).append(
            {
                "token": str(entry["token"]),
                "source": str(entry["source"]),
                "path": str(entry["path"]),
            }
        )
    return {
        "observed_ids": sorted(by_id),
        "by_id": {str(key): value for key, value in sorted(by_id.items())},
        "unscanned_non_zip_paks": sorted(unscanned),
        "entry_count": sum(len(v) for v in by_id.values()),
    }
