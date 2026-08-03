from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

from .models import Battalion, BattleParticipant, CampaignState, Faction, PendingBattle


@dataclass(frozen=True, slots=True)
class MoveResult:
    moved: bool
    pending_battle: PendingBattle | None = None


class CampaignEngine:
    TURN_ORDER = (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC)

    def __init__(self, state: CampaignState, *, random_seed: int | None = None) -> None:
        state.validate()
        self.state = state
        self._random = random.Random(random_seed)

    def move_or_attack(self, battalion_id: str, target_province_id: str) -> MoveResult:
        if self.state.pending_battle is not None:
            raise RuntimeError("Resolve the pending battle first")
        battalion = self._get_battalion(battalion_id)
        target = self._get_province(target_province_id)
        origin = self._get_province(battalion.province_id)
        if battalion.movement_remaining <= 0:
            raise ValueError(f"Battalion {battalion_id} has no movement remaining")
        if target_province_id not in origin.neighbors:
            raise ValueError(f"Province {target_province_id} is not adjacent")
        defender = self._battalion_in(target_province_id)
        if target.owner in (battalion.faction, Faction.NEUTRAL) and defender is None:
            battalion.province_id = target_province_id
            battalion.movement_remaining -= 1
            if target.owner == Faction.NEUTRAL:
                target.owner = battalion.faction
            return MoveResult(moved=True)
        if battalion.combat_actions_remaining <= 0:
            raise ValueError(f"Battalion {battalion_id} has no combat actions remaining")
        pending = self._build_pending_battle(battalion, defender, target_province_id)
        self.state.pending_battle = pending
        return MoveResult(moved=False, pending_battle=pending)

    def auto_resolve_pending_battle(self) -> Faction:
        pending = self._require_pending_battle()
        attacker = self._get_battalion(pending.attacking_participants[0].battalion_id)
        defender = self._get_battalion(pending.defending_participants[0].battalion_id) if pending.defending_participants else None
        target = self._get_province(pending.target_province_id)
        attacker_score = self._combat_score(attacker)
        defender_score = (self._combat_score(defender) if defender else 1.0) * (1 + min(target.fortification, 5) * 0.12)
        winner = attacker.faction if self._random.random() < attacker_score / max(attacker_score + defender_score, 1) else pending.defender_faction
        self.apply_battle_result(winner)
        return winner

    def apply_external_battle_result(self, winner: Faction, survivors: dict[str, list]) -> None:
        for battalion_id, roster in survivors.items():
            battalion = self.state.battalions.get(battalion_id)
            if battalion is not None:
                battalion.roster = roster
        self._finalize_positions(winner)

    def apply_battle_result(self, winner: Faction) -> None:
        pending = self._require_pending_battle()
        attacker = self._get_battalion(pending.attacking_participants[0].battalion_id)
        defender = self._get_battalion(pending.defending_participants[0].battalion_id) if pending.defending_participants else None
        if winner == pending.attacker_faction:
            if defender:
                self._apply_percentage_losses(defender, 0.65)
            self._apply_percentage_losses(attacker, 0.25)
        else:
            self._apply_percentage_losses(attacker, 0.55)
            if defender:
                self._apply_percentage_losses(defender, 0.20)
        self._finalize_positions(winner)

    def end_turn(self) -> Faction:
        if self.state.pending_battle is not None:
            raise RuntimeError("Cannot end turn with a pending battle")
        active = [f for f in self.TURN_ORDER if f.value in self.state.factions and not self.state.factions[f.value].is_eliminated]
        if not active:
            raise RuntimeError("No active factions")
        try:
            index = active.index(self.state.current_faction)
        except ValueError:
            index = -1
        next_faction = active[(index + 1) % len(active)]
        if index == len(active) - 1 or index == -1:
            self.state.turn_number += 1
            for faction in active:
                self.state.factions[faction.value].resources += sum(
                    p.resource_yield for p in self.state.provinces.values() if p.owner == faction
                )
            for battalion in self.state.battalions.values():
                battalion.movement_remaining = 1
                battalion.combat_actions_remaining = 1
                battalion.supply = min(100, battalion.supply + 20)
        self.state.current_faction = next_faction
        return next_faction

    def _finalize_positions(self, winner: Faction) -> None:
        pending = self._require_pending_battle()
        attacker = self._get_battalion(pending.attacking_participants[0].battalion_id)
        defender = self._get_battalion(pending.defending_participants[0].battalion_id) if pending.defending_participants else None
        target = self._get_province(pending.target_province_id)
        attacker.movement_remaining = 0
        attacker.combat_actions_remaining = max(0, attacker.combat_actions_remaining - 1)
        if winner == pending.attacker_faction:
            if defender:
                self._retreat_or_remove(defender, excluding=target.province_id)
            if not attacker.is_destroyed:
                attacker.province_id = target.province_id
                target.owner = attacker.faction
        else:
            if attacker.is_destroyed:
                self.state.battalions.pop(attacker.battalion_id, None)
            if defender and defender.is_destroyed:
                self.state.battalions.pop(defender.battalion_id, None)
        pending.completed = True
        self.state.pending_battle = None
        self.state.validate()

    def _retreat_or_remove(self, battalion: Battalion, *, excluding: str) -> None:
        if battalion.is_destroyed:
            self.state.battalions.pop(battalion.battalion_id, None)
            return
        current = self._get_province(battalion.province_id)
        candidates = [
            p for p in current.neighbors
            if p != excluding and self.state.provinces[p].owner == battalion.faction and self._battalion_in(p) is None
        ]
        if candidates:
            battalion.province_id = sorted(candidates)[0]
        else:
            self.state.battalions.pop(battalion.battalion_id, None)

    def _build_pending_battle(self, attacker: Battalion, defender: Battalion | None, target_id: str) -> PendingBattle:
        defender_faction = defender.faction if defender else self.state.provinces[target_id].owner
        return PendingBattle(
            battle_id=f"goc-{self.state.turn_number}-{uuid.uuid4().hex[:10]}",
            origin_province_id=attacker.province_id,
            target_province_id=target_id,
            attacker_faction=attacker.faction,
            defender_faction=defender_faction,
            attacking_participants=[BattleParticipant(attacker.battalion_id, attacker.faction, "stage_1", True)],
            defending_participants=[BattleParticipant(defender.battalion_id, defender.faction, "stage_2", True)] if defender else [],
            player_faction=self.state.selected_faction,
            player_is_attacker=attacker.faction == self.state.selected_faction,
        )

    @staticmethod
    def _combat_score(battalion: Battalion | None) -> float:
        if battalion is None:
            return 1.0
        weights = {"infantry": 1, "recon": 0.8, "vehicle": 1.7, "ifv": 2, "tank": 3, "artillery": 2.2, "air_defense": 1.8, "unknown": 1}
        base = sum(entry.quantity * weights.get(entry.category, 1) for entry in battalion.roster)
        return max(base * (0.4 + battalion.supply / 100 * 0.6) * (1 + min(battalion.experience, 1000) / 5000), 0.1)

    @staticmethod
    def _apply_percentage_losses(battalion: Battalion, fraction: float) -> None:
        for entry in battalion.roster:
            entry.quantity = max(0, entry.quantity - int(entry.quantity * fraction + 0.5))
        battalion.roster = [entry for entry in battalion.roster if entry.quantity > 0]

    def _get_battalion(self, battalion_id: str) -> Battalion:
        if battalion_id not in self.state.battalions:
            raise KeyError(f"Unknown battalion: {battalion_id}")
        return self.state.battalions[battalion_id]

    def _get_province(self, province_id: str):
        if province_id not in self.state.provinces:
            raise KeyError(f"Unknown province: {province_id}")
        return self.state.provinces[province_id]

    def _battalion_in(self, province_id: str) -> Battalion | None:
        return next((b for b in self.state.battalions.values() if b.province_id == province_id), None)

    def _require_pending_battle(self) -> PendingBattle:
        if self.state.pending_battle is None:
            raise RuntimeError("There is no pending battle")
        return self.state.pending_battle
