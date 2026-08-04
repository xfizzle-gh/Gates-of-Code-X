from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .bridge.scn import BreedInventoryItem, parse_breed_inventory
from .codex.catalog import CodeXCatalog, CodeXCatalogScanner, UnitDefinition
from .modstack import normalize_stack, resource_root


AUDIT_SCHEMA_VERSION = 1
FULL_PLAYABLE_MINIMUM = 6
TACTICAL_SIDES = {"nato", "ukr", "rusa", "prc"}

NATION_ALIASES: dict[str, tuple[str, ...]] = {
    "usa": ("usa", "usarmy", "usmc", "american"),
    "united_kingdom": ("brit", "british", "britain", "ukarmy", "royalmarine", "royal_marines"),
    "germany": ("ger", "germany", "german", "bundeswehr", "westgermany", "west_germany", "frg"),
    "east_germany": ("eastgermany", "east_germany", "gdr", "ddr", "nva"),
    "france": ("fra", "france", "french"),
    "poland": ("pol", "poland", "polish"),
    "ukraine": ("ukraine", "ukrainian"),
    "russia": ("rus", "russia", "russian"),
    "soviet_legacy": ("soviet", "ussr", "redarmy", "red_army"),
    "prc": ("prc", "pla", "china", "chinese"),
    "dprk": ("dprk", "kpa", "northkorea", "north_korea", "northkorean", "nokor"),
    "belarus": ("belarus", "belarusian"),
    "serbia": ("serbia", "serbian", "serb"),
    "yugoslavia": ("yugoslavia", "yugoslav", "yugo", "jna"),
    "sweden": ("sweden", "swedish"),
    "switzerland": ("switzerland", "swiss"),
    "austria": ("austria", "austrian"),
    "turkey": ("turkey", "turkish"),
    "romania": ("romania", "romanian"),
    "baltic": ("baltic", "estonia", "estonian", "latvia", "latvian", "lithuania", "lithuanian"),
}

CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("air_defense", ("air_defense", "airdefense", "sam", "manpads", "stinger", "igla", "shilka", "tunguska", "aa")),
    ("anti_armor", ("anti_armor", "antiarmor", "antitank", "anti_tank", "atgm", "tow", "javelin", "kornet")),
    ("artillery", ("artillery", "howitzer", "mortar", "spg", "mlrs", "rocket_artillery")),
    ("recon", ("recon", "scout", "recce", "spetsnaz_recon")),
    ("engineering", ("engineer", "engineering", "sapper", "pioneer")),
    ("logistics_transport", ("logistics", "supply", "transport", "truck", "cargo")),
    ("ifv", ("ifv", "bmp", "bradley", "marder", "warrior")),
    ("apc", ("apc", "btr", "m113", "stryker", "boxer")),
    ("tank", ("tank", "mbt", "leopard", "abrams", "challenger", "t72", "t80", "t90")),
    ("infantry", ("infantry", "rifle", "grenadier", "marine", "airborne", "paratrooper")),
)

STOP_TOKENS = {
    "unit", "units", "squad", "team", "group", "section", "platoon", "company",
    "vehicle", "crew", "member", "default", "standard", "generic", "mp", "conquest",
    "early", "mid", "late", "modern", "legacy", "reserve", "support", "unknown",
    "nato", "ukr", "rusa", "prc", "2022s", "1980s", "1981", "1985",
}
for _aliases in NATION_ALIASES.values():
    STOP_TOKENS.update(_aliases)
for _category, _hints in CATEGORY_HINTS:
    STOP_TOKENS.add(_category)
    STOP_TOKENS.update(_hints)


@dataclass(frozen=True, slots=True)
class AuditLayer:
    priority: int
    root_name: str
    name: str
    role: str

    def to_dict(self) -> dict:
        return {
            "priority": self.priority,
            "root_name": self.root_name,
            "name": self.name,
            "role": self.role,
        }


class UnitPoolAuditor:
    def __init__(self, resource_stack: Iterable[str | Path]) -> None:
        self.roots = normalize_stack(resource_stack)
        if not self.roots:
            raise ValueError("Unit-pool audit requires at least one resource stack layer")
        for root in self.roots:
            if not root.is_dir():
                raise FileNotFoundError(f"Stack layer does not exist: {root}")
        self.layers = [_identify_layer(root, index) for index, root in enumerate(self.roots)]
        self._breed_index: dict[str, tuple[Path, int]] | None = None

    def run(self) -> tuple[dict, str, dict]:
        catalog = CodeXCatalogScanner().scan_stack(self.roots)
        rows = [self._audit_unit(unit) for unit in _raw_units(catalog)]
        rows.sort(key=lambda row: (row["inferred_nation"], row["unit_name"]))
        actors = self._actor_summaries(rows)
        payload = {
            "schema": "gates-of-codex.unit-pool-audit",
            "schema_version": AUDIT_SCHEMA_VERSION,
            "stack_signature": catalog.signature,
            "source_layers": [layer.to_dict() for layer in self.layers],
            "row_count": len(rows),
            "rows": rows,
            "actors": actors,
        }
        unclassified = self._unclassified_tokens(rows, catalog.signature)
        return payload, render_unit_pool_summary(payload), unclassified

    def write(
        self,
        output: str | Path,
        summary: str | Path,
        unclassified: str | Path,
    ) -> dict:
        payload, markdown, token_payload = self.run()
        _write_json(output, payload)
        summary_path = Path(summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(markdown, encoding="utf-8")
        _write_json(unclassified, token_payload)
        return payload

    def _audit_unit(self, unit: UnitDefinition) -> dict:
        provenance = self._provenance(unit)
        nation = _infer_nation(unit)
        loadouts = [
            self._breed_loadout(breed, unit.side, unit.period, count)
            for breed, count in sorted(unit.members.items())
        ]
        loadout_complete = all(item["complete"] for item in loadouts) if loadouts else True
        category = _audit_category(unit)
        notes: list[str] = []
        if not unit.materializable:
            notes.append("no parsed human members or vehicles")
        if unit.members and not loadout_complete:
            notes.append("one or more human breeds lack an emittable primary weapon/ammo loadout")
        if provenance["content_role"] == "legacy_reserve":
            notes.append("West81-derived reserve/legacy content")
        if nation["method"] == "conflicting_evidence":
            notes.append("conflicting national evidence retained as unknown")
        if nation["method"] == "tactical_side_only":
            notes.append("no national evidence beyond tactical side")
        return {
            "unit_name": unit.name,
            "source_layer": provenance["source_layer"],
            "source_files": provenance["source_files"],
            "source_layers": provenance["source_layers"],
            "overlay_priority": provenance["overlay_priority"],
            "content_role": provenance["content_role"],
            "tactical_side": unit.side,
            "inferred_nation": nation["nation"],
            "inference_method": nation["method"],
            "inference_tokens": nation["tokens"],
            "inference_evidence": nation["evidence"],
            "conflicting_nations": nation["conflicts"],
            "period": unit.period,
            "category": category,
            "catalog_category": unit.category,
            "type_tags": sorted(unit.type_tags),
            "doctrine": unit.doctrine,
            "doctrine_cost": unit.doctrine_cost,
            "breeds": sorted(unit.members),
            "breed_counts": dict(sorted(unit.members.items())),
            "human_loadouts": loadouts,
            "vehicles": sorted(unit.vehicles),
            "actions": sorted(unit.actions),
            "materializable": unit.materializable,
            "human_materializable": bool(unit.members),
            "vehicle_materializable": bool(unit.vehicles),
            "loadout_complete": loadout_complete,
            "confidence": nation["confidence"],
            "notes": notes,
        }

    def _provenance(self, unit: UnitDefinition) -> dict:
        entries: list[dict] = []
        for source in sorted(unit.source_files, key=_source_sort_key):
            priority, relative = _parse_source(source)
            layer = self.layers[priority] if 0 <= priority < len(self.layers) else AuditLayer(
                priority=priority,
                root_name="unknown",
                name="unknown",
                role="unknown",
            )
            entries.append({
                "priority": priority,
                "layer": layer.name,
                "role": layer.role,
                "path": relative,
            })
        winning = max(entries, key=lambda item: (item["priority"], item["path"])) if entries else {
            "priority": -1,
            "layer": "unknown",
            "role": "unknown",
            "path": "",
        }
        roles = {entry["role"] for entry in entries}
        if "modern" in roles:
            content_role = "modern"
        elif "legacy_reserve" in roles:
            content_role = "legacy_reserve"
        elif "overlay" in roles:
            content_role = "overlay_only"
        else:
            content_role = "unknown"
        return {
            "source_layer": winning["layer"],
            "source_files": [entry["path"] for entry in entries],
            "source_layers": entries,
            "overlay_priority": winning["priority"],
            "content_role": content_role,
        }

    def _breed_loadout(self, breed: str, side: str, period: str, count: int) -> dict:
        resolved = self._resolve_breed(breed, side, period)
        if resolved is None:
            return {
                "breed": breed,
                "count": count,
                "resolved": False,
                "source_layer": "",
                "source_path": "",
                "primary_weapons": [],
                "ammunition": [],
                "complete": False,
                "error": "breed definition not found in configured stack",
            }
        path, priority = resolved
        try:
            items = parse_breed_inventory(path.read_text(encoding="utf-8-sig", errors="replace"))
            weapons = sorted({item.name for item in items if _is_primary_weapon(item)})
            ammunition = sorted({item.name for item in items if _is_ammunition(item)})
            error = ""
        except (OSError, ValueError) as exc:
            weapons = []
            ammunition = []
            error = str(exc)
        layer = self.layers[priority]
        return {
            "breed": breed,
            "count": count,
            "resolved": True,
            "source_layer": layer.name,
            "source_path": path.relative_to(resource_root(self.roots[priority])).as_posix(),
            "primary_weapons": weapons,
            "ammunition": ammunition,
            "complete": bool(weapons and ammunition and not error),
            "error": error,
        }

    def _resolve_breed(self, breed: str, side: str, period: str) -> tuple[Path, int] | None:
        for priority in range(len(self.roots) - 1, -1, -1):
            resources = resource_root(self.roots[priority])
            candidates = (
                resources / f"set/breed/mp/{side}/{period}/{breed}.set",
                resources / f"set/breed/mp/{side}/{breed}.set",
                resources / f"set/breed/mp/{period}/{side}/{breed}.set",
                resources / f"set/breed/{breed}.set",
            )
            for candidate in candidates:
                if candidate.is_file():
                    return candidate, priority
        self._ensure_breed_index()
        assert self._breed_index is not None
        return self._breed_index.get(breed.lower())

    def _ensure_breed_index(self) -> None:
        if self._breed_index is not None:
            return
        values: dict[str, tuple[Path, int]] = {}
        for priority in range(len(self.roots) - 1, -1, -1):
            breed_root = resource_root(self.roots[priority]) / "set/breed"
            if not breed_root.is_dir():
                continue
            for path in sorted(breed_root.rglob("*.set")):
                values.setdefault(path.stem.lower(), (path, priority))
        self._breed_index = values

    def _actor_summaries(self, rows: list[dict]) -> list[dict]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["inferred_nation"]].append(row)
        return [self._actor_summary(actor, grouped[actor]) for actor in sorted(grouped)]

    @staticmethod
    def _actor_summary(actor: str, rows: list[dict]) -> dict:
        materializable = [row for row in rows if row["materializable"]]
        modern = [row for row in materializable if row["content_role"] == "modern"]
        legacy = [row for row in materializable if row["content_role"] == "legacy_reserve"]
        categories = Counter(row["category"] for row in materializable)
        periods = Counter(row["period"] for row in materializable)
        loadout_rows = [row for row in materializable if row["human_materializable"]]
        complete_loadouts = [row for row in loadout_rows if row["loadout_complete"]]
        capabilities = {
            "infantry_family": categories["infantry"] > 0,
            "crews_support": any(
                row["human_materializable"] and (
                    row["vehicle_materializable"]
                    or row["category"] in {"engineering", "logistics_transport", "artillery", "air_defense"}
                    or "crew" in _normalized_text(row["unit_name"])
                    or "support" in _normalized_text(row["unit_name"])
                )
                for row in materializable
            ),
            "transport_mechanized": any(categories[key] > 0 for key in ("ifv", "apc", "logistics_transport")),
            "armor_or_anti_armor": categories["tank"] > 0 or categories["anti_armor"] > 0,
            "air_defense": categories["air_defense"] > 0,
            "artillery_indirect": categories["artillery"] > 0,
            "valid_human_loadouts": bool(loadout_rows) and len(loadout_rows) == len(complete_loadouts),
            "meaningful_variety": len(modern) >= FULL_PLAYABLE_MINIMUM,
        }
        gaps = [name for name, present in capabilities.items() if not present]
        recommendation = _recommend_actor(actor, materializable, modern, legacy, capabilities)
        return {
            "actor": actor,
            "tactical_sides": sorted({row["tactical_side"] for row in rows}),
            "raw_unit_count": len(rows),
            "materializable_unit_count": len(materializable),
            "modern_materializable_count": len(modern),
            "legacy_reserve_materializable_count": len(legacy),
            "complete_loadout_count": len(complete_loadouts),
            "human_unit_count": len(loadout_rows),
            "categories": dict(sorted(categories.items())),
            "periods": dict(sorted(periods.items())),
            "source_layers": sorted({entry["layer"] for row in rows for entry in row["source_layers"]}),
            "capabilities": capabilities,
            "missing_categories": gaps,
            "recommendation": recommendation,
        }

    @staticmethod
    def _unclassified_tokens(rows: list[dict], signature: str) -> dict:
        units_by_token: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            if row["inference_method"] not in {"tactical_side_only", "unknown", "conflicting_evidence"}:
                continue
            values = [row["unit_name"], *row["breeds"], *row["vehicles"]]
            tokens = set()
            for value in values:
                tokens.update(_tokens(value))
            for token in tokens:
                if len(token) < 3 or token.isdigit() or token in STOP_TOKENS:
                    continue
                units_by_token[token].add(row["unit_name"])
        token_rows = [
            {"token": token, "count": len(unit_names), "unit_names": sorted(unit_names)}
            for token, unit_names in units_by_token.items()
        ]
        token_rows.sort(key=lambda item: (-item["count"], item["token"]))
        return {
            "schema": "gates-of-codex.unclassified-unit-tokens",
            "schema_version": AUDIT_SCHEMA_VERSION,
            "stack_signature": signature,
            "tokens": token_rows,
        }


def audit_unit_pools(
    resource_stack: Iterable[str | Path],
    *,
    output: str | Path,
    summary: str | Path,
    unclassified: str | Path,
) -> dict:
    return UnitPoolAuditor(resource_stack).write(output, summary, unclassified)


def render_unit_pool_summary(payload: dict) -> str:
    lines = [
        "# Code:X and West81 national unit-pool audit",
        "",
        "> Audit recommendations only. This report does not change campaign factions, actors, ownership, or GoH tactical sides.",
        "",
        f"Stack signature: `{payload['stack_signature']}`",
        "",
        "## Source layers",
        "",
        "| Priority | Layer | Role | Root |",
        "|---:|---|---|---|",
    ]
    for layer in payload["source_layers"]:
        lines.append(f"| {layer['priority']} | {layer['name']} | {layer['role']} | `{layer['root_name']}` |")
    lines.extend([
        "",
        "## Actor decision table",
        "",
        "| Actor / pool | Tactical side | Raw | Materializable | Modern | Legacy | Complete loadouts | Recommendation |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for actor in payload["actors"]:
        lines.append(
            "| {actor} | {side} | {raw} | {materializable} | {modern} | {legacy} | {complete} | `{recommendation}` |".format(
                actor=actor["actor"],
                side=", ".join(actor["tactical_sides"]),
                raw=actor["raw_unit_count"],
                materializable=actor["materializable_unit_count"],
                modern=actor["modern_materializable_count"],
                legacy=actor["legacy_reserve_materializable_count"],
                complete=actor["complete_loadout_count"],
                recommendation=actor["recommendation"],
            )
        )
    for actor in payload["actors"]:
        lines.extend([
            "",
            f"### {actor['actor']}",
            "",
            f"- Tactical sides: {', '.join(actor['tactical_sides']) or 'none'}",
            f"- Periods: {_format_counts(actor['periods'])}",
            f"- Categories: {_format_counts(actor['categories'])}",
            f"- Source layers: {', '.join(actor['source_layers']) or 'unknown'}",
            f"- Missing playable-threshold capabilities: {', '.join(actor['missing_categories']) or 'none'}",
            f"- Recommendation: `{actor['recommendation']}`",
        ])
    lines.extend([
        "",
        "## Interpretation rules",
        "",
        "- `tactical_side` is preserved independently from national inference.",
        "- West81-only definitions are reserve/legacy evidence, not modern national coverage.",
        "- Conflicting or low-confidence national evidence remains `unknown` or a generic tactical pool.",
        "- Human loadout completeness requires a resolved breed with both a primary weapon and ammunition.",
        "- The fully playable recommendation requires every capability listed by issue #45 plus at least six modern materializable rows.",
        "",
    ])
    return "\n".join(lines)


def _raw_units(catalog: CodeXCatalog) -> list[UnitDefinition]:
    values = catalog.units.raw_values() if hasattr(catalog.units, "raw_values") else catalog.units.values()
    return sorted(values, key=lambda unit: unit.name)


def _identify_layer(root: Path, priority: int) -> AuditLayer:
    text = str(root).lower()
    mod_info = root / "mod.info"
    if mod_info.is_file():
        text += "\n" + mod_info.read_text(encoding="utf-8-sig", errors="replace").lower()
    if "2897299509" in text or "west81" in text or "west 81" in text:
        return AuditLayer(priority, root.name, "West81", "legacy_reserve")
    if "3636883799" in text or "ai overhaul" in text or "conquest ai overhaul" in text:
        return AuditLayer(priority, root.name, "Code:X AI Overhaul", "overlay")
    if "3700832981" in text or "gates-of-code-x" in text or "gates of codex" in text:
        return AuditLayer(priority, root.name, "Gates of CodeX", "overlay")
    if "3261086933" in text or "code:x" in text or "codex" in text:
        return AuditLayer(priority, root.name, "Code:X", "modern")
    return AuditLayer(priority, root.name, root.name, "unknown")


def _infer_nation(unit: UnitDefinition) -> dict:
    evidence_sources = [
        ("unit_name", re.sub(r"\((?:nato|ukr|rusa|prc)\)$", "", unit.name, flags=re.I), 4),
        *[("breed", breed, 3) for breed in sorted(unit.members)],
        *[("vehicle", vehicle, 2) for vehicle in sorted(unit.vehicles)],
        *[("source", _parse_source(source)[1], 1) for source in unit.source_files],
        ("doctrine", unit.doctrine, 1),
        *[("type_tag", tag, 1) for tag in unit.type_tags],
    ]
    scores: Counter[str] = Counter()
    evidence: list[dict] = []
    tokens_found: set[str] = set()
    for field, value, weight in evidence_sources:
        normalized = _normalized_text(value)
        for nation, aliases in NATION_ALIASES.items():
            for alias in aliases:
                normalized_alias = _normalized_text(alias)
                if _contains_alias(normalized, normalized_alias):
                    scores[nation] += weight
                    tokens_found.add(alias)
                    evidence.append({"field": field, "value": value, "token": alias, "nation": nation, "weight": weight})
                    break
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    conflicts = [nation for nation, score in ranked[1:] if score >= 3]
    if ranked and conflicts:
        return {
            "nation": "unknown",
            "method": "conflicting_evidence",
            "confidence": "conflict",
            "tokens": sorted(tokens_found),
            "evidence": evidence,
            "conflicts": [ranked[0][0], *conflicts],
        }
    if ranked:
        nation, score = ranked[0]
        return {
            "nation": nation,
            "method": "alias_evidence",
            "confidence": "high" if score >= 4 else "medium",
            "tokens": sorted(tokens_found),
            "evidence": evidence,
            "conflicts": [],
        }
    if unit.side == "prc":
        return _side_inference("prc", "high", unit.side)
    if unit.side == "ukr":
        return _side_inference("ukraine", "high", unit.side)
    if unit.side in {"nato", "rusa"}:
        return _side_inference(f"generic_{unit.side}", "low", unit.side)
    return {
        "nation": "unknown",
        "method": "unknown",
        "confidence": "low",
        "tokens": [],
        "evidence": [],
        "conflicts": [],
    }


def _side_inference(nation: str, confidence: str, side: str) -> dict:
    return {
        "nation": nation,
        "method": "tactical_side_only",
        "confidence": confidence,
        "tokens": [side],
        "evidence": [{"field": "tactical_side", "value": side, "token": side, "nation": nation, "weight": 0}],
        "conflicts": [],
    }


def _audit_category(unit: UnitDefinition) -> str:
    text = _normalized_text(" ".join([
        unit.name,
        unit.category,
        unit.doctrine,
        *unit.type_tags,
        *unit.members,
        *unit.vehicles,
    ]))
    for category, hints in CATEGORY_HINTS:
        if any(_contains_alias(text, _normalized_text(hint)) for hint in hints):
            return category
    if unit.members:
        return "infantry"
    if unit.vehicles:
        return "vehicle"
    return unit.category or "unknown"


def _recommend_actor(
    actor: str,
    materializable: list[dict],
    modern: list[dict],
    legacy: list[dict],
    capabilities: dict[str, bool],
) -> str:
    if modern and all(capabilities.values()):
        return "full_playable_pool"
    core = sum(
        1
        for key in ("infantry_family", "transport_mechanized", "armor_or_anti_armor", "air_defense", "artillery_indirect")
        if capabilities[key]
    )
    if len(modern) >= 3 and capabilities["infantry_family"] and core >= 3:
        return "playable_with_coalition_fallback"
    if materializable and (legacy or actor in {"dprk", "soviet_legacy", "east_germany"}):
        return "reserve_or_auxiliary_only"
    if materializable:
        return "diplomatic_or_garrison_actor_only"
    return "insufficient_content"


def _is_primary_weapon(item: BreedInventoryItem) -> bool:
    return bool(item.filled and item.kind not in {"ammo", "grenade"})


def _is_ammunition(item: BreedInventoryItem) -> bool:
    return item.kind == "ammo" or bool(item.filling)


def _normalized_text(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _contains_alias(text: str, alias: str) -> bool:
    if not text or not alias:
        return False
    return bool(re.search(rf"(?:^|_){re.escape(alias)}(?:_|$)", text))


def _tokens(value: str) -> set[str]:
    return {token for token in _normalized_text(value).split("_") if token}


def _parse_source(source: str) -> tuple[int, str]:
    match = re.match(r"^(\d+):[^/]+/(.*)$", source)
    if not match:
        return -1, source
    return int(match.group(1)), match.group(2)


def _source_sort_key(source: str) -> tuple[int, str]:
    priority, path = _parse_source(source)
    return priority, path


def _format_counts(values: dict) -> str:
    return ", ".join(f"{key}={values[key]}" for key in sorted(values)) or "none"


def _write_json(path: str | Path, payload: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
