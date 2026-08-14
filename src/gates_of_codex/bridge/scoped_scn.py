from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from ..codex.catalog import CodeXCatalog
from ..models import CampaignState, PendingBattle
from ..modstack import mod_root, resource_root
from .scn import CampaignScnBuilder, ObjectIdAllocator, parse_breed_inventory


class ParticipantScopedCampaignScnBuilder(CampaignScnBuilder):
    """Materialize tactical participants from explicitly scoped catalogs.

    The ordinary tactical catalog remains the default. A caller may assign a
    different catalog to one battalion and may pin individual unit definitions
    to one resource root for breed/inventory closure. This prevents an
    encounter-local content exception from changing same-name definitions or
    crew assets consumed by unrelated participants in the same battle.
    """

    def __init__(
        self,
        catalog: CodeXCatalog,
        code_x_directory: str | Path | None = None,
        *,
        resource_stack: Iterable[str | Path] | None = None,
        participant_catalogs: Mapping[str, CodeXCatalog] | None = None,
        pinned_unit_roots: Mapping[str, Mapping[str, str | Path]] | None = None,
    ) -> None:
        super().__init__(
            catalog,
            code_x_directory,
            resource_stack=resource_stack,
        )
        self.participant_catalogs = dict(participant_catalogs or {})
        self.pinned_unit_roots: dict[str, dict[str, Path]] = {
            str(battalion_id): {
                str(unit_name): mod_root(root)
                for unit_name, root in unit_roots.items()
            }
            for battalion_id, unit_roots in (pinned_unit_roots or {}).items()
        }
        configured_roots = set(self.roots)
        for battalion_id, unit_roots in self.pinned_unit_roots.items():
            for unit_name, root in unit_roots.items():
                if root not in configured_roots:
                    raise ValueError(
                        f"Pinned tactical source root for {battalion_id}/{unit_name} "
                        f"is outside the configured resource stack: {root}"
                    )
        self._pinned_inventory_cache: dict[
            tuple[str, str, str, str], list
        ] = {}

    def build(self, state: CampaignState, pending: PendingBattle) -> str:
        ids = ObjectIdAllocator()
        objects: list[str] = []
        inventories: list[str] = []
        squads: list[str] = []
        participants = {
            item.battalion_id: item.stage
            for item in (*pending.attacking_participants, *pending.defending_participants)
        }
        self._preflight_rosters(state, participants)
        player_by_battalion = {
            item.battalion_id: (0 if pending.player_is_attacker else 1)
            for item in pending.attacking_participants
        }
        player_by_battalion.update(
            {
                item.battalion_id: (1 if pending.player_is_attacker else 0)
                for item in pending.defending_participants
            }
        )

        for battalion_id, stage in participants.items():
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                raise KeyError(f"Missing battalion {battalion_id}")
            player = player_by_battalion.get(battalion_id, 0)
            catalog = self._catalog_for_battalion(battalion_id)
            for entry in battalion.roster:
                if entry.quantity <= 0:
                    continue
                definition = catalog.units.get(entry.unit_name)
                if definition is None:
                    raise KeyError(
                        f"Code:X catalog for {battalion_id} has no definition for {entry.unit_name}"
                    )
                pinned_root = self._pinned_root_for(battalion_id, entry.unit_name)
                for _ in range(entry.quantity):
                    object_ids: list[str] = []
                    for vehicle in definition.vehicles[:1]:
                        object_id, mid = ids.allocate()
                        object_ids.append(object_id)
                        objects.append(self._entity(vehicle, object_id, player=player, mid=mid))
                        inventories.append(self._inventory(object_id, items=[]))
                    for breed, count in definition.members.items():
                        for _ in range(count):
                            object_id, mid = ids.allocate()
                            object_ids.append(object_id)
                            objects.append(
                                self._human_scoped(
                                    breed,
                                    definition.side,
                                    definition.period,
                                    object_id,
                                    player=player,
                                    mid=mid,
                                    pinned_root=pinned_root,
                                )
                            )
                            inventories.append(
                                self._inventory(
                                    object_id,
                                    items=self._breed_inventory_scoped(
                                        breed,
                                        definition.side,
                                        definition.period,
                                        pinned_root=pinned_root,
                                    ),
                                )
                            )
                    if not object_ids:
                        raise ValueError(f"Unit {entry.unit_name} has no materializable members")
                    squads.append(
                        f'\t\t{{"{entry.unit_name}" "{stage}" {" ".join(object_ids)}}}'
                    )

        text = (
            "{campaign\n"
            + "\n".join(objects + inventories)
            + "\n\t{CampaignSquads\n"
            + "\n".join(squads)
            + "\n\t}\n}\n"
        )
        self.validate(text)
        return text

    def _catalog_for_battalion(self, battalion_id: str) -> CodeXCatalog:
        return self.participant_catalogs.get(battalion_id, self.catalog)

    def _pinned_root_for(self, battalion_id: str, unit_name: str) -> Path | None:
        return self.pinned_unit_roots.get(battalion_id, {}).get(unit_name)

    def _preflight_rosters(self, state: CampaignState, participants: dict[str, str]) -> None:
        invalid: list[str] = []
        for battalion_id in participants:
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                invalid.append(f"{battalion_id}: battalion is missing")
                continue
            catalog = self._catalog_for_battalion(battalion_id)
            for entry in battalion.roster:
                if entry.quantity <= 0:
                    continue
                definition = catalog.units.get(entry.unit_name)
                if definition is None:
                    invalid.append(
                        f"{battalion_id}: {entry.unit_name} is absent from its scoped Code:X catalog"
                    )
                elif not definition.materializable:
                    sources = ", ".join(definition.source_files) or "unknown source"
                    invalid.append(
                        f"{battalion_id}: {entry.unit_name} has no parsed members or vehicles ({sources})"
                    )
        if invalid:
            details = "\n- ".join(sorted(set(invalid)))
            raise ValueError(f"Tactical roster contains nonmaterializable Code:X entries:\n- {details}")

    def _resolve_breed_path_scoped(
        self,
        breed: str,
        side: str,
        period: str,
        *,
        pinned_root: Path | None,
    ) -> Path:
        if pinned_root is None:
            return super()._resolve_breed_path(breed, side, period)

        resources = resource_root(pinned_root)
        candidates = [
            resources / f"set/breed/mp/{side}/{period}/{breed}.set",
            resources / f"set/breed/mp/{side}/{breed}.set",
            resources / f"set/breed/mp/{period}/{side}/{breed}.set",
            resources / f"set/breed/{breed}.set",
        ]
        for path in candidates:
            if path.is_file():
                return path

        breed_root = resources / "set/breed"
        matches = sorted(
            path
            for path in breed_root.rglob("*.set")
            if path.stem.casefold() == breed.casefold()
        ) if breed_root.is_dir() else []
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            detail = ", ".join(path.relative_to(resources).as_posix() for path in matches)
            raise ValueError(
                f"Pinned tactical breed {breed} is ambiguous in {pinned_root}: {detail}"
            )
        raise FileNotFoundError(
            f"Could not resolve pinned tactical breed {breed} in source root {pinned_root}"
        )

    def _human_scoped(
        self,
        breed: str,
        side: str,
        period: str,
        object_id: str,
        *,
        player: int,
        mid: int,
        pinned_root: Path | None,
    ) -> str:
        if pinned_root is None:
            return super()._human(
                breed,
                side,
                period,
                object_id,
                player=player,
                mid=mid,
            )
        path = self._resolve_breed_path_scoped(
            breed,
            side,
            period,
            pinned_root=pinned_root,
        )
        breed_token = self._to_breed_token(
            path.relative_to(resource_root(pinned_root)).as_posix()
        )
        return (
            f'\t{{Human "{breed_token}" {object_id}\n'
            f"\t\t{{Position 0 0}}\n"
            f"\t\t{{xform zl 90}}\n"
            f'\t\t{{TexMod "auto"}}\n'
            f"\t\t{{SpawnedInFog}}\n"
            f"\t\t{{Player {player}}}\n"
            f"\t\t{{MID {mid}}}\n"
            f'\t\t{{FsmState "stand_noaim"}}\n'
            f"\t}}"
        )

    def _breed_inventory_scoped(
        self,
        breed: str,
        side: str,
        period: str,
        *,
        pinned_root: Path | None,
    ) -> list:
        if pinned_root is None:
            return super()._breed_inventory(breed, side, period)
        cache_key = (
            str(pinned_root).casefold(),
            side.casefold(),
            period.casefold(),
            breed.casefold(),
        )
        cached = self._pinned_inventory_cache.get(cache_key)
        if cached is not None:
            return cached
        path = self._resolve_breed_path_scoped(
            breed,
            side,
            period,
            pinned_root=pinned_root,
        )
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        items = parse_breed_inventory(text)
        self._pinned_inventory_cache[cache_key] = items
        return items
