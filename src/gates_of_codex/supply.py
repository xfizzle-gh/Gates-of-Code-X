from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace

from .diplomacy import allied_factions, is_friendly_owner
from .models import Battalion, CampaignState, Faction
from .operational_position import load_operational_graph_for_state
from .p2_integrity import earth3_p2_supply_disabled


DEFAULT_SUPPLY_SOURCES: dict[Faction, tuple[str, ...]] = {
    Faction.NATO: ("Sussex", "Wester Ems", "Warszawa"),
    Faction.UKRAINE: ("Lwow", "Zhytomyr"),
    Faction.RUSSIA: ("Minsk", "Leningrad"),
    Faction.PRC: ("province_0501",),
}

SUPPLY_RESTORE = 20
SUPPLY_DRAIN = 25
ATTRITION_START_TURN = 3


@dataclass(frozen=True, slots=True)
class SupplyReport:
    faction: Faction
    authority: str
    sources: tuple[str, ...]
    reachable_provinces: int | None
    legacy_admin_reachable_provinces: int
    supplied_battalions: tuple[str, ...]
    isolated_battalions: tuple[str, ...]
    destroyed_battalions: tuple[str, ...]
    connected_formations: tuple[str, ...]
    disconnected_formations: tuple[str, ...]
    grace_formations: tuple[str, ...]
    cut_off_formations: tuple[str, ...]
    connected_battalions: tuple[str, ...]
    grace_battalions: tuple[str, ...]
    cut_off_battalions: tuple[str, ...]


def mark_default_supply_sources(state: CampaignState) -> None:
    for faction, province_ids in DEFAULT_SUPPLY_SOURCES.items():
        for province_id in province_ids:
            province = state.provinces.get(province_id)
            if province is None:
                raise ValueError(f"Supply source for {faction.value} references missing province {province_id}")
            values = set(province.metadata.get("supply_source_for", []))
            values.add(faction.value)
            province.metadata["supply_source_for"] = sorted(values)
            static_values = set(province.metadata.get("static_supply_source_for", []))
            static_values.add(faction.value)
            province.metadata["static_supply_source_for"] = sorted(static_values)


def reachable_supply_provinces(state: CampaignState, faction: Faction) -> set[str]:
    if earth3_p2_supply_disabled(state):
        return set()
    friendly = allied_factions(state, faction)
    sources = _eligible_sources(state, faction)
    reachable: set[str] = set()
    queue: deque[str] = deque()
    for province_id in sources:
        province = state.provinces[province_id]
        if province.owner in friendly:
            reachable.add(province_id)
            queue.append(province_id)
    while queue:
        province_id = queue.popleft()
        for neighbor_id in sorted(state.provinces[province_id].neighbors):
            if neighbor_id in reachable:
                continue
            neighbor = state.provinces[neighbor_id]
            if neighbor.owner not in friendly:
                continue
            reachable.add(neighbor_id)
            queue.append(neighbor_id)
    return reachable


def refresh_supply_for_faction(state: CampaignState, faction: Faction) -> SupplyReport:
    if earth3_p2_supply_disabled(state):
        return supply_status_for_faction(state, faction)
    reachable = reachable_supply_provinces(state, faction)
    supplied: list[str] = []
    isolated: list[str] = []
    destroyed: list[str] = []

    for battalion in sorted(
        (value for value in state.battalions.values() if value.faction == faction),
        key=lambda value: value.battalion_id,
    ):
        operational_supplied = formation_supplied_for_battalion(
            state, battalion
        )
        is_supplied = (
            battalion.province_id in reachable
            if operational_supplied is None
            else operational_supplied
        )
        if is_supplied:
            from .site_upgrade import forward_depot_supply_restore_bonus

            restore = SUPPLY_RESTORE + forward_depot_supply_restore_bonus(
                state, battalion.province_id
            )
            battalion.supply = min(100, battalion.supply + restore)
            battalion.encircled_turns = 0
            supplied.append(battalion.battalion_id)
            continue

        battalion.supply = max(0, battalion.supply - SUPPLY_DRAIN)
        battalion.encircled_turns += 1
        isolated.append(battalion.battalion_id)
        if battalion.encircled_turns >= ATTRITION_START_TURN and battalion.supply <= 25:
            _apply_encirclement_attrition(battalion)
        if battalion.is_destroyed:
            destroyed.append(battalion.battalion_id)
        if battalion.supply == 0:
            battalion.movement_remaining = 0
            battalion.combat_actions_remaining = 0

    for battalion_id in destroyed:
        state.battalions.pop(battalion_id, None)

    report = replace(
        supply_status_for_faction(state, faction),
        supplied_battalions=tuple(supplied),
        isolated_battalions=tuple(isolated),
        destroyed_battalions=tuple(destroyed),
    )
    state.validate()
    return report


def supply_status_for_faction(
    state: CampaignState, faction: Faction
) -> SupplyReport:
    """Return one read-only status shape with explicit routing authority."""
    battalions = sorted(
        (
            value
            for value in state.battalions.values()
            if value.faction == faction
        ),
        key=lambda value: value.battalion_id,
    )
    if earth3_p2_supply_disabled(state):
        return SupplyReport(
            faction=faction,
            authority="none_until_p3",
            sources=(),
            reachable_provinces=None,
            legacy_admin_reachable_provinces=0,
            supplied_battalions=(),
            isolated_battalions=(),
            destroyed_battalions=(),
            connected_formations=(),
            disconnected_formations=(),
            grace_formations=(),
            cut_off_formations=(),
            connected_battalions=(),
            grace_battalions=(),
            cut_off_battalions=(),
        )
    reachable = reachable_supply_provinces(state, faction)
    if load_operational_graph_for_state(state) is None:
        supplied = tuple(
            item.battalion_id
            for item in battalions
            if item.province_id in reachable
        )
        isolated = tuple(
            item.battalion_id
            for item in battalions
            if item.province_id not in reachable
        )
        return SupplyReport(
            faction=faction,
            authority="province",
            sources=tuple(_eligible_sources(state, faction)),
            reachable_provinces=len(reachable),
            legacy_admin_reachable_provinces=len(reachable),
            supplied_battalions=supplied,
            isolated_battalions=isolated,
            destroyed_battalions=(),
            connected_formations=(),
            disconnected_formations=(),
            grace_formations=(),
            cut_off_formations=(),
            connected_battalions=(),
            grace_battalions=(),
            cut_off_battalions=(),
        )

    from .operational_supply import resolve_operational_supply_sources

    sources, _diagnostics = resolve_operational_supply_sources(state, faction)
    forces = sorted(
        (
            value
            for value in state.strategic_formations.values()
            if value.faction == faction
        ),
        key=lambda value: value.strategic_formation_id,
    )
    connected_forces = tuple(
        force.strategic_formation_id
        for force in forces
        if force.supplied
        and not force.cut_off
        and force.grace_ticks_remaining == 0
        and force.source_hub_id is not None
    )
    disconnected_forces = tuple(
        force.strategic_formation_id
        for force in forces
        if force.supplied
        and not force.cut_off
        and force.grace_ticks_remaining == 0
        and force.source_hub_id is None
    )
    grace_forces = tuple(
        force.strategic_formation_id
        for force in forces
        if force.supplied and force.grace_ticks_remaining == 1
    )
    cut_off_forces = tuple(
        force.strategic_formation_id for force in forces if force.cut_off
    )
    connected_force_set = set(connected_forces)
    grace_force_set = set(grace_forces)
    cut_off_force_set = set(cut_off_forces)
    connected_battalions: list[str] = []
    grace_battalions: list[str] = []
    cut_off_battalions: list[str] = []
    supplied_battalions: list[str] = []
    isolated_battalions: list[str] = []
    for battalion in battalions:
        force = _formation_for_battalion(state, battalion)
        force_id = None if force is None else force.strategic_formation_id
        if force is not None and force.supplied:
            supplied_battalions.append(battalion.battalion_id)
        else:
            isolated_battalions.append(battalion.battalion_id)
        if force_id in connected_force_set:
            connected_battalions.append(battalion.battalion_id)
        elif force_id in grace_force_set:
            grace_battalions.append(battalion.battalion_id)
        elif force_id in cut_off_force_set or force is None:
            cut_off_battalions.append(battalion.battalion_id)

    return SupplyReport(
        faction=faction,
        authority="operational_graph",
        sources=tuple(item.source_hub_id for item in sources),
        reachable_provinces=None,
        legacy_admin_reachable_provinces=len(reachable),
        supplied_battalions=tuple(supplied_battalions),
        isolated_battalions=tuple(isolated_battalions),
        destroyed_battalions=(),
        connected_formations=connected_forces,
        disconnected_formations=disconnected_forces,
        grace_formations=grace_forces,
        cut_off_formations=cut_off_forces,
        connected_battalions=tuple(connected_battalions),
        grace_battalions=tuple(grace_battalions),
        cut_off_battalions=tuple(cut_off_battalions),
    )


def refresh_all_supply(state: CampaignState) -> list[SupplyReport]:
    return [
        refresh_supply_for_faction(state, faction)
        for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC)
        if faction.value in state.factions and not state.factions[faction.value].is_eliminated
    ]


def formation_supplied_for_battalion(
    state: CampaignState, battalion: Battalion
) -> bool | None:
    """Return S8 formation authority, or None for legacy no-graph campaigns."""
    if earth3_p2_supply_disabled(state):
        return None
    if load_operational_graph_for_state(state) is None:
        return None
    force = _formation_for_battalion(state, battalion)
    return False if force is None else force.supplied


def _formation_for_battalion(state: CampaignState, battalion: Battalion):
    force = state.strategic_formations.get(battalion.strategic_formation_id)
    if force is not None:
        return force
    return next(
        (
            item
            for item in sorted(
                state.strategic_formations.values(),
                key=lambda value: value.strategic_formation_id,
            )
            if battalion.battalion_id in item.battalion_ids
        ),
        None,
    )


def _eligible_sources(state: CampaignState, faction: Faction) -> list[str]:
    friendly = {value.value for value in allied_factions(state, faction)}
    sources = {
        province.province_id
        for province in state.provinces.values()
        if friendly.intersection(
            set(province.metadata.get("supply_source_for", []))
            | set(province.metadata.get("static_supply_source_for", []))
        )
        and is_friendly_owner(state, faction, province.owner)
    }
    for allied in allied_factions(state, faction):
        for province_id in DEFAULT_SUPPLY_SOURCES.get(allied, ()):
            province = state.provinces.get(province_id)
            if province is not None and is_friendly_owner(state, faction, province.owner):
                sources.add(province_id)
    return sorted(sources)


def _apply_encirclement_attrition(battalion: Battalion) -> None:
    if not battalion.roster:
        return
    largest = max(battalion.roster, key=lambda value: (value.quantity, value.unit_name))
    largest.quantity = max(0, largest.quantity - 1)
    battalion.roster = [value for value in battalion.roster if value.quantity > 0]


CONNECTED_SUPPLY_STATE = "connected"
INITIAL_DISCONNECTED_SUPPLY_STATE = "initial_disconnected"
GRACE_SUPPLY_STATE = "grace"
CUT_OFF_SUPPLY_STATE = "cut_off"
OPERATIONAL_SUPPLY_STATES = frozenset(
    {
        CONNECTED_SUPPLY_STATE,
        INITIAL_DISCONNECTED_SUPPLY_STATE,
        GRACE_SUPPLY_STATE,
        CUT_OFF_SUPPLY_STATE,
    }
)

#: Existing rollover / repair rules. Presentation quotes these; it does not invent a new table.
SUPPLY_RESTORE_EFFECT = (
    f"Supplied formations restore {SUPPLY_RESTORE} readiness at rollover; "
    "repair requires battalion supply of at least 50 and no encirclement."
)
CUT_OFF_SUPPLY_EFFECT = (
    f"Cut-off drains {SUPPLY_DRAIN} readiness, increments encirclement, "
    "and blocks repair."
)
GRACE_SUPPLY_EFFECT = (
    "One-tick grace: still supplied this tick. The next disconnected "
    "consuming tick becomes cut-off."
)
INITIAL_DISCONNECTED_SUPPLY_EFFECT = (
    "No route yet; still supplied. The next disconnected consuming tick "
    "enters one-tick grace."
)
PROVINCE_SUPPLIED_EFFECT = (
    f"Province-reach supplied formations restore {SUPPLY_RESTORE} readiness "
    "at rollover; repair requires battalion supply of at least 50 and no encirclement."
)
PROVINCE_ISOLATED_EFFECT = (
    f"Isolated formations drain {SUPPLY_DRAIN} readiness, increment encirclement, "
    "and block repair."
)
P2_SUPPLY_UNAVAILABLE_EFFECT = "Operational supply is unavailable until P3."


def formation_supply_state(force) -> str:
    """Return the exact S8 serialized shape for one strategic formation."""

    if force.cut_off and not force.supplied and force.source_hub_id is None:
        if force.grace_ticks_remaining == 0:
            return CUT_OFF_SUPPLY_STATE
    if (
        force.supplied
        and not force.cut_off
        and force.source_hub_id is None
        and force.grace_ticks_remaining == 1
    ):
        return GRACE_SUPPLY_STATE
    if (
        force.supplied
        and not force.cut_off
        and force.source_hub_id is not None
        and force.grace_ticks_remaining == 0
    ):
        return CONNECTED_SUPPLY_STATE
    if (
        force.supplied
        and not force.cut_off
        and force.source_hub_id is None
        and force.grace_ticks_remaining == 0
    ):
        return INITIAL_DISCONNECTED_SUPPLY_STATE
    raise ValueError("invalid_operational_supply_state")


QUERY_SUPPLY_NOT_OWNED = "query_supply_not_owned"


def _acting_player_faction(state: CampaignState) -> Faction:
    """Player-issued exact supply queries bind to the selected player faction."""

    return state.selected_faction


def _player_owns_formation(state: CampaignState, force) -> bool:
    return force.faction == _acting_player_faction(state)


def query_supply_status(
    state: CampaignState,
    *,
    strategic_formation_id: str | None = None,
    province_id: str | None = None,
) -> dict:
    """Return bounded, read-only S8 supply/readiness for one owned formation.

    Player-issued queries are ownership fail-closed: exact supply, hub, grace,
    repair eligibility, encirclement, and readiness are returned only for a
    formation owned by ``state.selected_faction``. Province targets never
    enumerate enemy rows. The same ownership gate applies with Fog On or Off;
    this command does not invent a second S11 visibility model.
    """

    formation_id = str(strategic_formation_id or "").strip()
    province = str(province_id or "").strip()
    if not formation_id and not province:
        raise ValueError("query_supply requires strategic_formation_id or province_id")
    if province and province not in state.provinces:
        raise ValueError(f"unknown_province {province}")
    acting = _acting_player_faction(state)
    if formation_id:
        force = state.strategic_formations.get(formation_id)
        if force is None:
            raise ValueError(f"unknown_strategic_formation {formation_id}")
        if not _player_owns_formation(state, force):
            raise ValueError(f"{QUERY_SUPPLY_NOT_OWNED} {formation_id}")
        if province and force.province_id != province:
            raise ValueError(
                f"formation_not_in_province {formation_id} {province}"
            )
        forces = [force]
        province = force.province_id
    else:
        forces = [
            force
            for force in sorted(
                state.strategic_formations.values(),
                key=lambda value: value.strategic_formation_id,
            )
            if force.province_id == province and force.faction == acting
        ]

    authority = "none_until_p3"
    if not earth3_p2_supply_disabled(state):
        authority = (
            "operational_graph"
            if load_operational_graph_for_state(state) is not None
            else "province"
        )
    return {
        "authority": authority,
        "province_id": province,
        "formations": [
            _query_supply_formation_row(state, force, authority=authority)
            for force in forces
        ],
    }


def _query_supply_formation_row(
    state: CampaignState, force, *, authority: str
) -> dict:
    members = [
        state.battalions[battalion_id]
        for battalion_id in force.battalion_ids
        if battalion_id in state.battalions
    ]
    encircled_turns = max((item.encircled_turns for item in members), default=0)
    can_repair = bool(members) and all(
        item.supply >= 50 and item.encircled_turns == 0 for item in members
    )
    if authority == "none_until_p3":
        supply_state = formation_supply_state(force)
        effect = P2_SUPPLY_UNAVAILABLE_EFFECT
        supplied = force.supplied
        cut_off = force.cut_off
        source_hub_id = force.source_hub_id
        grace_ticks_remaining = force.grace_ticks_remaining
    elif authority == "province":
        reachable = reachable_supply_provinces(state, force.faction)
        in_supply = force.province_id in reachable
        supply_state = (
            CONNECTED_SUPPLY_STATE if in_supply else CUT_OFF_SUPPLY_STATE
        )
        effect = PROVINCE_SUPPLIED_EFFECT if in_supply else PROVINCE_ISOLATED_EFFECT
        supplied = in_supply
        cut_off = not in_supply
        source_hub_id = None
        grace_ticks_remaining = 0
    else:
        supply_state = formation_supply_state(force)
        effect = {
            CONNECTED_SUPPLY_STATE: SUPPLY_RESTORE_EFFECT,
            GRACE_SUPPLY_STATE: GRACE_SUPPLY_EFFECT,
            INITIAL_DISCONNECTED_SUPPLY_STATE: INITIAL_DISCONNECTED_SUPPLY_EFFECT,
            CUT_OFF_SUPPLY_STATE: CUT_OFF_SUPPLY_EFFECT,
        }[supply_state]
        supplied = force.supplied
        cut_off = force.cut_off
        source_hub_id = force.source_hub_id
        grace_ticks_remaining = force.grace_ticks_remaining
    return {
        "strategic_formation_id": force.strategic_formation_id,
        "province_id": force.province_id,
        "supply_state": supply_state,
        "supplied": supplied,
        "cut_off": cut_off,
        "source_hub_id": source_hub_id,
        "grace_ticks_remaining": grace_ticks_remaining,
        "readiness": {
            "supply": int(force.supply_summary),
            "can_repair": can_repair,
            "encircled_turns": int(encircled_turns),
        },
        "effect": effect,
    }
