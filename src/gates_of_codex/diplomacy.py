from __future__ import annotations

from .models import CampaignState, Faction


def allied_factions(state: CampaignState, faction: Faction) -> set[Faction]:
    members = {faction}
    for alliance in state.alliances.values():
        if faction in alliance.factions:
            members.update(alliance.factions)
    return members


def are_allied(state: CampaignState, left: Faction, right: Faction) -> bool:
    if left == right:
        return True
    if Faction.NEUTRAL in (left, right):
        return False
    return right in allied_factions(state, left)


def is_friendly_owner(state: CampaignState, faction: Faction, owner: Faction) -> bool:
    return owner != Faction.NEUTRAL and are_allied(state, faction, owner)
