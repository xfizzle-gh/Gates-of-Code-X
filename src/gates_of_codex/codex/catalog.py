from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from ..goh_source import MacroCall, SourceEntry, scan_source_entries
from ..modstack import normalize_stack, resource_root, stack_signature


@dataclass(slots=True)
class UnitDefinition:
    name: str
    side: str
    period: str = "2022s"
    doctrine: str = ""
    members: dict[str, int] = field(default_factory=dict)
    vehicles: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    type_tags: list[str] = field(default_factory=list)
    category: str = "unknown"
    doctrine_cost: int = 0
    manpower_estimate: int = 0
    source_files: list[str] = field(default_factory=list)

    @property
    def materializable(self) -> bool:
        """Whether the tactical bridge can create at least one engine object."""

        return bool(self.members or self.vehicles)


class CatalogUnits(dict[str, UnitDefinition]):
    """Raw catalog mapping with materializable iteration for campaign systems.

    Code:X Lua tables can describe doctrine/shop entries without providing a
    concrete squad definition. Those rows remain addressable through normal
    mapping operations and are preserved by serialization, but campaign-facing
    iteration excludes them so they cannot enter rosters or the economy.
    """

    def values(self):  # type: ignore[override]
        return [unit for unit in super().values() if unit.materializable]

    def raw_values(self):
        return super().values()


@dataclass(slots=True)
class CodeXCatalog:
    units: dict[str, UnitDefinition] = field(default_factory=dict)
    signature: str = ""
    resource_stack: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.units, CatalogUnits):
            self.units = CatalogUnits(self.units)

    def by_faction(self, faction: str) -> list[UnitDefinition]:
        return sorted((unit for unit in self.units.values() if unit.side == faction), key=lambda unit: unit.name)

    def raw_by_faction(self, faction: str) -> list[UnitDefinition]:
        values = self.units.raw_values() if isinstance(self.units, CatalogUnits) else self.units.values()
        return sorted((unit for unit in values if unit.side == faction), key=lambda unit: unit.name)

    def diagnostic_counts(self) -> dict[str, dict[str, int]]:
        return {
            faction: {
                "raw": len(self.raw_by_faction(faction)),
                "materializable": len(self.by_faction(faction)),
            }
            for faction in CodeXCatalogScanner.FACTIONS
        }

    def to_dict(self) -> dict:
        return {
            "signature": self.signature,
            "resource_stack": self.resource_stack,
            "units": {name: asdict(unit) for name, unit in self.units.items()},
        }

    @classmethod
    def from_dict(cls, value: dict) -> "CodeXCatalog":
        return cls(
            units={name: UnitDefinition(**unit) for name, unit in value.get("units", {}).items()},
            signature=value.get("signature", ""),
            resource_stack=list(value.get("resource_stack", [])),
        )

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "CodeXCatalog":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))


class CodeXCatalogScanner:
    FACTIONS = ("nato", "ukr", "rusa", "prc")
    # These are source/content namespaces present in West81. They are not valid
    # GoH tactical armies for Gates campaigns. They may be scanned only when an
    # explicit caller needs source-backed legacy materialization (for example
    # #48 encounter-only garrisons).
    LEGACY_SOURCE_SIDES = ("sov", "gdr", "csa", "frg")
    SOURCE_SIDES = (*FACTIONS, *LEGACY_SOURCE_SIDES)
    SOURCE_EXTENSIONS = {".set", ".goh"}
    _MACRO_MEMBER_RE = re.compile(r"\b(?:c\d+|crew\d*|member\d*|breed\d*)\(([^:()\s]+):(\d+)\)", re.I)
    _ENTITY_MACRO_HINTS = (
        "vehicle",
        "tank",
        "cannon",
        "gun",
        "empl",
        "artillery",
        "mortar",
        "howitzer",
        "aa",
        "spg",
    )

    def scan(self, code_x_directory: str | Path) -> CodeXCatalog:
        return self.scan_stack([code_x_directory])

    def scan_stack(
        self,
        resource_stack: Iterable[str | Path],
        *,
        include_legacy_sources: bool = False,
    ) -> CodeXCatalog:
        roots = normalize_stack(resource_stack)
        if not roots:
            raise ValueError("Code:X resource stack is empty")
        accepted_sides = frozenset(
            self.SOURCE_SIDES if include_legacy_sources else self.FACTIONS
        )
        units: dict[str, UnitDefinition] = {}
        for layer_index, root in enumerate(roots):
            if not root.is_dir():
                raise FileNotFoundError(f"Stack layer does not exist: {root}")
            layer_units: dict[str, UnitDefinition] = {}
            resources = resource_root(root)

            # Lua rows provide the exact campaign/shop template IDs, including
            # faction suffixes. Scan them first so GoH source macros can merge
            # composition into those rows instead of creating duplicate aliases.
            lua_root = resources / "script/multiplayer/units"
            if lua_root.is_dir():
                for path in sorted(lua_root.rglob("*.lua")):
                    self._scan_lua(
                        path,
                        resources,
                        layer_units,
                        layer_index,
                        root.name,
                        accepted_sides,
                    )

            conquest_root = resources / "set/multiplayer/units/conquest"
            if conquest_root.is_dir():
                for path in sorted(
                    candidate
                    for candidate in conquest_root.rglob("*")
                    if candidate.is_file() and candidate.suffix.lower() in self.SOURCE_EXTENSIONS
                ):
                    self._scan_source(
                        path,
                        resources,
                        layer_units,
                        layer_index,
                        root.name,
                        accepted_sides,
                    )

            for name, overlay in layer_units.items():
                existing = units.get(name)
                units[name] = self._merge(existing, overlay) if existing else overlay
        return CodeXCatalog(
            units=units,
            signature=stack_signature(roots),
            resource_stack=[str(root) for root in roots],
        )

    def _scan_source(
        self,
        path: Path,
        resources: Path,
        units: dict[str, UnitDefinition],
        layer_index: int,
        layer_name: str,
        accepted_sides: frozenset[str],
    ) -> None:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        default_period = self._period_from_path(path)
        default_side = self._side_from_path(path)
        source = f"{layer_index}:{layer_name}/{path.relative_to(resources).as_posix()}"

        for entry in self._source_entries(text, source):
            side = self._side_from_name(entry.name) or self._call_value(entry.calls, "side") or default_side
            side = side.lower()
            if side not in accepted_sides:
                continue
            period = self._call_value(entry.calls, "period") or default_period
            name = self._canonical_name(entry.name, side, units)
            unit = units.setdefault(name, UnitDefinition(name=name, side=side, period=period))
            unit.side = side
            if period:
                unit.period = period
            if source not in unit.source_files:
                unit.source_files.append(source)

            members = self._members(entry.raw, entry.calls)
            for breed, count in members.items():
                unit.members[breed] = max(unit.members.get(breed, 0), count)

            explicit_vehicles = self._vehicles(entry.calls)
            for vehicle in explicit_vehicles:
                if vehicle not in unit.vehicles:
                    unit.vehicles.append(vehicle)

            has_crew_slots = any(call.family == "crew" for call in entry.calls)
            macro_is_entity = any(hint in entry.macro_kind.lower() for hint in self._ENTITY_MACRO_HINTS)
            if not explicit_vehicles and (has_crew_slots or macro_is_entity):
                inferred = self._base_name(entry.name)
                if inferred and inferred not in unit.vehicles:
                    unit.vehicles.append(inferred)

            for action in self._actions(entry.calls):
                if action not in unit.actions:
                    unit.actions.append(action)
            unit.manpower_estimate = max(unit.manpower_estimate, sum(unit.members.values()))
            unit.category = self._category(unit)

    def _scan_lua(
        self,
        path: Path,
        resources: Path,
        units: dict[str, UnitDefinition],
        layer_index: int,
        layer_name: str,
        accepted_sides: frozenset[str],
    ) -> None:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        default_side = self._side_from_path(path)
        source = f"{layer_index}:{layer_name}/{path.relative_to(resources).as_posix()}"
        for name, body in self._lua_rows(text):
            side = self._side_from_name(name) or default_side
            if side not in accepted_sides:
                continue
            unit = units.setdefault(name, UnitDefinition(name=name, side=side))
            if source not in unit.source_files:
                unit.source_files.append(source)
            tags_match = re.search(r'type\s*=\s*\{([^}]*)\}', body, flags=re.S)
            if tags_match:
                for tag in re.findall(r'"([^"]+)"', tags_match.group(1)):
                    if tag not in unit.type_tags:
                        unit.type_tags.append(tag)
            cost = re.search(r'(?:dp|doctrineCost|cost)\s*=\s*(\d+)', body)
            if cost:
                unit.doctrine_cost = int(cost.group(1))
            if "Doctrine" in unit.type_tags:
                unit.doctrine = path.stem
            unit.category = self._category(unit)

    @staticmethod
    def _lua_rows(text: str) -> Iterator[tuple[str, str]]:
        for match in re.finditer(r'\bunit\s*=\s*"([^"]+)"', text):
            start = text.rfind("{", 0, match.start())
            if start < 0:
                continue
            depth = 0
            end = None
            for index in range(start, len(text)):
                if text[index] == "{":
                    depth += 1
                elif text[index] == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            if end is not None:
                yield match.group(1), text[start:end]

    @staticmethod
    def _source_entries(text: str, source: str) -> Sequence[SourceEntry]:
        return scan_source_entries(text, source).entries

    @staticmethod
    def _members(raw: str, calls: Sequence[MacroCall]) -> dict[str, int]:
        values: dict[str, int] = {}
        for breed, count in re.findall(
            r'\{(?:member|breed)\s+"?([^"\s{}]+)"?\s*(\d+)?',
            raw,
            flags=re.I,
        ):
            values[breed] = values.get(breed, 0) + int(count or 1)
        for call in calls:
            if call.family not in {"c", "crew", "member", "breed"} or ":" not in call.value:
                continue
            breed, count = call.value.rsplit(":", 1)
            if breed and count.isdigit():
                values[breed] = values.get(breed, 0) + int(count)
        if not any(":" in call.value for call in calls):
            for breed, count in CodeXCatalogScanner._MACRO_MEMBER_RE.findall(raw):
                values[breed] = values.get(breed, 0) + int(count)
        return values

    @staticmethod
    def _vehicles(calls: Sequence[MacroCall]) -> list[str]:
        return list(dict.fromkeys(
            call.value for call in calls
            if call.family in {"vehicle", "entity"} and call.value
        ))

    @staticmethod
    def _actions(calls: Sequence[MacroCall]) -> list[str]:
        return list(dict.fromkeys(
            call.value for call in calls if call.family == "action" and call.value
        ))

    @staticmethod
    def _call_value(calls: Sequence[MacroCall], family: str) -> str:
        return next((call.value for call in calls if call.family == family), "")

    @classmethod
    def _canonical_name(cls, name: str, side: str, units: dict[str, UnitDefinition]) -> str:
        if name in units:
            return name
        suffixed = f"{name}({side})"
        if suffixed in units:
            return suffixed
        base = cls._base_name(name).lower()
        matching = [
            candidate
            for candidate, definition in units.items()
            if definition.side == side and cls._base_name(candidate).lower() == base
        ]
        return sorted(matching)[0] if matching else name

    @staticmethod
    def _merge(base: UnitDefinition, overlay: UnitDefinition) -> UnitDefinition:
        return UnitDefinition(
            name=overlay.name,
            side=overlay.side or base.side,
            period=overlay.period if overlay.period != "2022s" or base.period == "2022s" else base.period,
            doctrine=overlay.doctrine or base.doctrine,
            members=dict(overlay.members) if overlay.members else dict(base.members),
            vehicles=list(overlay.vehicles) if overlay.vehicles else list(base.vehicles),
            actions=list(dict.fromkeys([*base.actions, *overlay.actions])),
            type_tags=list(overlay.type_tags) if overlay.type_tags else list(base.type_tags),
            category=overlay.category if overlay.category != "unknown" else base.category,
            doctrine_cost=overlay.doctrine_cost or base.doctrine_cost,
            manpower_estimate=overlay.manpower_estimate or base.manpower_estimate,
            source_files=list(dict.fromkeys([*base.source_files, *overlay.source_files])),
        )

    @classmethod
    def _side_from_path(cls, path: Path) -> str:
        pattern = "|".join(re.escape(side) for side in cls.SOURCE_SIDES)
        for part in path.parts:
            lowered = part.lower()
            if lowered in cls.SOURCE_SIDES:
                return lowered
            match = re.search(rf"(?:^|[_\-.])({pattern})(?:[_\-.]|$)", lowered)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _period_from_path(path: Path) -> str:
        return next(
            (part.lower() for part in path.parts if re.fullmatch(r"20\d\ds|mid|late|early", part.lower())),
            "2022s",
        )

    @staticmethod
    def _word_attr(raw: str, name: str) -> str:
        match = re.search(rf"\b{re.escape(name)}\(([^)\s]+)\)", raw, flags=re.I)
        return match.group(1).strip('"') if match else ""

    @classmethod
    def _side_from_name(cls, name: str) -> str:
        pattern = "|".join(re.escape(side) for side in cls.SOURCE_SIDES)
        match = re.search(rf'\(({pattern})\)', name, flags=re.I)
        return match.group(1).lower() if match else ""

    @classmethod
    def _base_name(cls, name: str) -> str:
        pattern = "|".join(re.escape(side) for side in cls.SOURCE_SIDES)
        return re.sub(rf"\(({pattern})\)$", "", name, flags=re.I)

    @staticmethod
    def _category(unit: UnitDefinition) -> str:
        tags = {tag.lower() for tag in unit.type_tags}
        if "tank" in tags:
            return "tank"
        if "ifv" in tags:
            return "ifv"
        if "artillery" in tags or "cannon" in tags:
            return "artillery"
        if "aa" in tags:
            return "air_defense"
        if "recon" in tags:
            return "recon"
        if unit.vehicles:
            return "vehicle"
        if unit.members or "infantry" in tags:
            return "infantry"
        return "unknown"
