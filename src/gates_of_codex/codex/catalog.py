from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

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


@dataclass(slots=True)
class CodeXCatalog:
    units: dict[str, UnitDefinition] = field(default_factory=dict)
    signature: str = ""
    resource_stack: list[str] = field(default_factory=list)

    def by_faction(self, faction: str) -> list[UnitDefinition]:
        return sorted((unit for unit in self.units.values() if unit.side == faction), key=lambda unit: unit.name)

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

    def scan(self, code_x_directory: str | Path) -> CodeXCatalog:
        return self.scan_stack([code_x_directory])

    def scan_stack(self, resource_stack: Iterable[str | Path]) -> CodeXCatalog:
        roots = normalize_stack(resource_stack)
        if not roots:
            raise ValueError("Code:X resource stack is empty")
        units: dict[str, UnitDefinition] = {}
        for layer_index, root in enumerate(roots):
            if not root.is_dir():
                raise FileNotFoundError(f"Stack layer does not exist: {root}")
            layer_units: dict[str, UnitDefinition] = {}
            resources = resource_root(root)
            conquest_root = resources / "set/multiplayer/units/conquest"
            if conquest_root.is_dir():
                for path in sorted(conquest_root.rglob("*.set")):
                    self._scan_set(path, resources, layer_units, layer_index, root.name)
            lua_root = resources / "script/multiplayer/units"
            if lua_root.is_dir():
                for path in sorted(lua_root.rglob("*.lua")):
                    self._scan_lua(path, resources, layer_units, layer_index, root.name)
            for name, overlay in layer_units.items():
                existing = units.get(name)
                units[name] = self._merge(existing, overlay) if existing else overlay
        return CodeXCatalog(
            units=units,
            signature=stack_signature(roots),
            resource_stack=[str(root) for root in roots],
        )

    def _scan_set(
        self,
        path: Path,
        resources: Path,
        units: dict[str, UnitDefinition],
        layer_index: int,
        layer_name: str,
    ) -> None:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        period = next((part for part in path.parts if re.fullmatch(r"20\d\ds|mid|late|early", part.lower())), "2022s")
        default_side = next((part.lower() for part in path.parts if part.lower() in self.FACTIONS), "")
        source = f"{layer_index}:{layer_name}/{path.relative_to(resources).as_posix()}"
        for name, body in self._named_blocks(text):
            side = self._side_from_name(name) or default_side
            if side not in self.FACTIONS:
                continue
            unit = units.setdefault(name, UnitDefinition(name=name, side=side, period=period))
            if source not in unit.source_files:
                unit.source_files.append(source)
            for breed, count in re.findall(r'\{(?:member|breed)\s+"?([^"\s{}]+)"?\s*(\d+)?', body, flags=re.I):
                unit.members[breed] = unit.members.get(breed, 0) + int(count or 1)
            for vehicle in re.findall(r'\{(?:vehicle|entity)\s+"?([^"\s{}]+)', body, flags=re.I):
                if vehicle not in unit.vehicles:
                    unit.vehicles.append(vehicle)
            for action in re.findall(r'\{action\s+"?([^"\s{}]+)', body, flags=re.I):
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
    ) -> None:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        default_side = next((part.lower() for part in path.parts if part.lower() in self.FACTIONS), "")
        source = f"{layer_index}:{layer_name}/{path.relative_to(resources).as_posix()}"
        for row in re.finditer(r'\{[^{}]*unit\s*=\s*"([^"]+)"[^{}]*\}', text, flags=re.S):
            body = row.group(0)
            name = row.group(1)
            side = self._side_from_name(name) or default_side
            if side not in self.FACTIONS:
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

    @staticmethod
    def _named_blocks(text: str):
        pattern = re.compile(r'\{\s*"?([^"\s{}]+(?:\([^)]*\))?)"?\s*', re.M)
        for match in pattern.finditer(text):
            depth = 0
            end = None
            for index in range(match.start(), len(text)):
                if text[index] == "{":
                    depth += 1
                elif text[index] == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            if end:
                yield match.group(1), text[match.end():end - 1]

    @staticmethod
    def _side_from_name(name: str) -> str:
        match = re.search(r'\((nato|ukr|rusa|prc)\)', name, flags=re.I)
        return match.group(1).lower() if match else ""

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
