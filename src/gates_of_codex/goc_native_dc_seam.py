"""Production native Dynamic Conquest seam for Gates-owned goc_* armies (#191/#201).

Native per-side packs are a deterministic rendering of the #190-approved
faction-wiring / compiler actor authority (not disposable bootstrap prototypes).

``roster_conquest.set`` lifecycle (single owner contract):
- Never committed; always generated under the ignored runtime path.
- ``materialize_native_dc_seam`` writes the multi-faction native-DC roster
  (complete core includes + all playable production goc packs).
- Expanded Nations activation may overwrite the same path with a single-actor
  isolation roster. Both generators share CANONICAL core include lists.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .expanded_nations_actor_sources import (
    normalize_actor_purchase_ids,
    project_actor_units,
)
from .expanded_nations_breeds import project_actor_breed_files
from .expanded_nations_inf_costs import project_actor_inf_cost_rows
from .expanded_nations_models import (
    BROAD_ROSTER_INCLUDES,
    CANONICAL_INF_INCLUDES,
    GENERATED_MARKER,
)
from .expanded_nations_render import project_research_nodes, render_research_file
from .faction_wiring_compiler import FactionWiringCompiler
from .goc_tactical_army_registry import (
    GocArmyRegistryError,
    army_row,
    dc_menu_goc_sides,
    load_goc_army_registry,
    nation_map_id,
    playable_goc_sides,
    render_army_set,
)
from .modstack import normalize_stack

CORE_WEST = ("nato", "ukr")
CORE_EAST = ("rusa", "prc")

_NATION_MAP_CORE = (
    "rusa = 1, ukr = 2, nato = 3, csa = 4, sov = 5, prc = 6, frg = 7, pol = 8"
)
_NATION_MAP_ALIASES = "rus = 1, ger = 2, fin = 3, usa = 3, eng = 3, jap = 6"

_ROSTER_RELATIVE = "resource/set/multiplayer/units/roster_conquest.set"
_RESOLVED_UNIT_RE = re.compile(r"^;\s*resolved_unit=(.+?)\s*$", re.MULTILINE)
_LUA_PURCHASE_RE = re.compile(r'\bunit\s*=\s*"([^"]+)"')


def playable_west_sides() -> tuple[str, ...]:
    return tuple(
        side
        for side in dc_menu_goc_sides()
        if str(army_row(side).get("coalition") or "").lower() == "west"
    )


def playable_east_sides() -> tuple[str, ...]:
    return tuple(
        side
        for side in dc_menu_goc_sides()
        if str(army_row(side).get("coalition") or "").lower() == "east"
    )


def actor_id_for_side(side: str) -> str:
    return str(army_row(side)["actor_id"])


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
    for side in dc_menu_goc_sides():
        coalition = str(army_row(side).get("coalition") or "").lower()
        opponents = CORE_EAST if coalition == "west" else CORE_WEST
        for opp in opponents:
            pairs.append(f'"{side} {opp}"')
            pairs.append(f'"{opp} {side}"')
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
        f'"{side} rusa"\n\t\t\t"rusa {side}"' for side in dc_menu_goc_sides()
    )
    return (
        "; Gates production GOC values.set (#191)\n"
        "; Core matchups retained; production goc_* both-direction pairs injected.\n"
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
    """Multi-faction native DC roster: complete core + production goc packs.

    Uses the same canonical core include lists as Expanded Nations. Runtime-only.
    """
    sides = dc_menu_goc_sides()
    lines = [
        ";sdl",
        GENERATED_MARKER,
        "; mode=native_multi_faction_dc",
        "; owner=goc_native_dc_seam.materialize_native_dc_seam",
        "{units",
        '\t(include "conquest/settings.set")',
        "",
    ]
    lines.extend(f'\t(include "{path}")' for path in CANONICAL_INF_INCLUDES)
    lines.extend(f'\t(include "conquest/inf_{side}.set")' for side in sides)
    lines.append("")
    lines.extend(f'\t(include "{path}")' for path in BROAD_ROSTER_INCLUDES)
    lines.extend(f'\t(include "conquest/units_{side}.set")' for side in sides)
    lines.extend(["}", ""])
    return "\n".join(lines)


def render_units_set_from_projection(
    actor: Mapping[str, Any],
    body: str,
) -> str:
    side = str(actor["tactical_side"])
    return (
        f"{GENERATED_MARKER}\n"
        f"; #191 production native DC units for {side}\n"
        f"; actor_id={actor['actor_id']}\n"
        f"; display_name={actor['display_name']}\n"
        f"; tactical_side={side}\n"
        f"; unit_count={actor['unit_count']}\n"
        f"; components={','.join(actor.get('components') or [])}\n"
        "; Deterministic rendering of #190-approved compiler actor authority.\n"
        "; Source definitions projected from the installed stack; not bootstrap prototypes.\n\n"
        + body
    )


def render_inf_set_from_projection(actor: Mapping[str, Any], body: str) -> str:
    side = str(actor["tactical_side"])
    if not body.strip():
        return (
            f"{GENERATED_MARKER}\n"
            f"; #191 production inf costs for {side} (none required)\n"
            f"; actor_id={actor['actor_id']}\n"
        )
    return (
        f"{GENERATED_MARKER}\n"
        f"; #191 production inf costs for {side}\n"
        f"; actor_id={actor['actor_id']}\n"
        f"; tactical_side={side}\n\n"
        + body
    )


def _lua_type_for_unit(unit: Mapping[str, Any]) -> list[str]:
    category = str(unit.get("category") or "infantry").lower()
    name = str(unit.get("unit_name") or "").lower()
    if category == "infantry" or "squad_" in name:
        tags = ["Class2", "Infantry", "Squad"]
        if "_at" in name or "javelin" in name or "smaw" in name:
            tags.append("AT")
        return tags
    if category == "tank":
        return ["Class1", "Armored", "Tank"]
    if category in {"ifv", "vehicle", "apc"}:
        return ["Class1", "Armored", "Vehicle"]
    if category == "artillery":
        return ["Class1", "Artillery"]
    if category in {"air_defense", "aa"}:
        return ["Class1", "AirDefence"]
    if category in {"aviation", "air"}:
        return ["Class1", "Aviation"]
    if category == "anti_armor":
        return ["Class1", "Armored", "AT"]
    return ["Class2", "Infantry", "Squad"]


def render_purchase_lua_from_actor(actor: Mapping[str, Any]) -> str:
    """Render AI purchases from already-normalized native purchase IDs.

    ``normalize_actor_purchase_ids`` is the sole ID authority. In particular,
    block-form definitions such as ``vz_77_dana`` remain bare IDs while macro
    purchases carry the engine-derived ``name(goc_side)`` suffix. Never infer
    or append a suffix here: doing so creates an AI ID that has no matching
    unit/research definition.
    """
    side = str(actor["tactical_side"])
    units = sorted(actor.get("units") or [], key=lambda row: str(row["unit_name"]))
    lines = [
        "Purchases = Purchases or {}",
        f'Purchases["conquest.{side}"] = {{',
        "\t{Repeat = 0,",
        "\t\tUnits = {",
    ]
    for index, unit in enumerate(units):
        purchase_id = str(unit["unit_name"])
        tags = _lua_type_for_unit(unit)
        tag_lit = ", ".join(f'"{item}"' for item in tags)
        priority = max(0.2, 2.5 - (index * 0.02))
        lines.append(
            f'\t\t\t{{priority = {priority:.2f}, type = {{{tag_lit}}}, unit = "{purchase_id}"}},'
        )
    lines.extend(["\t\t}", "\t},", "}", ""])
    return "\n".join(lines)


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
    if n1 != 1 and "goc_bel" not in aio_text:
        raise GocArmyRegistryError(
            "Unable to patch conquest.lua nationMap; AIO format unexpected"
        )
    if n1 != 1:
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
        "# #191/#192 production army labels (merge into dlg_mp2.pot on deploy if needed)",
        "",
    ]
    registry = load_goc_army_registry()["armies"]
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
        "grc": "Greece",
        "rou": "Romania",
        "bgr": "Bulgaria",
        "hrv": "Croatia",
        "svn": "Slovenia",
        "bih": "Bosnia and Herzegovina",
        "mne": "Montenegro",
        "alb": "Albania",
        "mkd": "North Macedonia",
        "mda": "Moldova",
        "geo": "Georgia",
        "arm": "Armenia",
        "aze": "Azerbaijan",
        "isr": "Israel",
        "lbn": "Lebanon",
        "syr": "Syria",
        "jor": "Jordan",
        "irq": "Iraq",
        "mar": "Morocco",
        "dza": "Algeria",
        "tun": "Tunisia",
        "lby": "Libya",
        "egy": "Egypt",
        "cyp": "Cyprus",
        "mlt": "Malta",
    }
    for side in sorted(registry):
        actor = registry[side]["actor_id"]
        lines.append(f'msgid "mp/army/{side}"')
        lines.append(f'msgstr "{display.get(actor, actor.upper())}"')
        lines.append("")
    return "\n".join(lines)


def committed_seam_relpaths() -> list[str]:
    """Paths that must be committed (roster_conquest.set is intentionally excluded)."""
    paths = [
        "resource/set/multiplayer/games/presets/alliances_generic.inc",
        "resource/set/multiplayer/games/campaign_capture_the_flag.set",
        "resource/set/dynamic_campaign/values.set",
        "resource/script/multiplayer/modes/conquest.lua",
        "resource/localizations/default/interface/text/dlg_mp_goc_phase2.pot",
    ]
    for side in sorted(load_goc_army_registry()["armies"]):
        paths.append(f"resource/set/multiplayer/armies/{side}.set")
    for side in dc_menu_goc_sides():
        paths.extend(
            [
                f"resource/set/multiplayer/units/conquest/inf_{side}.set",
                f"resource/set/multiplayer/units/conquest/units_{side}.set",
                f"resource/set/dynamic_campaign/unit_research_{side}.set",
                f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
            ]
        )
    return paths


def expected_seam_relpaths() -> list[str]:
    return committed_seam_relpaths()


def _select_playable_actors(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    by_id = {str(row["actor_id"]): row for row in payload["actors"]}
    selected: dict[str, dict[str, Any]] = {}
    for side in playable_goc_sides():
        actor_id = actor_id_for_side(side)
        actor = by_id.get(actor_id)
        if actor is None:
            raise GocArmyRegistryError(f"Resolved catalog missing actor {actor_id}")
        if str(actor.get("tactical_side")) != side:
            raise GocArmyRegistryError(
                f"Actor {actor_id} tactical_side {actor.get('tactical_side')} != {side}"
            )
        if not actor.get("playable"):
            raise GocArmyRegistryError(f"Playable registry side {side} actor is not playable")
        if int(actor.get("unit_count") or 0) < 1:
            raise GocArmyRegistryError(
                f"Playable actor {actor_id} resolved zero units from #190 authority"
            )
        selected[side] = actor
    return selected


def _is_managed_breed_projection(path: Path) -> bool:
    try:
        head = path.read_bytes()[:512].decode("utf-8-sig", errors="replace")
    except OSError:
        return False
    return GENERATED_MARKER in head


def _replace_actor_breed_namespace(
    root: Path,
    side: str,
    outputs: Mapping[Path, bytes],
) -> tuple[list[str], int]:
    """Replace only managed files in one goc_* breed namespace."""
    relative_root = Path("resource/set/breed/mp") / side
    side_root = root / relative_root
    desired = {(root / relative).resolve() for relative in outputs}
    removed = 0

    if side_root.is_dir():
        for path in sorted(
            (candidate for candidate in side_root.rglob("*") if candidate.is_file()),
            key=lambda item: item.as_posix(),
            reverse=True,
        ):
            if path.resolve() in desired:
                continue
            if not _is_managed_breed_projection(path):
                continue
            path.unlink()
            removed += 1
        for directory in sorted(
            (candidate for candidate in side_root.rglob("*") if candidate.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass

    written: list[str] = []
    for relative, data in sorted(outputs.items(), key=lambda item: item[0].as_posix()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(relative.as_posix())
    return written, removed


def materialize_native_dc_seam(
    repo_root: str | Path,
    *,
    resource_stack: Sequence[str | Path],
    aio_conquest_lua: str | Path | None = None,
    flag_source: str | Path | None = None,
    resolved_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write production native DC seam from #190 compiler authority + stack sources."""
    root = Path(repo_root)
    roots = normalize_stack(resource_stack)
    if not roots:
        raise GocArmyRegistryError("Native DC materialize requires an ordered resource stack")
    payload = (
        dict(resolved_payload)
        if resolved_payload is not None
        else FactionWiringCompiler(roots).compile()
    )
    if int(payload.get("error_count") or 0) != 0:
        raise GocArmyRegistryError(
            f"Resolved catalog has {payload.get('error_count')} error(s); refuse native DC materialize"
        )
    actors_by_side = _select_playable_actors(payload)
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
    _write(_ROSTER_RELATIVE, render_roster_conquest())
    _write(
        "resource/localizations/default/interface/text/dlg_mp_goc_phase2.pot",
        render_dlg_mp_keys(),
    )

    unit_counts: dict[str, int] = {}
    breed_counts: dict[str, int] = {}
    stale_breed_files_removed: dict[str, int] = {}
    for side, actor in sorted(actors_by_side.items()):
        projected_units, projected_body = project_actor_units(actor, roots, root)
        native_actor = normalize_actor_purchase_ids(actor, projected_units)
        if len(projected_units) != int(native_actor["unit_count"]):
            raise GocArmyRegistryError(
                f"Actor {native_actor['actor_id']} projected {len(projected_units)} "
                f"units, catalog unit_count={native_actor['unit_count']}"
            )

        breed_outputs = project_actor_breed_files(native_actor, roots)
        breed_written, breed_removed = _replace_actor_breed_namespace(
            root,
            side,
            breed_outputs,
        )
        written.extend(breed_written)

        inf_rows, inf_body = project_actor_inf_cost_rows(native_actor, roots)
        research_nodes = project_research_nodes(native_actor)
        _write(
            f"resource/set/multiplayer/units/conquest/units_{side}.set",
            render_units_set_from_projection(native_actor, projected_body),
        )
        _write(
            f"resource/set/multiplayer/units/conquest/inf_{side}.set",
            render_inf_set_from_projection(native_actor, inf_body),
        )
        _write(
            f"resource/set/dynamic_campaign/unit_research_{side}.set",
            render_research_file(native_actor, research_nodes),
        )
        _write(
            f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
            render_purchase_lua_from_actor(native_actor),
        )
        unit_counts[side] = len(projected_units)
        breed_counts[side] = len(breed_outputs)
        stale_breed_files_removed[side] = breed_removed
        _ = inf_rows

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

    obsolete = root / "resource/set/multiplayer/games/presets/alliances_goc_production_west.inc"
    removed = False
    if obsolete.is_file():
        obsolete.unlink()
        removed = True

    return {
        "written": sorted(set(written)),
        "playable_sides": list(playable_goc_sides()),
        "unit_counts": unit_counts,
        "breed_counts": breed_counts,
        "stale_breed_files_removed": stale_breed_files_removed,
        "flag_copies": flag_copies,
        "removed_obsolete_alliance_fragment": removed,
        "roster_path": _ROSTER_RELATIVE,
        "roster_committed": False,
    }


def validate_repo_native_dc_seam(repo_root: str | Path) -> list[str]:
    """Return problems if the committed seam is incomplete or authority-divergent."""
    root = Path(repo_root)
    problems: list[str] = []

    roster_path = root / _ROSTER_RELATIVE
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    if "/resource/set/multiplayer/units/roster_conquest.set" not in gitignore:
        problems.append("roster_conquest.set missing from .gitignore (must stay runtime-only)")
    if "/resource/set/breed/mp/goc_*/" not in gitignore:
        problems.append("runtime goc_* breed projections missing from .gitignore")
    if roster_path.is_file():
        roster_text = roster_path.read_text(encoding="utf-8", errors="ignore")
        expected = render_roster_conquest()
        if roster_text != expected:
            for rel in CANONICAL_INF_INCLUDES:
                if rel not in roster_text and "goc_active_actor_units" not in roster_text:
                    problems.append(f"on-disk roster missing canonical include {rel}")
            for rel in (
                "conquest/inf_sov_era1960.set",
                "conquest/inf_frg_era1960.set",
                "conquest/units_frg_era1960.set",
            ):
                if rel not in roster_text and "goc_active_actor_units" not in roster_text:
                    problems.append(f"on-disk roster missing core include {rel}")
        for side in dc_menu_goc_sides():
            if f"inf_{side}.set" not in roster_text and "goc_active_actor_units" not in roster_text:
                problems.append(f"native multi-faction roster missing {side}")

    for rel in committed_seam_relpaths():
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
            if "presets/alliances_generic.inc" not in text:
                problems.append("CTF does not include alliances_generic.inc")
        if rel.endswith("values.set"):
            for side in dc_menu_goc_sides():
                if side not in text:
                    problems.append(f"values.set missing matchups for {side}")
        if rel.endswith("conquest.lua"):
            # nationMap should include every playable Expanded-mode goc identity.
            for side in playable_goc_sides():
                if side not in text:
                    problems.append(f"conquest.lua missing {side}")
        if rel.endswith(".lua") and "/units/" in rel:
            if "Repeat" not in text or "Units" not in text:
                problems.append(f"purchase lua schema invalid: {rel}")
            if "usmc_rifleman" in text or "_test_rifle" in text:
                problems.append(f"purchase lua still uses bootstrap prototype content: {rel}")
            side = Path(rel).parent.name
            units_path = root / "resource/set/multiplayer/units/conquest" / f"units_{side}.set"
            if units_path.is_file():
                resolved_ids = set(
                    _RESOLVED_UNIT_RE.findall(
                        units_path.read_text(encoding="utf-8", errors="ignore")
                    )
                )
                lua_ids = set(_LUA_PURCHASE_RE.findall(text))
                if resolved_ids != lua_ids:
                    problems.append(
                        f"native purchase ID mismatch for {side}: "
                        f"missing_in_lua={sorted(resolved_ids - lua_ids)}; "
                        f"extra_in_lua={sorted(lua_ids - resolved_ids)}"
                    )
        if rel.endswith("units_goc_cze.set"):
            if "vz_77_dana" not in text:
                problems.append("goc_cze units pack missing #190 authority unit vz_77_dana")
            if "usmc_rifleman" in text or "m1126" in text:
                problems.append("goc_cze units pack still contains bootstrap USMC/Stryker content")
        if rel.endswith("units_goc_svk.set"):
            if "vz_77_dana" not in text:
                problems.append("goc_svk units pack missing #190 authority unit vz_77_dana")
        if "/units_goc_" in rel and rel.endswith(".set"):
            if "bootstrap" in text.lower() and "Disposable #201" in text:
                problems.append(f"production units pack still labeled disposable spike: {rel}")
            if GENERATED_MARKER not in text and "Deterministic rendering" not in text:
                if "usmc_rifleman" in text:
                    problems.append(f"units pack looks like bootstrap prototype: {rel}")

    obsolete = root / "resource/set/multiplayer/games/presets/alliances_goc_production_west.inc"
    if obsolete.is_file():
        problems.append("obsolete alliances_goc_production_west.inc still present")

    rendered = render_roster_conquest()
    for rel in CANONICAL_INF_INCLUDES:
        if rel not in rendered:
            problems.append(f"render_roster_conquest missing {rel}")
    for rel in BROAD_ROSTER_INCLUDES:
        if rel not in rendered:
            problems.append(f"render_roster_conquest missing {rel}")
    for required in (
        "conquest/inf_sov_era1960.set",
        "conquest/inf_frg_era1960.set",
        "conquest/units_frg_era1960.set",
    ):
        if required not in rendered:
            problems.append(f"render_roster_conquest missing required core {required}")

    return problems
