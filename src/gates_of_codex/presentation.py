from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .codex.catalog import CodeXCatalog, UnitDefinition
from .models import Battalion, BattalionRosterEntry, CampaignState


SOURCE_UNKNOWN = {
    "label": "Unknown source",
    "marker": "?",
    "role": "unknown",
    "priority": -1,
    "path": "",
}

CATEGORY_ICONS = {
    "infantry": "INF",
    "recon": "REC",
    "engineer": "ENG",
    "engineering": "ENG",
    "tank": "ARM",
    "armor": "ARM",
    "ifv": "IFV",
    "apc": "APC",
    "vehicle": "VEH",
    "artillery": "ART",
    "air_defense": "AD",
    "anti_armor": "AT",
    "logistics": "LOG",
    "logistics_transport": "LOG",
    "support": "SUP",
    "unknown": "UNIT",
}


def register_catalog_presentations(state: CampaignState, catalog: CodeXCatalog) -> None:
    presentations = state.map_metadata.setdefault("unit_presentations", {})
    units = catalog.units.raw_values() if hasattr(catalog.units, "raw_values") else catalog.units.values()
    for unit in units:
        presentations[unit.name] = unit_presentation_from_catalog(unit)


def unit_presentation_from_catalog(unit: UnitDefinition) -> dict[str, Any]:
    source = _source_presentation(unit.source_files)
    return {
        "display_name": readable_unit_name(unit.name),
        "portrait_key": portrait_key(unit.name),
        "category_icon": category_icon(unit.category),
        "source": source,
        "catalog_category": unit.category,
        "tactical_side": unit.side,
        "period": unit.period,
    }


def build_stack_presentations(
    state: CampaignState,
    front_options: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    legal_by_battalion: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for option in front_options:
        battalion_id = str(option.get("battalion_id", ""))
        if battalion_id:
            legal_by_battalion[battalion_id].append(dict(option))

    battalions: dict[str, dict[str, Any]] = {}
    stacks: dict[str, list[str]] = defaultdict(list)
    for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id):
        presentation = build_battalion_presentation(
            state,
            battalion,
            legal_options=legal_by_battalion.get(battalion.battalion_id, []),
        )
        battalions[battalion.battalion_id] = presentation
        stacks[battalion.province_id].append(battalion.battalion_id)

    # Strategic-formation presentations (on-map containers). Tabs use these, not
    # template formation IDs or raw battalion IDs.
    from .operational_position import position_to_dict, resolve_display_pixel

    force_presentations: dict[str, dict[str, Any]] = {}
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        member_ids = [
            battalion_id
            for battalion_id in force.battalion_ids
            if battalion_id in battalions
        ]
        if not member_ids:
            continue
        member_rows = [battalions[battalion_id] for battalion_id in member_ids]
        total_units = sum(int(row["unit_count"]) for row in member_rows)
        force_presentations[force.strategic_formation_id] = {
            "id": force.strategic_formation_id,
            "display_name": force.display_name,
            "echelon": force.echelon.value if hasattr(force.echelon, "value") else str(force.echelon),
            "commander_id": force.commander_id,
            "commander_label": _commander_label(state, force.commander_id),
            "faction": force.faction.value,
            "province_id": force.province_id,
            "position": position_to_dict(force.position),
            "display_pixel": resolve_display_pixel(state, force),
            "actor_marker": force.actor_id or (
                member_rows[0]["actor_marker"] if member_rows else force.faction.value.upper()
            ),
            "battalion_ids": list(member_ids),
            "battalion_count": len(member_ids),
            "unit_count": int(total_units),
            "can_act": any(bool(row["can_act"]) for row in member_rows),
            "template_formation_id": force.template_formation_id,
        }

    # Disambiguate colliding strategic-formation display names in a province.
    names_by_province: dict[str, list[str]] = defaultdict(list)
    for force_id, row in force_presentations.items():
        names_by_province[str(row["province_id"])].append(str(row["display_name"]))
    for force_id, row in force_presentations.items():
        name = str(row["display_name"])
        province_id = str(row["province_id"])
        if names_by_province[province_id].count(name) > 1:
            # Compact disambiguator; keep authored name primary.
            suffix = force_id.replace("sf-", "")[-4:]
            row["tab_label"] = f"{name} ({suffix})"
        else:
            row["tab_label"] = name

    stack_presentations: dict[str, dict[str, Any]] = {}
    for province_id, battalion_ids in sorted(stacks.items()):
        rows = [battalions[battalion_id] for battalion_id in battalion_ids]
        total_units = sum(int(row["unit_count"]) for row in rows)
        total_authorized = sum(int(row["authorized_unit_count"]) for row in rows)
        weight = max(total_units, 1)
        weighted_condition = sum(
            int(row["condition"]) * max(int(row["unit_count"]), 1) for row in rows
        )
        weighted_supply = sum(
            int(row["supply"]) * max(int(row["unit_count"]), 1) for row in rows
        )
        strategic_formation_ids = sorted(
            {
                force_id
                for force_id, force_row in force_presentations.items()
                if str(force_row.get("province_id")) == province_id
            }
        )
        # Compatibility: template formation ids still listed for older clients.
        template_formation_ids = sorted(
            {
                str(row.get("formation_id", ""))
                for row in rows
                if str(row.get("formation_id", ""))
            }
        )
        stack_presentations[province_id] = {
            "province_id": province_id,
            "battalion_ids": list(battalion_ids),
            "battalion_count": int(len(battalion_ids)),
            "formation_count": int(len(strategic_formation_ids)),
            "formation_ids": template_formation_ids,
            "strategic_formation_ids": strategic_formation_ids,
            "unit_count": int(total_units),
            "authorized_unit_count": int(total_authorized),
            "replacement_deficit": int(max(0, total_authorized - total_units)),
            "condition": int(round(weighted_condition / weight)),
            "supply": int(round(weighted_supply / weight)),
            "reinforcement_cost": int(sum(int(row["reinforcement_cost"]) for row in rows)),
            "repair_cost": int(sum(int(row["repair_cost"]) for row in rows)),
            "can_act": any(bool(row["can_act"]) for row in rows),
            "actor_markers": sorted(
                {
                    str(row["actor_marker"])
                    for row in rows
                    if str(row["actor_marker"])
                }
            ),
            "summary_label": _stack_summary_label(
                formation_count=len(strategic_formation_ids),
                battalion_count=len(battalion_ids),
                unit_count=total_units,
                authorized_unit_count=total_authorized,
            ),
        }
    return {
        "battalions": battalions,
        "stacks": stack_presentations,
        "strategic_formations": force_presentations,
    }


def build_battalion_presentation(
    state: CampaignState,
    battalion: Battalion,
    *,
    legal_options: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    formation = state.formations.get(battalion.formation_id)
    formation_name = formation.display_name if formation is not None else battalion.formation_id
    actor_marker = formation.nation if formation is not None else battalion.faction.value.upper()
    legal_rows = sorted(
        (dict(option) for option in legal_options),
        key=lambda value: (str(value.get("target", "")), str(value.get("kind", ""))),
    )
    show_placeholders = bool(state.map_metadata.get("debug_show_placeholder_units", False))
    cards = [
        card
        for card in _unit_cards(state, battalion)
        if show_placeholders or not is_placeholder_unit_name(str(card.get("unit_name", "")))
    ]
    if not cards and not show_placeholders:
        # Explicit empty tactical content — UI shows diagnostic only in debug mode.
        cards = []
    reinforcement_cost = sum(int(card["replacement_cost"]) for card in cards)
    repair_cost = sum(int(card["repair_cost"]) for card in cards)
    battalion_label = readable_battalion_name(battalion.battalion_id)
    # Prefer real formation display names over synthetic formation-01 IDs.
    primary_name = formation_name if formation is not None else battalion_label
    return {
        "id": battalion.battalion_id,
        "display_name": primary_name,
        "battalion_label": battalion_label,
        "formation_id": battalion.formation_id,
        "formation_name": formation_name,
        "actor_marker": actor_marker,
        "faction": battalion.faction.value,
        "province_id": battalion.province_id,
        "type": battalion.battalion_type.value,
        "type_label": readable_unit_name(battalion.battalion_type.value),
        "unit_count": battalion.unit_count,
        "authorized_unit_count": battalion.authorized_unit_count,
        "replacement_deficit": battalion.replacement_deficit,
        "condition": battalion.condition,
        "supply": battalion.supply,
        "experience": battalion.experience,
        "movement_remaining": battalion.movement_remaining,
        "combat_actions_remaining": battalion.combat_actions_remaining,
        "encircled_turns": battalion.encircled_turns,
        "is_player_controlled": battalion.is_player_controlled,
        "can_act": bool(legal_rows),
        "legal_option_count": len(legal_rows),
        "legal_options": legal_rows,
        "reinforcement_cost": reinforcement_cost,
        "repair_cost": repair_cost,
        "cards": cards,
    }


def readable_unit_name(unit_name: str) -> str:
    value = re.sub(r"\((?:nato|ukr|rusa|prc)\)$", "", unit_name.strip(), flags=re.I)
    value = re.sub(r"[_/]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return "Unknown Unit"
    return " ".join(_title_token(token) for token in value.split())


def readable_battalion_name(battalion_id: str) -> str:
    value = re.sub(r"^(?:battalion|bn|formation)[-_]", "", battalion_id, flags=re.I)
    return readable_unit_name(value)


def _stack_summary_label(
    *,
    formation_count: int,
    battalion_count: int,
    unit_count: int,
    authorized_unit_count: int,
) -> str:
    parts = [
        _count_label(int(formation_count), "formation", "formations"),
        _count_label(int(battalion_count), "battalion", "battalions"),
    ]
    if authorized_unit_count > 0:
        parts.append(
            f"{int(unit_count)}/{int(authorized_unit_count)} "
            f"{'tactical unit' if unit_count == 1 else 'tactical units'}"
        )
    else:
        parts.append(_count_label(int(unit_count), "tactical unit", "tactical units"))
    return " | ".join(parts)


def _count_label(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _commander_label(state: CampaignState, commander_id: str | None) -> str:
    if not commander_id:
        return "Unassigned Commander"
    commander = state.commanders.get(commander_id)
    if commander is None:
        return "Unassigned Commander"
    name = str(getattr(commander, "display_name", "") or "").strip()
    return name or "Unassigned Commander"


def is_placeholder_unit_name(unit_name: str) -> bool:
    return "placeholder" in unit_name.strip().lower()


def portrait_key(unit_name: str) -> str:
    value = re.sub(r"\((?:nato|ukr|rusa|prc)\)$", "", unit_name.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown_unit"


def category_icon(category: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")
    return CATEGORY_ICONS.get(normalized, normalized[:4].upper() or "UNIT")


def _unit_cards(state: CampaignState, battalion: Battalion) -> list[dict[str, Any]]:
    current = _group_roster(battalion.roster)
    authorized = _group_roster(battalion.authorized_roster)
    keys = sorted(set(current) | set(authorized), key=lambda value: (value[1], value[0], value[2]))
    stored_presentations = state.map_metadata.get("unit_presentations", {})
    cards: list[dict[str, Any]] = []
    for unit_name, stage, category in keys:
        quantity = current.get((unit_name, stage, category), 0)
        authorized_quantity = authorized.get((unit_name, stage, category), 0)
        deficit = max(0, authorized_quantity - quantity)
        presentation = dict(stored_presentations.get(unit_name, {}))
        source = dict(presentation.get("source", SOURCE_UNKNOWN))
        economy = state.unit_economy.get(unit_name)
        purchase_cost = economy.purchase_cost if economy is not None else 0
        repair_rate = economy.repair_cost_per_point if economy is not None else 0
        display_name = str(presentation.get("display_name") or readable_unit_name(unit_name))
        icon = str(presentation.get("category_icon") or category_icon(category))
        card = {
            "unit_name": unit_name,
            "display_name": display_name,
            "short_name": _ellipsize(display_name, 30),
            "portrait_key": str(presentation.get("portrait_key") or portrait_key(unit_name)),
            "portrait_fallback": icon,
            "category": category,
            "category_icon": icon,
            "stage": stage,
            "quantity": quantity,
            "authorized_quantity": authorized_quantity,
            "replacement_deficit": deficit,
            "condition": battalion.condition,
            "condition_source": "battalion_inherited",
            "supply": battalion.supply,
            "supply_source": "battalion_inherited",
            "experience": battalion.experience,
            "experience_source": "battalion_inherited",
            "source": source,
            "replacement_cost": deficit * purchase_cost,
            "repair_cost": quantity * max(0, 100 - battalion.condition) * repair_rate,
        }
        card["tooltip"] = _card_tooltip(card)
        cards.append(card)
    return cards


def _group_roster(entries: Iterable[BattalionRosterEntry]) -> dict[tuple[str, str, str], int]:
    values: dict[tuple[str, str, str], int] = defaultdict(int)
    for entry in entries:
        values[(entry.unit_name, entry.stage, entry.category)] += entry.quantity
    return dict(values)


def _source_presentation(source_files: Iterable[str]) -> dict[str, Any]:
    parsed: list[tuple[int, str, str]] = []
    for source in source_files:
        match = re.match(r"^(\d+):([^/]+)/(.*)$", source)
        if match:
            parsed.append((int(match.group(1)), match.group(2), match.group(3)))
    if not parsed:
        return dict(SOURCE_UNKNOWN)
    priority, root_name, path = max(parsed, key=lambda value: (value[0], value[2]))
    normalized = root_name.lower().replace(" ", "")
    if "west81" in normalized:
        label, marker, role = "West81", "W81", "legacy_reserve"
    elif "codex" in normalized or "code:x" in root_name.lower():
        label, marker, role = "Code:X", "C:X", "modern"
    elif "gates" in normalized:
        label, marker, role = "Gates overlay", "OVR", "overlay"
    else:
        label, marker, role = root_name, _ellipsize(root_name.upper(), 4), "unknown"
    return {
        "label": label,
        "marker": marker,
        "role": role,
        "priority": priority,
        "path": Path(path).as_posix(),
    }


def _card_tooltip(card: dict[str, Any]) -> str:
    source = card["source"]
    return (
        f"{card['display_name']}\n"
        f"{card['quantity']}/{card['authorized_quantity']} fielded · "
        f"{card['condition']}% condition · {card['supply']}% supply · "
        f"XP {card['experience']}\n"
        f"Source: {source.get('label', 'Unknown source')} "
        f"({source.get('role', 'unknown')})"
    )


def _ellipsize(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(1, limit - 1)].rstrip() + "…"


def _title_token(token: str) -> str:
    if any(character.isdigit() for character in token) or token.isupper():
        return token.upper()
    return token.capitalize()
