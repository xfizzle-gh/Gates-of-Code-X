from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

from .diplomacy import are_allied, is_friendly_owner
from .models import Battalion, BattleParticipant, CampaignState, CommanderStatus, Faction, PendingBattle


@dataclass(frozen=True, slots=True)
class MoveResult:
    moved: bool
    pending_battle: PendingBattle | None = None


class CampaignEngine:
    TURN_ORDER = (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC)

    def __init__(self, state: CampaignState, *, random_seed: int | None = None) -> None:
        from .strategic import ensure_strategic_layer

        ensure_strategic_layer(state)
        state.validate()
        self.state = state
        self._random = random.Random(random_seed)

    def move_or_attack(self, battalion_id: str, target_province_id: str) -> MoveResult:
        if self.state.pending_battle is not None:
            raise RuntimeError("Resolve the pending battle first")
        battalion = self._get_battalion(battalion_id)
        self._reject_if_operational_order_locked(battalion)
        target = self._get_province(target_province_id)
        origin = self._get_province(battalion.province_id)
        if battalion.movement_remaining <= 0:
            raise ValueError(f"Battalion {battalion_id} has no movement remaining")
        if battalion.condition <= 20:
            raise ValueError(f"Battalion {battalion_id} is too damaged to move")
        if target_province_id not in origin.neighbors:
            raise ValueError(f"Province {target_province_id} is not adjacent")

        defender = self._battalion_in(target_province_id)
        if defender is not None and are_allied(self.state, battalion.faction, defender.faction):
            raise ValueError(f"Allied province {target_province_id} already contains battalion {defender.battalion_id}")

        friendly_or_neutral = target.owner == Faction.NEUTRAL or is_friendly_owner(
            self.state, battalion.faction, target.owner
        )
        if defender is None and friendly_or_neutral:
            battalion.province_id = target_province_id
            battalion.movement_remaining -= 1
            self._sync_strategic_formation_location(battalion)
            # Operational maneuver: ownership only via control-site capture (S5), not entry.
            if target.owner == Faction.NEUTRAL and not bool(
                self.state.map_metadata.get("operational_maneuver_enabled")
            ):
                target.owner = battalion.faction
                from .strategic import evaluate_campaign_outcome, sync_province_infrastructure_owner

                sync_province_infrastructure_owner(target)
                evaluate_campaign_outcome(self.state)
            return MoveResult(moved=True)

        if battalion.combat_actions_remaining <= 0:
            raise ValueError(f"Battalion {battalion_id} has no combat actions remaining")
        pending = self._build_pending_battle(battalion, defender, target_province_id)
        self.state.pending_battle = pending
        return MoveResult(moved=False, pending_battle=pending)

    def auto_resolve_pending_battle(self) -> Faction:
        pending = self._require_pending_battle()
        attackers = self._participants_battalions(pending.attacking_participants)
        defenders = self._participants_battalions(pending.defending_participants)
        target = self._get_province(pending.target_province_id)
        attacker_score = sum(self._combat_score(item) for item in attackers) or 0.1
        defender_score = (
            sum(self._combat_score(item) for item in defenders) or 1.0
        ) * (1 + min(target.fortification, 5) * 0.12)
        winner = (
            pending.attacker_faction
            if self._random.random() < attacker_score / max(attacker_score + defender_score, 1)
            else pending.defender_faction
        )
        self.apply_battle_result(winner)
        return winner

    def apply_external_battle_result(self, winner: Faction, survivors: dict[str, list]) -> None:
        for battalion_id, roster in survivors.items():
            battalion = self.state.battalions.get(battalion_id)
            if battalion is not None:
                previous = max(1, battalion.unit_count)
                battalion.roster = roster
                casualty_ratio = max(0.0, 1.0 - battalion.unit_count / previous)
                battalion.condition = max(10, battalion.condition - max(5, int(casualty_ratio * 35)))
        self._finalize_positions(winner)

    def apply_battle_result(self, winner: Faction) -> None:
        pending = self._require_pending_battle()
        attackers = self._participants_battalions(pending.attacking_participants)
        defenders = self._participants_battalions(pending.defending_participants)
        if winner == pending.attacker_faction:
            for defender in defenders:
                self._apply_percentage_losses(defender, 0.65)
                defender.condition = max(10, defender.condition - 28)
            for attacker in attackers:
                self._apply_percentage_losses(attacker, 0.25)
                attacker.condition = max(10, attacker.condition - 12)
        else:
            for attacker in attackers:
                self._apply_percentage_losses(attacker, 0.55)
                attacker.condition = max(10, attacker.condition - 24)
            for defender in defenders:
                self._apply_percentage_losses(defender, 0.20)
                defender.condition = max(10, defender.condition - 10)
        self._finalize_positions(winner)

    def end_turn(self) -> Faction:
        if self.state.pending_battle is not None:
            raise RuntimeError("Cannot end turn with a pending battle")
        outcome = self.state.map_metadata.get("campaign_outcome", {})
        if outcome.get("status") == "complete":
            raise RuntimeError("Campaign is already complete")
        active = [f for f in self.TURN_ORDER if f.value in self.state.factions and not self.state.factions[f.value].is_eliminated]
        if not active:
            raise RuntimeError("No active factions")
        try:
            index = active.index(self.state.current_faction)
        except ValueError:
            index = -1
        next_faction = active[(index + 1) % len(active)]
        if index == len(active) - 1 or index == -1:
            from .economy import settle_round_economy
            from .operational_movement import resolve_strategic_turn_movement
            from .strategic import evaluate_campaign_outcome
            from .supply import refresh_all_supply

            # S3: resolve on the ending turn number so committed_turn matches
            # (manual commit during turn N activates when turn N ends).
            resolve_strategic_turn_movement(self.state)
            self.state.turn_number += 1
            settle_round_economy(self.state)
            for battalion in self.state.battalions.values():
                battalion.movement_remaining = 1
                battalion.combat_actions_remaining = 1
            refresh_all_supply(self.state)
            evaluate_campaign_outcome(self.state, advance_hold=True)
        self.state.current_faction = next_faction
        return next_faction

    def _finalize_positions(self, winner: Faction) -> None:
        """Apply post-battle placement once per strategic formation (not per battalion)."""
        pending = self._require_pending_battle()
        attackers = self._participants_battalions(pending.attacking_participants)
        defenders = self._participants_battalions(pending.defending_participants)
        target = self._get_province(pending.target_province_id)
        for attacker in attackers:
            attacker.movement_remaining = 0
            attacker.combat_actions_remaining = max(0, attacker.combat_actions_remaining - 1)

        # Destroy empty battalions first (per-battalion casualties already applied).
        for battalion in list(attackers) + list(defenders):
            if battalion.battalion_id in self.state.battalions and battalion.is_destroyed:
                self._remove_battalion(battalion.battalion_id)

        attackers = [bn for bn in attackers if bn.battalion_id in self.state.battalions]
        defenders = [bn for bn in defenders if bn.battalion_id in self.state.battalions]
        atk_forces = self._formations_for_battalions(attackers)
        def_forces = self._formations_for_battalions(defenders)
        is_op_contact = bool(str(getattr(pending, "encounter_kind", "") or ""))

        if winner == pending.attacker_faction:
            for force_id in def_forces:
                self._resolve_formation_after_battle(
                    force_id,
                    lost=True,
                    exclude_province=target.province_id,
                    preferred_retreat=None,
                )
            for force_id in atk_forces:
                self._resolve_formation_after_battle(
                    force_id,
                    lost=False,
                    hold_province=target.province_id,
                )
            if any(self.state.strategic_formations.get(fid) for fid in atk_forces):
                target.owner = pending.attacker_faction
                from .strategic import sync_province_infrastructure_owner

                sync_province_infrastructure_owner(target)
        else:
            # Defenders hold; attackers retreat once per formation.
            for force_id in atk_forces:
                preferred = None
                if is_op_contact and force_id == str(getattr(pending, "attacker_formation_id", "") or ""):
                    preferred = str(pending.origin_province_id or "") or None
                self._resolve_formation_after_battle(
                    force_id,
                    lost=True,
                    exclude_province=target.province_id,
                    preferred_retreat=preferred,
                )
            for force_id in def_forces:
                self._resolve_formation_after_battle(
                    force_id,
                    lost=False,
                    hold_province=None,  # stay put
                )

        # Entry-contact movers stay blocked for the remainder of the turn.
        if is_op_contact:
            from .operational_schema import MoveOrderStatus

            for force_id in atk_forces:
                force = self.state.strategic_formations.get(force_id)
                if force is None or force.move_order is None:
                    continue
                if force.move_order.status not in {
                    MoveOrderStatus.COMPLETED.value,
                    MoveOrderStatus.CANCELLED.value,
                }:
                    from dataclasses import replace

                    force.move_order = replace(
                        force.move_order, status=MoveOrderStatus.BLOCKED.value
                    )

        pending.completed = True
        self.state.pending_battle = None
        from .strategic import evaluate_campaign_outcome

        evaluate_campaign_outcome(self.state)
        self.state.validate()

    def _participants_battalions(self, participants) -> list[Battalion]:
        battalions: list[Battalion] = []
        seen: set[str] = set()
        for part in participants:
            if part.battalion_id in seen:
                continue
            battalion = self.state.battalions.get(part.battalion_id)
            if battalion is None:
                continue
            seen.add(part.battalion_id)
            battalions.append(battalion)
        return battalions

    def _formations_for_battalions(self, battalions: list[Battalion]) -> list[str]:
        force_ids: list[str] = []
        seen: set[str] = set()
        for battalion in battalions:
            force_id = battalion.strategic_formation_id
            if not force_id or force_id in seen:
                continue
            if force_id not in self.state.strategic_formations:
                continue
            seen.add(force_id)
            force_ids.append(force_id)
        return sorted(force_ids)

    def _resolve_formation_after_battle(
        self,
        force_id: str,
        *,
        lost: bool,
        exclude_province: str | None = None,
        preferred_retreat: str | None = None,
        hold_province: str | None = None,
    ) -> None:
        """Once-per-formation post-battle placement. Keeps all survivors co-located."""
        from .operational_position import place_formation_at_province_anchor

        force = self.state.strategic_formations.get(force_id)
        if force is None:
            return
        # Drop destroyed members already removed from state.
        force.battalion_ids = [
            battalion_id
            for battalion_id in force.battalion_ids
            if battalion_id in self.state.battalions
        ]
        if not force.battalion_ids:
            self.state.strategic_formations.pop(force_id, None)
            if force.commander_id and force.commander_id in self.state.commanders:
                commander = self.state.commanders[force.commander_id]
                if commander.assigned_strategic_formation_id == force_id:
                    commander.assigned_strategic_formation_id = None
                    commander.status = CommanderStatus.UNASSIGNED
            return

        if not lost:
            if hold_province:
                force.province_id = hold_province
            # Co-locate all surviving members and snap operational anchor when graph exists.
            for battalion_id in force.battalion_ids:
                battalion = self.state.battalions.get(battalion_id)
                if battalion is not None:
                    battalion.province_id = force.province_id
                    battalion.strategic_formation_id = force_id
            place_formation_at_province_anchor(force, self.state)
            return

        # Lost: retreat once.
        destination: str | None = None
        if (
            preferred_retreat
            and preferred_retreat in self.state.provinces
            and preferred_retreat != exclude_province
            and is_friendly_owner(
                self.state,
                force.faction,
                self.state.provinces[preferred_retreat].owner,
            )
        ):
            destination = preferred_retreat
        if destination is None:
            current_id = force.province_id
            if current_id not in self.state.provinces:
                current_id = exclude_province or next(iter(self.state.provinces))
            current = self.state.provinces[current_id]
            candidates = [
                province_id
                for province_id in current.neighbors
                if province_id != exclude_province
                and is_friendly_owner(
                    self.state, force.faction, self.state.provinces[province_id].owner
                )
                and not self._hostile_battalion_in(province_id, force.faction)
            ]
            if preferred_retreat and preferred_retreat in candidates:
                destination = preferred_retreat
            elif candidates:
                destination = sorted(candidates)[0]
        if destination is None:
            # No legal retreat: destroy the whole formation.
            for battalion_id in list(force.battalion_ids):
                self._remove_battalion(battalion_id)
            return
        force.province_id = destination
        for battalion_id in force.battalion_ids:
            battalion = self.state.battalions.get(battalion_id)
            if battalion is not None:
                battalion.province_id = destination
                battalion.strategic_formation_id = force_id
        place_formation_at_province_anchor(force, self.state)

    def _hostile_battalion_in(self, province_id: str, faction: Faction) -> bool:
        for battalion in self.state.battalions.values():
            if battalion.province_id != province_id:
                continue
            if battalion.faction == faction or are_allied(self.state, faction, battalion.faction):
                continue
            return True
        return False

    def _retreat_or_remove(self, battalion: Battalion, *, excluding: str) -> None:
        """Legacy single-battalion retreat (kept for non-formation callers)."""
        if battalion.is_destroyed:
            self._remove_battalion(battalion.battalion_id)
            return
        force_id = battalion.strategic_formation_id
        if force_id and force_id in self.state.strategic_formations:
            self._resolve_formation_after_battle(
                force_id,
                lost=True,
                exclude_province=excluding,
            )
            return
        current = self._get_province(battalion.province_id)
        candidates = [
            province_id
            for province_id in current.neighbors
            if province_id != excluding
            and is_friendly_owner(self.state, battalion.faction, self.state.provinces[province_id].owner)
            and self._battalion_in(province_id) is None
        ]
        if candidates:
            battalion.province_id = sorted(candidates)[0]
            self._sync_strategic_formation_location(battalion)
        else:
            self._remove_battalion(battalion.battalion_id)

    def _reject_if_operational_order_locked(self, battalion: Battalion) -> None:
        """Legacy adjacency move cannot bypass a committed/active operational order."""
        from .operational_schema import MoveOrderStatus

        force_id = battalion.strategic_formation_id
        if not force_id:
            return
        force = self.state.strategic_formations.get(force_id)
        if force is None or force.move_order is None:
            return
        status = force.move_order.status
        if status in {
            MoveOrderStatus.COMMITTED.value,
            MoveOrderStatus.ACTIVE.value,
        }:
            raise ValueError(
                f"Strategic formation {force_id} has a {status} operational order; "
                "legacy adjacency move is locked until the order completes"
            )

    def _sync_strategic_formation_location(self, battalion: Battalion) -> None:
        from .operational_position import place_formation_at_province_anchor

        force_id = battalion.strategic_formation_id
        if not force_id:
            return
        force = self.state.strategic_formations.get(force_id)
        if force is None:
            return
        force.province_id = battalion.province_id
        # Adjacency moves stay province-authoritative until S3; snap to new province anchor
        # only when this map has an operational graph.
        place_formation_at_province_anchor(force, self.state)
        for member_id in force.battalion_ids:
            member = self.state.battalions.get(member_id)
            if member is not None:
                member.province_id = force.province_id

    def _remove_battalion(self, battalion_id: str) -> None:
        battalion = self.state.battalions.pop(battalion_id, None)
        if battalion is None:
            return
        force_id = battalion.strategic_formation_id
        if not force_id:
            return
        force = self.state.strategic_formations.get(force_id)
        if force is None:
            return
        force.battalion_ids = [item for item in force.battalion_ids if item != battalion_id]
        if not force.battalion_ids:
            self.state.strategic_formations.pop(force_id, None)
            if force.commander_id and force.commander_id in self.state.commanders:
                commander = self.state.commanders[force.commander_id]
                if commander.assigned_strategic_formation_id == force_id:
                    commander.assigned_strategic_formation_id = None
                    commander.status = CommanderStatus.UNASSIGNED

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
        supply_factor = 0.4 + battalion.supply / 100 * 0.6
        condition_factor = 0.35 + battalion.condition / 100 * 0.65
        experience_factor = 1 + min(battalion.experience, 1000) / 5000
        return max(base * supply_factor * condition_factor * experience_factor, 0.1)

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
        return next((battalion for battalion in self.state.battalions.values() if battalion.province_id == province_id), None)

    def _require_pending_battle(self) -> PendingBattle:
        if self.state.pending_battle is None:
            raise RuntimeError("There is no pending battle")
        return self.state.pending_battle
