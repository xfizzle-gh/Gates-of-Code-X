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
        is_edge_contact = bool(str(getattr(pending, "encounter_edge_id", "") or "").strip())
        edge_progress = getattr(pending, "encounter_progress_milli", None)
        edge_id = str(getattr(pending, "encounter_edge_id", "") or "")

        if winner == pending.attacker_faction:
            for force_id in def_forces:
                preferred = None
                hold_node = None
                if is_edge_contact:
                    preferred = self._edge_retreat_node(force_id, edge_id)
                    hold_node = self._edge_retreat_hold_node(force_id)
                self._resolve_formation_after_battle(
                    force_id,
                    lost=True,
                    exclude_province=target.province_id,
                    preferred_retreat=preferred,
                    hold_node_id=hold_node,
                )
            operational_campaign = self._is_operational_campaign()
            hold_node = None if is_edge_contact else self._hold_node_after_battle(
                pending,
                is_op_contact=is_op_contact,
                operational_campaign=operational_campaign,
                province_id=target.province_id,
            )
            for force_id in atk_forces:
                if is_edge_contact:
                    self._hold_formation_on_edge(
                        force_id,
                        edge_id=edge_id,
                        progress_canonical=edge_progress,
                    )
                else:
                    self._resolve_formation_after_battle(
                        force_id,
                        lost=False,
                        hold_province=target.province_id,
                        hold_node_id=hold_node,
                    )
            # Operational-capable campaigns never flip ownership from battle wins (S5).
            # Legacy campaigns without operational maneuver retain immediate ownership change.
            if (
                not operational_campaign
                and not is_op_contact
                and any(self.state.strategic_formations.get(fid) for fid in atk_forces)
            ):
                target.owner = pending.attacker_faction
                from .strategic import sync_province_infrastructure_owner

                sync_province_infrastructure_owner(target)
        else:
            # Defenders hold; attackers retreat once per formation.
            for force_id in atk_forces:
                preferred = None
                hold_node = None
                if is_edge_contact:
                    preferred = self._edge_retreat_node(force_id, edge_id)
                    hold_node = self._edge_retreat_hold_node(force_id)
                elif is_op_contact and force_id == str(
                    getattr(pending, "attacker_formation_id", "") or ""
                ):
                    preferred = str(pending.origin_province_id or "") or None
                self._resolve_formation_after_battle(
                    force_id,
                    lost=True,
                    exclude_province=target.province_id,
                    preferred_retreat=preferred,
                    hold_node_id=hold_node,
                )
            for force_id in def_forces:
                if is_edge_contact:
                    self._hold_formation_on_edge(
                        force_id,
                        edge_id=edge_id,
                        progress_canonical=edge_progress,
                    )
                else:
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

    def _is_operational_campaign(self) -> bool:
        return bool(self.state.map_metadata.get("operational_maneuver_enabled")) or bool(
            str(self.state.map_metadata.get("operational_graph", "") or "").strip()
        )

    def _edge_retreat_node(self, force_id: str, edge_id: str) -> str | None:
        """Province of the exact previous legal node for edge retreat (not arbitrary neighbor)."""
        # Prefer exact node recorded at contact stop.
        store = self.state.map_metadata.get("operational_edge_retreat_nodes")
        node_id = None
        if isinstance(store, dict):
            node_id = store.get(force_id) or store.get(str(force_id))
        if node_id:
            from .operational_position import load_operational_graph_for_state

            graph = load_operational_graph_for_state(self.state)
            if graph:
                node = next(
                    (
                        n
                        for n in graph.get("nodes") or []
                        if str(n.get("node_id")) == str(node_id)
                    ),
                    None,
                )
                if node:
                    province_id = str(node.get("province_id") or "")
                    if province_id:
                        return province_id
        force = self.state.strategic_formations.get(force_id)
        if force is None:
            return None
        pos = force.position
        if pos is not None and pos.mode == "on_edge" and pos.facing_node_id:
            from .operational_position import load_operational_graph_for_state

            graph = load_operational_graph_for_state(self.state)
            if graph:
                for edge in graph.get("edges") or []:
                    if str(edge.get("edge_id")) != edge_id:
                        continue
                    a, b = str(edge.get("a")), str(edge.get("b"))
                    facing = str(pos.facing_node_id)
                    origin = b if facing == a else a
                    node = next(
                        (
                            n
                            for n in graph.get("nodes") or []
                            if str(n.get("node_id")) == origin
                        ),
                        None,
                    )
                    if node:
                        return str(node.get("province_id") or "") or None
        return force.province_id or None

    def _edge_retreat_hold_node(self, force_id: str) -> str | None:
        """Exact previous legal node ID for post-battle placement."""
        store = self.state.map_metadata.get("operational_edge_retreat_nodes")
        if isinstance(store, dict):
            node_id = store.get(force_id) or store.get(str(force_id))
            if node_id:
                return str(node_id)
        return None

    def _hold_formation_on_edge(
        self,
        force_id: str,
        *,
        edge_id: str,
        progress_canonical: int | None,
    ) -> None:
        """Keep winners/holders on the encounter edge at canonical progress."""
        from .operational_interception import _formation_progress_from_canonical
        from .operational_position import load_operational_graph_for_state
        from .operational_schema import FormationOperationalPosition, PositionMode

        force = self.state.strategic_formations.get(force_id)
        if force is None or not edge_id:
            return
        graph = load_operational_graph_for_state(self.state)
        if graph is None:
            return
        edge_row = next(
            (e for e in graph.get("edges") or [] if str(e.get("edge_id")) == edge_id),
            None,
        )
        if edge_row is None:
            return
        from .operational_schema import OperationalRouteEdge

        edge = OperationalRouteEdge(
            edge_id=str(edge_row["edge_id"]),
            a=str(edge_row["a"]),
            b=str(edge_row["b"]),
            kind=str(edge_row["kind"]),
            authority=str(edge_row["authority"]),
            length_px=int(edge_row["length_px"]),
            base_move_points_milli=int(edge_row["base_move_points_milli"]),
            movement_cost_milli=int(edge_row["movement_cost_milli"]),
            requires_port=bool(edge_row["requires_port"]),
            can_be_blockaded=bool(edge_row["can_be_blockaded"]),
            traversal_enabled=bool(edge_row["traversal_enabled"]),
            bidirectional=bool(edge_row["bidirectional"]),
            province_ids=list(edge_row.get("province_ids") or []),
        )
        facing = None
        if force.position and force.position.facing_node_id:
            facing = str(force.position.facing_node_id)
        if facing not in {edge.a, edge.b}:
            facing = edge.b
        progress = 0 if progress_canonical is None else int(progress_canonical)
        form_progress = _formation_progress_from_canonical(
            progress, facing=facing, edge=edge
        )
        force.position = FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id=edge_id,
            progress_milli=form_progress,
            facing_node_id=facing,
        )
        force.movement_state = "on_route"
        from .operational_movement import sync_province_from_position

        sync_province_from_position(self.state, force)
        for battalion_id in force.battalion_ids:
            battalion = self.state.battalions.get(battalion_id)
            if battalion is not None:
                battalion.province_id = force.province_id
                battalion.strategic_formation_id = force_id

    def _hold_node_after_battle(
        self,
        pending,
        *,
        is_op_contact: bool,
        operational_campaign: bool,
        province_id: str,
    ) -> str | None:
        """Node winners must remain on for post-battle site capture."""
        if is_op_contact:
            node_id = str(getattr(pending, "encounter_node_id", "") or "").strip()
            return node_id or None
        if operational_campaign:
            return self._control_site_node_for_province(province_id)
        return None

    def _control_site_node_for_province(self, province_id: str) -> str | None:
        """Deterministic control-site node for a province (highest weight, then site_id)."""
        from .operational_capture import list_control_sites

        candidates = [
            site
            for site in list_control_sites(self.state)
            if str(site.get("province_id") or "") == province_id
            and str(site.get("route_node_id") or "").strip()
        ]
        if not candidates:
            return None

        def sort_key(site: dict) -> tuple:
            try:
                weight = -int(site.get("control_weight_milli") or 0)
            except (TypeError, ValueError):
                weight = 0
            return (weight, str(site.get("site_id") or ""))

        best = sorted(candidates, key=sort_key)[0]
        return str(best["route_node_id"])

    def _resolve_formation_after_battle(
        self,
        force_id: str,
        *,
        lost: bool,
        exclude_province: str | None = None,
        preferred_retreat: str | None = None,
        hold_province: str | None = None,
        hold_node_id: str | None = None,
    ) -> None:
        """Once-per-formation post-battle placement. Keeps all survivors co-located."""
        from .operational_position import place_formation_at_province_anchor
        from .operational_schema import FormationOperationalPosition, PositionMode

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
            for battalion_id in force.battalion_ids:
                battalion = self.state.battalions.get(battalion_id)
                if battalion is not None:
                    battalion.province_id = force.province_id
                    battalion.strategic_formation_id = force_id
            if hold_node_id:
                # Stay on the encounter/control-site node so capture ticks can begin.
                force.position = FormationOperationalPosition(
                    mode=PositionMode.AT_NODE.value,
                    node_id=hold_node_id,
                    progress_milli=0,
                )
                force.movement_state = "at_anchor"
            elif hold_province:
                place_formation_at_province_anchor(force, self.state)
            # else: keep existing operational position (holding defenders).
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
        # Prefer exact previous legal node when recorded (edge retreat).
        if hold_node_id:
            force.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=hold_node_id,
                progress_milli=0,
            )
            force.movement_state = "at_anchor"
        else:
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
