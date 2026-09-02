from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .campaign import CampaignEngine
from .diplomacy import are_allied, is_friendly_owner
from .economy import run_ai_economy
from .models import Battalion, CampaignState, Faction
from .strategic import run_ai_construction


@dataclass(frozen=True, slots=True)
class StrategicAction:
    battalion_id: str
    action: str
    origin_province_id: str = ""
    target_province_id: str = ""
    winner: Faction | None = None
    details: dict[str, Any] = field(default_factory=dict)


class StrategicAI:
    def __init__(self, state: CampaignState, *, random_seed: int = 0) -> None:
        self.state = state
        self.engine = CampaignEngine(state, random_seed=random_seed)

    def take_turn(self, faction: Faction) -> list[StrategicAction]:
        if faction.value not in self.state.factions:
            raise ValueError(f"Unknown strategic faction: {faction.value}")
        actions: list[StrategicAction] = []
        if self.state.unit_economy and self.state.research_nodes:
            for economy_action in run_ai_economy(self.state, faction):
                actions.append(
                    StrategicAction(
                        battalion_id=str(economy_action.get("formation_id", "")),
                        action=str(economy_action.get("action", "economy")),
                        target_province_id=str(
                            economy_action.get("unit_name", economy_action.get("key", ""))
                        ),
                        details=economy_action,
                    )
                )
        construction = run_ai_construction(self.state, faction)
        if construction:
            actions.append(
                StrategicAction(
                    battalion_id="",
                    action="construct",
                    origin_province_id=str(construction.get("province_id", "")),
                    target_province_id=str(construction.get("building", "")),
                    details=construction,
                )
            )
        battalion_ids = sorted(
            battalion.battalion_id
            for battalion in self.state.battalions.values()
            if battalion.faction == faction
        )
        for battalion_id in battalion_ids:
            battalion = self.state.battalions.get(battalion_id)
            if battalion is None or battalion.movement_remaining <= 0 or battalion.condition <= 20:
                continue
            origin = battalion.province_id
            target = self._choose_adjacent_target(battalion)
            if target is None:
                target = self._next_step_to_front(battalion)
            if target is None:
                actions.append(StrategicAction(battalion_id, "hold", origin))
                continue
            target_owner_before = self.state.provinces[target].owner
            result = self.engine.move_or_attack(battalion_id, target)
            if result.pending_battle is not None:
                winner = self.engine.auto_resolve_pending_battle()
                actions.append(StrategicAction(battalion_id, "attack", origin, target, winner))
            else:
                captured = target_owner_before == Faction.NEUTRAL or (
                    target_owner_before != battalion.faction
                    and not is_friendly_owner(self.state, battalion.faction, target_owner_before)
                )
                actions.append(
                    StrategicAction(battalion_id, "capture" if captured else "move", origin, target)
                )
        return actions

    def _choose_adjacent_target(self, battalion: Battalion) -> str | None:
        origin = self.state.provinces[battalion.province_id]
        candidates: list[tuple[int, int, str]] = []
        for neighbor_id in origin.neighbors:
            province = self.state.provinces[neighbor_id]
            occupant = self._battalion_in(neighbor_id)
            if occupant is not None and are_allied(self.state, battalion.faction, occupant.faction):
                continue
            if occupant is not None:
                candidates.append((0, occupant.unit_count, neighbor_id))
            elif province.owner == Faction.NEUTRAL:
                candidates.append((1, 0, neighbor_id))
            elif not is_friendly_owner(self.state, battalion.faction, province.owner):
                candidates.append((2, 0, neighbor_id))
        return min(candidates)[2] if candidates else None

    def _next_step_to_front(self, battalion: Battalion) -> str | None:
        start = battalion.province_id
        queue: deque[tuple[str, str | None]] = deque([(start, None)])
        visited = {start}
        while queue:
            province_id, first_step = queue.popleft()
            for neighbor_id in sorted(self.state.provinces[province_id].neighbors):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                occupant = self._battalion_in(neighbor_id)
                province = self.state.provinces[neighbor_id]
                step = neighbor_id if first_step is None else first_step
                allied_block = occupant is not None and are_allied(
                    self.state, battalion.faction, occupant.faction
                )
                hostile = occupant is not None and not allied_block
                capturable = occupant is None and (
                    province.owner == Faction.NEUTRAL
                    or not is_friendly_owner(self.state, battalion.faction, province.owner)
                )
                if hostile or capturable:
                    if self._is_legal_step(battalion, step):
                        return step
                    continue
                queue.append((neighbor_id, step))
        return None

    def _is_legal_step(self, battalion: Battalion, target_id: str) -> bool:
        origin = self.state.provinces.get(battalion.province_id)
        if origin is None or target_id not in origin.neighbors:
            return False
        occupant = self._battalion_in(target_id)
        if occupant is not None and are_allied(self.state, battalion.faction, occupant.faction):
            return False
        return True

    def _battalion_in(self, province_id: str) -> Battalion | None:
        return next(
            (value for value in self.state.battalions.values() if value.province_id == province_id),
            None,
        )
