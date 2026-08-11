"""Production native Dynamic Conquest seam for Gates-owned goc_* armies (#191/#201).

Follows the owner-confirmed #201 recipe:
army registration, alliances_generic, values.set matchups, roster includes,
inf/units, research, purchase Lua, conquest.lua nationMap/coalitions, CTF.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .goc_tactical_army_registry import (
    GocArmyRegistryError,
    army_row,
    load_goc_army_registry,
    nation_map_id,
    playable_goc_sides,
    render_army_set,
)

CORE_WEST = ("nato", "ukr")
CORE_EAST = ("rusa", "prc")

# Bootstrap DC pack reuses proven Code:X NATO breed paths (same approach as #201 spike).
# Army identity is the goc_* side tag; breeds are not claimed as national authorship.
_BOOTSTRAP_BREEDS = (
    ("mp/nato/2022s/usmc_rifleman", "nato_basic", "13.5"),
    ("mp/nato/2022s/usmc_medic", "nato_medic", "14.0"),
    ("mp/nato/2022s/usmc_teamlead", "nato_basic", "10.5"),
    ("mp/nato/2022s/usmc_antitank_smaw", "nato_basic", "40.0"),
    ("mp/nato/2022s/usmc_vehicleman", "nato_supporter", "10.5"),
)

_CORE_ROSTER_INF = (
    "conquest/inf_ukr.set",
    "conquest/inf_rusa.set",
    "conquest/inf_nato.set",
    "conquest/inf_prc_era1960.set",
    "conquest/inf_csa_era1960.set",
)
_CORE_ROSTER_UNITS = (
    "conquest/units_ukr.set",
    "conquest/units_rusa.set",
    "conquest/units_nato.set",
    "conquest/units_sov_era1960.set",
    "conquest/units_csa_era1960.set",
    "conquest/units_prc_era1960.set",
)

_NATION_MAP_CORE = (
    "rusa = 1, ukr = 2, nato = 3, csa = 4, sov = 5, prc = 6, frg = 7, pol = 8"
)
_NATION_MAP_ALIASES = "rus = 1, ger = 2, fin = 3, usa = 3, eng = 3, jap = 6"


def playable_west_sides() -> tuple[str, ...]:
    return tuple(
        side
        for side in playable_goc_sides()
        if str(army_row(side).get("coalition") or "").lower() == "west"
    )


def playable_east_sides() -> tuple[str, ...]:
    return tuple(
        side
        for side in playable_goc_sides()
        if str(army_row(side).get("coalition") or "").lower() == "east"
    )


def unit_id(side: str, kind: str) -> str:
    return f"{side}_{kind}({side})"


def render_alliances_generic() -> str:
    west_lines = [f'\t{{armies "{name}"}}' for name in CORE_WEST]
    west_lines.extend(f'\t{{armies "{side}"}}' for side in playable_west_sides())
    east_lines = [f'\t{{armies "{name}"}}' for name in CORE_EAST]
    east_lines.extend(f'\t{{armies "{side}"}}' for side in playable_east_sides())
    return (
        '{"West"\n'
        '\t{title "mp/alliance/west"}\n'
        + "\n".join(west_lines)
        + '\n\t{icon "/interface/pages/multi/flag_nato"}\n'
        "}\n"
        '{"East"\n'
        '\t{title "mp/alliance/east"}\n'
        + "\n".join(east_lines)
        + '\n\t{icon "/interface/pages/multi/flag_rusa"}\n'
        "}\n"
    )


def render_ctf_set() -> str:
    return (
        "{Game\n"
        '\t{name "campaign_capture_the_flag"}\n'
        "\t{teamSettings\n"
        "\t\t{armySelectionMode alliance}\n"
        "\t\t{alliances\n"
        '\t\t\t(include "presets/alliances_generic.inc")\n'
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )


def _matchup_pairs() -> list[str]:
    pairs: list[str] = []
    # Preserve Core pairs required by Code:X create-menu regions.
    core_pairs = [
        ("nato", "ukr"),
        ("nato", "rusa"),
        ("nato", "prc"),
        ("ukr", "rusa"),
        ("rusa", "ukr"),
        ("ukr", "prc"),
        ("rusa", "prc"),
        ("prc", "rusa"),
        ("prc", "ukr"),
        ("ukr", "nato"),
        ("rusa", "nato"),
        ("prc", "nato"),
    ]
    for left, right in core_pairs:
        pairs.append(f'"{left} {right}"')
    for side in playable_goc_sides():
        coalition = str(army_row(side).get("coalition") or "").lower()
        opponents = CORE_EAST if coalition == "west" else CORE_WEST
        for opp in opponents:
            pairs.append(f'"{side} {opp}"')
            pairs.append(f'"{opp} {side}"')
    # Stable unique order.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in pairs:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def render_values_set() -> str:
    matchups = "\n\t\t\t".join(_matchup_pairs())
    test_extras = "\n\t\t\t".join(
        f'"{side} rusa"\n\t\t\t"rusa {side}"' for side in playable_goc_sides()
    )
    return (
        "; Gates production GOC values.set (#191)\n"
        "; Core matchups retained; production goc_* both-direction pairs injected.\n"
        "; Empty AvailableMatchups for a shown region crash Dynamic Conquest create.\n"
        "\n"
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
        f"\t\t\t{test_extras}\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
        "\n"
        "{GameModes\n"
        '\t"campaign_capture_the_flag"\n'
        "}\n"
    )


def render_roster_conquest() -> str:
    sides = playable_goc_sides()
    inf_goc = "\n".join(f'\t(include "conquest/inf_{side}.set")' for side in sides)
    units_goc = "\n".join(f'\t(include "conquest/units_{side}.set")' for side in sides)
    core_inf = "\n".join(f'\t(include "{path}")' for path in _CORE_ROSTER_INF)
    core_units = "\n".join(f'\t(include "{path}")' for path in _CORE_ROSTER_UNITS)
    return (
        ";sdl\n"
        "; Gates #191 production roster: Core stack includes + production goc_* packs\n"
        "; Only includes files present under multiplayer/units/conquest/ on the live stack.\n"
        "{units\n"
        '\t(include "conquest/settings.set")\n'
        "\n"
        f"{core_inf}\n"
        f"{inf_goc}\n"
        "\n"
        f"{core_units}\n"
        f"{units_goc}\n"
        "}\n"
    )


def render_inf_set(side: str) -> str:
    lines = [
        f"; #191 production inf costs for {side}.",
        "; Breed paths reuse Code:X nato assets; side tag is the GOC army token.",
        "",
    ]
    for breed, macro, cost in _BOOTSTRAP_BREEDS:
        lines.append(f'{{"{breed}"\t\t("{macro}" side({side})) {{cost {cost}}}}}')
    return "\n".join(lines) + "\n"


def render_units_set(side: str) -> str:
    rifle = unit_id(side, "rifle")
    at = unit_id(side, "at")
    vehicle = unit_id(side, "vehicle")
    return (
        f"; #191 production DC bootstrap units for {side}.\n"
        "; Breeds reuse mp/nato paths; army identity is the goc_* side tag.\n"
        "\n"
        f'{{"{rifle}"\n'
        "\t{charge {delay 0}{interval 0}}\n"
        '\t{content "mp/nato/2022s/usmc_rifleman mp/nato/2022s/usmc_rifleman '
        'mp/nato/2022s/usmc_rifleman mp/nato/2022s/usmc_medic"}\n'
        f'\t{{tags "conquest conquestonly {side} 2022s"}}\n'
        "\t{level 1}\n"
        "\t{cost 120}\n"
        "\t{cp 4}\n"
        "\t{cw 0}\n"
        "\t{research_stage 1}\n"
        "\t{research_stage_max 99}\n"
        "\t{squad_cost_factor 1}\n"
        "\t{round_multiple 5.0}\n"
        '\t{button "inf1"}\n'
        "}\n"
        "\n"
        f'{{"{at}"\n'
        "\t{charge {delay 0}{interval 0}}\n"
        '\t{content "mp/nato/2022s/usmc_teamlead mp/nato/2022s/usmc_antitank_smaw '
        'mp/nato/2022s/usmc_antitank_smaw"}\n'
        f'\t{{tags "conquest conquestonly {side} 2022s"}}\n'
        "\t{level 1}\n"
        "\t{cost 90}\n"
        "\t{cp 3}\n"
        "\t{cw 0}\n"
        "\t{research_stage 1}\n"
        "\t{research_stage_max 99}\n"
        "\t{squad_cost_factor 1}\n"
        "\t{round_multiple 5.0}\n"
        '\t{button "inf2"}\n'
        "}\n"
        "\n"
        f'{{"{vehicle}"\n'
        "\t{charge {delay 0}{interval 0}}\n"
        '\t{content "m1126 ( mp/nato/2022s/usmc_vehicleman mp/nato/2022s/usmc_vehicleman '
        'mp/nato/2022s/usmc_vehicleman )"}\n'
        f'\t{{tags "conquest conquestonly {side} 2022s"}}\n'
        "\t{level 1}\n"
        "\t{cost 200}\n"
        "\t{cp 4}\n"
        "\t{cw 2}\n"
        "\t{research_stage 1}\n"
        "\t{research_stage_max 99}\n"
        "\t{squad_cost_factor 1}\n"
        "\t{round_multiple 5.0}\n"
        '\t{button "vehicles"}\n'
        "}\n"
    )


def render_research_set(side: str) -> str:
    rifle = unit_id(side, "rifle")
    at = unit_id(side, "at")
    vehicle = unit_id(side, "vehicle")
    return (
        "  {IconGap 30}\n"
        "\n"
        f"; #191 production research tree for {side} — isolated GOC bootstrap pool.\n"
        "\n"
        '\t{ tech "reinforcement_stage_1"\t\trequires ""\t\t\t\t\t\t\tcosts 0  position 0 0}\n'
        '\t{ tech "reinforcement_stage_2"\t\trequires "reinforcement_stage_1"\tcosts 1  position 1 0}\n'
        '\t{ tech "reinforcement_stage_3"\t\trequires "reinforcement_stage_2"\tcosts 2  position 2 0}\n'
        '\t{ tech "reinforcement_stage_4"\t\trequires "reinforcement_stage_3"\tcosts 5  position 3 0}\n'
        '\t{ tech "reinforcement_stage_5"\t\trequires "reinforcement_stage_4"\tcosts 7  position 4 0}\n'
        "\t\n"
        '\t{ tech "defense_level_1"\t\t\trequires "reinforcement_stage_2"\tcosts 1  position 7 0}\n'
        '\t{ tech "defense_level_2"\t\t\trequires "defense_level_1"\t\t\tcosts 5  position 8 0}\n'
        '\t{ tech "defense_level_3"\t\t\trequires "defense_level_2"\t\t\tcosts 7  position 9 0}\n'
        "\n"
        f'\t{{"{rifle}"\t\t\trequires ""\t\t\t\tcosts 1 position 1 2}}\n'
        f'\t{{"{at}"\t\t\trequires "{rifle}"\t\t\t\tcosts 1 position 3 2}}\n'
        f'\t{{"{vehicle}"\t\t\trequires "{rifle}"\t\t\t\tcosts 2 position 5 2}}\n'
    )


def render_purchase_lua(side: str) -> str:
    rifle = unit_id(side, "rifle")
    at = unit_id(side, "at")
    vehicle = unit_id(side, "vehicle")
    return (
        "Purchases = Purchases or {}\n"
        f'Purchases["conquest.{side}"] = {{\n'
        "\t{Repeat = 0,\n"
        "\t\tUnits = {\n"
        f'\t\t\t{{priority = 2.2, type = {{"Class2", "Infantry", "Squad"}}, unit = "{rifle}"}},\n'
        f'\t\t\t{{priority = 1.5, type = {{"Class2", "Infantry", "Squad", "AT"}}, unit = "{at}"}},\n'
        f'\t\t\t{{priority = 0.8, type = {{"Class1", "Armored", "Vehicle"}}, unit = "{vehicle}"}},\n'
        "\t\t}\n"
        "\t},\n"
        "}\n"
    )


def render_nation_map_entries() -> str:
    parts = [_NATION_MAP_CORE]
    for side in playable_goc_sides():
        parts.append(f"{side} = {nation_map_id(side)}")
    return ", ".join(parts)


def render_west_nations_table() -> str:
    entries = [
        "nato = true",
        "ukr = true",
        "csa = true",
        "frg = true",
        "usa = true",
        "eng = true",
        "ger = true",
        "fin = true",
    ]
    entries.extend(f"{side} = true" for side in playable_west_sides())
    return "{ " + ", ".join(entries) + " }"


def render_east_nations_table() -> str:
    entries = [
        "rusa = true",
        "sov = true",
        "prc = true",
        "pol = true",
        "rus = true",
        "jap = true",
    ]
    entries.extend(f"{side} = true" for side in playable_east_sides())
    return "{ " + ", ".join(entries) + " }"


def patch_conquest_lua(aio_text: str) -> str:
    """Surgically inject production GOC nationMap and coalition tables into AIO conquest.lua."""
    if "local nationMap" not in aio_text:
        raise GocArmyRegistryError("AIO conquest.lua missing nationMap anchor")
    nation_body = render_nation_map_entries()
    alias_body = _NATION_MAP_ALIASES
    west_body = render_west_nations_table()
    east_body = render_east_nations_table()

    nation_pattern = re.compile(
        r"local\s+nationMap\s*=\s*\{.*?\}\s*"
        r"(?:--[^\n]*\n\s*)*"
        r"(?:rus\s*=\s*1.*?jap\s*=\s*6\s*)?\}",
        re.DOTALL,
    )
    # Prefer exact multi-line replacement of the AIO two-line nationMap block.
    nation_block = (
        f"\tlocal nationMap = {{ {nation_body},\n"
        f"\t\t-- legacy / alias ids\n"
        f"\t\t{alias_body} }}"
    )
    text, n1 = re.subn(
        r"\tlocal nationMap = \{ rusa = 1, ukr = 2, nato = 3, csa = 4, sov = 5, prc = 6, frg = 7, pol = 8,\n"
        r"\t\t-- legacy / alias ids\n"
        r"\t\trus = 1, ger = 2, fin = 3, usa = 3, eng = 3, jap = 6 \}",
        nation_block,
        aio_text,
        count=1,
    )
    if n1 != 1:
        # Already patched or format drift: replace nationMap table contents if GOC keys missing.
        if "goc_bel" not in aio_text:
            raise GocArmyRegistryError(
                "Unable to patch conquest.lua nationMap; AIO format unexpected"
            )
        text = aio_text

    text, n2 = re.subn(
        r"local eastNations = \{[^\}]+\}",
        f"local eastNations = {east_body}",
        text,
        count=1,
    )
    text, n3 = re.subn(
        r"local westNations = \{[^\}]+\}",
        f"local westNations = {west_body}",
        text,
        count=1,
    )
    if n2 != 1 or n3 != 1:
        raise GocArmyRegistryError(
            "Unable to patch conquest.lua east/west nation tables"
        )
    for side in playable_goc_sides():
        if side not in text:
            raise GocArmyRegistryError(f"Patched conquest.lua missing {side}")
    return text


def render_dlg_mp_keys() -> str:
    lines = [
        "# #191 production army labels (merge into dlg_mp2.pot on deploy if needed)",
        "",
    ]
    registry = load_goc_army_registry()["armies"]
    for side in sorted(registry):
        actor = registry[side]["actor_id"]
        display = {
            "bel": "Belgium",
            "prt": "Portugal",
            "cze": "Czechia",
            "svk": "Slovakia",
            "hun": "Hungary",
            "ltu": "Lithuania",
            "lva": "Latvia",
            "est": "Estonia",
            "aut": "Austria",
            "che": "Switzerland",
            "irl": "Ireland",
            "isl": "Iceland",
        }.get(actor, actor.upper())
        lines.append(f'msgid "mp/army/{side}"')
        lines.append(f'msgstr "{display}"')
        lines.append("")
    return "\n".join(lines)


def expected_seam_relpaths() -> list[str]:
    paths = [
        "resource/set/multiplayer/games/presets/alliances_generic.inc",
        "resource/set/multiplayer/games/campaign_capture_the_flag.set",
        "resource/set/dynamic_campaign/values.set",
        "resource/set/multiplayer/units/roster_conquest.set",
        "resource/script/multiplayer/modes/conquest.lua",
        "resource/localizations/default/interface/text/dlg_mp_goc_phase2.pot",
    ]
    for side in sorted(load_goc_army_registry()["armies"]):
        paths.append(f"resource/set/multiplayer/armies/{side}.set")
    for side in playable_goc_sides():
        paths.extend(
            [
                f"resource/set/multiplayer/units/conquest/inf_{side}.set",
                f"resource/set/multiplayer/units/conquest/units_{side}.set",
                f"resource/set/dynamic_campaign/unit_research_{side}.set",
                f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
            ]
        )
    return paths


def materialize_native_dc_seam(
    repo_root: str | Path,
    *,
    aio_conquest_lua: str | Path | None = None,
    flag_source: str | Path | None = None,
) -> dict[str, Any]:
    """Write production native DC seam files under repo_root/resource."""
    root = Path(repo_root)
    written: list[str] = []

    def _write(rel: str, text: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(rel.replace("\\", "/"))

    for side in sorted(load_goc_army_registry()["armies"]):
        _write(f"resource/set/multiplayer/armies/{side}.set", render_army_set(side))

    _write(
        "resource/set/multiplayer/games/presets/alliances_generic.inc",
        render_alliances_generic(),
    )
    _write(
        "resource/set/multiplayer/games/campaign_capture_the_flag.set",
        render_ctf_set(),
    )
    _write("resource/set/dynamic_campaign/values.set", render_values_set())
    _write(
        "resource/set/multiplayer/units/roster_conquest.set",
        render_roster_conquest(),
    )
    _write(
        "resource/localizations/default/interface/text/dlg_mp_goc_phase2.pot",
        render_dlg_mp_keys(),
    )

    for side in playable_goc_sides():
        _write(
            f"resource/set/multiplayer/units/conquest/inf_{side}.set",
            render_inf_set(side),
        )
        _write(
            f"resource/set/multiplayer/units/conquest/units_{side}.set",
            render_units_set(side),
        )
        _write(
            f"resource/set/dynamic_campaign/unit_research_{side}.set",
            render_research_set(side),
        )
        _write(
            f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
            render_purchase_lua(side),
        )

    if aio_conquest_lua is None:
        raise GocArmyRegistryError(
            "aio_conquest_lua path is required to materialize conquest.lua"
        )
    aio_path = Path(aio_conquest_lua)
    if not aio_path.is_file():
        raise GocArmyRegistryError(f"AIO conquest.lua not found: {aio_path}")
    patched = patch_conquest_lua(aio_path.read_text(encoding="utf-8", errors="ignore"))
    _write("resource/script/multiplayer/modes/conquest.lua", patched)

    flag_copies = 0
    if flag_source is not None:
        source = Path(flag_source)
        if source.is_file():
            for side in sorted(load_goc_army_registry()["armies"]):
                dest = root / "resource/interface/pages/multi" / f"flag_{side}.tga"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(source.read_bytes())
                written.append(str(dest.relative_to(root)).replace("\\", "/"))
                flag_copies += 1

    # Remove obsolete fragment that is no longer the active alliance SoT.
    obsolete = root / "resource/set/multiplayer/games/presets/alliances_goc_production_west.inc"
    removed = False
    if obsolete.is_file():
        obsolete.unlink()
        removed = True

    return {
        "written": sorted(written),
        "playable_sides": list(playable_goc_sides()),
        "flag_copies": flag_copies,
        "removed_obsolete_alliance_fragment": removed,
    }


def validate_repo_native_dc_seam(repo_root: str | Path) -> list[str]:
    """Return problems if the committed seam is incomplete or inactive."""
    root = Path(repo_root)
    problems: list[str] = []
    for rel in expected_seam_relpaths():
        path = root / rel
        if not path.is_file():
            problems.append(f"missing {rel}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if rel.endswith("alliances_generic.inc"):
            for side in playable_west_sides():
                if f'{{armies "{side}"}}' not in text:
                    problems.append(f"alliances_generic missing {side}")
            for core in CORE_WEST + CORE_EAST:
                if f'{{armies "{core}"}}' not in text:
                    problems.append(f"alliances_generic missing core {core}")
        if rel.endswith("campaign_capture_the_flag.set"):
            if 'presets/alliances_generic.inc' not in text:
                problems.append("CTF does not include alliances_generic.inc")
        if rel.endswith("values.set"):
            for side in playable_goc_sides():
                if side not in text:
                    problems.append(f"values.set missing matchups for {side}")
        if rel.endswith("roster_conquest.set"):
            for side in playable_goc_sides():
                if f"inf_{side}.set" not in text or f"units_{side}.set" not in text:
                    problems.append(f"roster missing includes for {side}")
        if rel.endswith("conquest.lua"):
            for side in playable_goc_sides():
                if side not in text:
                    problems.append(f"conquest.lua missing {side}")
            if "westNations" not in text or "eastNations" not in text:
                problems.append("conquest.lua missing coalition tables")
        if "/units/" in rel and rel.endswith(".lua"):
            if "Repeat" not in text or "Units" not in text:
                problems.append(f"purchase lua schema invalid: {rel}")
    obsolete = root / "resource/set/multiplayer/games/presets/alliances_goc_production_west.inc"
    if obsolete.is_file():
        problems.append(
            "obsolete alliances_goc_production_west.inc still present; "
            "alliances_generic.inc is the active SoT"
        )
    return problems
