from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    BattalionType,
    CampaignState,
    Commander,
    CommanderStatus,
    Faction,
    FactionState,
    ForceEchelon,
    Formation,
    StrategicFormation,
)


BOOTSTRAP_METADATA_KEY = "earth3_bootstrap"
BOOTSTRAP_ID = "earth3_v1_campaign_bootstrap"
BOOTSTRAP_SCHEMA_VERSION = 1
MOVEMENT_AUTHORITY = "p3_required"

_FIXED_FILES = (
    "alliances.json",
    "bootstrap.json",
    "commanders.json",
    "deployment_zones.json",
    "factions.json",
    "formations.json",
    "objectives.json",
    "ownership.json",
    "province_mappings.json",
    "sites.json",
    "tactical_maps.json",
)

_APPROVED_RAW_FILE_SHA256 = {
    "alliances.json": "a07d869258d6f7b35bfeb5a5d5842bd3522b69d49f606357eb32480ea4754ff4",
    "bootstrap.json": "7ee4af8825a8acbf1813801f3eef7909b0e7e0e0dd0b68f0b25eb4cf642e108a",
    "commanders.json": "2413fe95a155a8361a6eaca3b33cc431a65413e54352d70acb46ad8ee4f79acf",
    "deployment_zones.json": "f6889dffd996dc1f3a08b1c9259ff60bdd9ffe385baccfa8a6ae1ebac75f47b3",
    "factions.json": "2be1b40bfa69c1f43f123f6156a8b35f5d23ca15cc4386663be7392e0bb480a8",
    "formations.json": "e8ae502e05ea30233d52257a3cfba7509250601015c2ea00f1acdbe32c63b31c",
    "objectives.json": "b399d922e61bbfd14977b2f1a7dd660a96ca567cfb321ead89111483fded2d54",
    "ownership.json": "c7439886d60f8ba7ae138c403f62b7b34777211831a92d7bb346cb39dfd9d7df",
    "province_mappings.json": "d7788110f5a57343c7007f2f9ec6cb9f0e9e334e63dd4a6881e18ab542c6bb16",
    "sites.json": "7fbfa2bd7fd40f97f69b5b515bb77cb7145d1299153a2263d79443692f4c2ef3",
    "tactical_maps.json": "cbf2a1023b080449a12329f17bba6d299e784a3734f7f47809ba683add713259",
}

_FORBIDDEN_DATA_KEYS = frozenset(
    {
        "adjacency",
        "border_segments",
        "dataset_identifier",
        "dataset_sha256",
        "edges",
        "geometry",
        "geometry_sha256",
        "manifest_identifier",
        "manifest_sha256",
        "neighbors",
        "operational_graph",
        "operational_nodes",
        "polygon_dataset",
        "production_asset_version",
        "production_authority",
        "route_node_id",
        "routes",
        "triangles",
        "vertices",
    }
)

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Earth3BootstrapError(ValueError):
    """The fixed Earth3 P2 scenario bundle or state contract is invalid."""


@dataclass(frozen=True, slots=True)
class CapturedBootstrapJson:
    path: Path
    raw_bytes: bytes
    raw_sha256: str
    parsed_json: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Earth3BootstrapBundle:
    root: Path
    documents: dict[str, dict[str, Any]]
    raw_sha256: dict[str, str]
    raw_bundle_sha256: str
    logical_bundle_sha256: str
    footprint_sha256: str
    footprint: tuple[str, ...]


def _bootstrap_data_root() -> Path:
    return Path(os.path.abspath(Path(__file__).parent / "data" / "earth3_v1"))


def _is_symlink_or_reparse(path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    attributes = getattr(path_stat, "st_file_attributes", None)
    return bool(
        attributes is not None
        and attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _same_identity(before: os.stat_result, after: os.stat_result) -> bool:
    return (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)


def _canonical_data_root(root: Path) -> Path:
    absolute = Path(os.path.abspath(root))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            raise Earth3BootstrapError(f"Earth3 P2 data root missing: {absolute}") from exc
        if _is_symlink_or_reparse(current_stat):
            raise Earth3BootstrapError(
                f"Earth3 P2 data root contains a symlink or reparse point: {current}"
            )
    try:
        root_stat = os.lstat(absolute)
        canonical = absolute.resolve(strict=True)
        canonical_stat = os.lstat(canonical)
    except OSError as exc:
        raise Earth3BootstrapError(f"Earth3 P2 data root is not canonical: {absolute}") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or not stat.S_ISDIR(canonical_stat.st_mode):
        raise Earth3BootstrapError(f"Earth3 P2 data root is not a directory: {absolute}")
    if _is_symlink_or_reparse(root_stat) or _is_symlink_or_reparse(canonical_stat):
        raise Earth3BootstrapError(f"Earth3 P2 data root is a symlink or reparse point: {absolute}")
    if not _same_identity(root_stat, canonical_stat):
        raise Earth3BootstrapError(f"Earth3 P2 data root is path-substituted: {absolute}")
    return canonical


def _strict_json_object(raw_bytes: bytes, *, label: str) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise Earth3BootstrapError(f"{label} contains duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        parsed = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=pairs_hook)
    except Earth3BootstrapError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Earth3BootstrapError(f"{label} is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise Earth3BootstrapError(f"{label} must be a JSON object")
    return parsed


def _read_fixed_bootstrap_json(root: Path, filename: str) -> CapturedBootstrapJson:
    canonical_root = _canonical_data_root(root)
    relative = Path(filename)
    if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts:
        raise Earth3BootstrapError(f"P2 data path is not a fixed filename: {filename}")
    path = canonical_root / relative
    try:
        root_before = os.lstat(canonical_root)
        before = os.lstat(path)
    except OSError as exc:
        raise Earth3BootstrapError(f"Earth3 P2 data file missing: {filename}") from exc
    if _is_symlink_or_reparse(before):
        raise Earth3BootstrapError(f"Earth3 P2 data file is a symlink or reparse point: {filename}")
    if not stat.S_ISREG(before.st_mode):
        raise Earth3BootstrapError(f"Earth3 P2 data file is not regular: {filename}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(canonical_root)
        resolved_stat = os.lstat(resolved)
    except (OSError, ValueError) as exc:
        raise Earth3BootstrapError(f"Earth3 P2 data file escapes its root: {filename}") from exc
    if _is_symlink_or_reparse(resolved_stat) or not _same_identity(before, resolved_stat):
        raise Earth3BootstrapError(f"Earth3 P2 data file is path-substituted: {filename}")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _same_identity(before, opened):
                raise Earth3BootstrapError(f"Earth3 P2 data file changed while opening: {filename}")
            raw_bytes = stream.read()
    except Earth3BootstrapError:
        raise
    except OSError as exc:
        raise Earth3BootstrapError(f"Earth3 P2 data file cannot be read: {filename}") from exc

    try:
        root_after = os.lstat(canonical_root)
        after = os.lstat(path)
        after_resolved = path.resolve(strict=True)
        after_resolved.relative_to(canonical_root)
    except (OSError, ValueError) as exc:
        raise Earth3BootstrapError(f"Earth3 P2 data path changed while reading: {filename}") from exc
    if (
        _is_symlink_or_reparse(root_after)
        or _is_symlink_or_reparse(after)
        or not _same_identity(root_before, root_after)
        or not _same_identity(before, after)
        or after_resolved != resolved
    ):
        raise Earth3BootstrapError(f"Earth3 P2 data path changed while reading: {filename}")

    return CapturedBootstrapJson(
        path=path,
        raw_bytes=raw_bytes,
        raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        parsed_json=_strict_json_object(raw_bytes, label=filename),
    )


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_object_fields(
    value: Any,
    required: set[str],
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Earth3BootstrapError(f"{label} must be an object")
    actual = set(value)
    if actual != required:
        raise Earth3BootstrapError(
            f"{label} fields mismatch: missing={sorted(required - actual)} "
            f"unexpected={sorted(actual - required)}"
        )
    return value


def _require_rows(value: Any, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise Earth3BootstrapError(f"{label} must be an array of objects")
    return value


def _reject_forbidden_keys(value: Any, *, path: str = "bundle") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_DATA_KEYS:
                raise Earth3BootstrapError(f"P2 data forbids {key} at {path}.{key}")
            _reject_forbidden_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, path=f"{path}[{index}]")


def _require_unique(rows: list[dict[str, Any]], key: str, *, label: str) -> None:
    values = [str(row.get(key, "")) for row in rows]
    if any(not value for value in values) or len(values) != len(set(values)):
        raise Earth3BootstrapError(f"{label} must contain unique non-empty {key} values")


def _validate_document_schemas(documents: Mapping[str, dict[str, Any]]) -> None:
    for filename, document in documents.items():
        _reject_forbidden_keys(document, path=filename)
        version = document.get("schema_version")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != BOOTSTRAP_SCHEMA_VERSION
        ):
            raise Earth3BootstrapError(f"{filename} has unsupported schema_version")

    _require_object_fields(
        documents["bootstrap.json"],
        {
            "bootstrap_id", "campaign_name", "content_note", "current_actor_id",
            "movement_authority", "operational_maneuver_enabled", "schema_version",
            "selected_actor_id", "turn_number",
        },
        label="bootstrap.json",
    )
    mapping_doc = _require_object_fields(
        documents["province_mappings.json"],
        {"justification", "location_authority", "mappings", "schema_version", "stable_id_authority"},
        label="province_mappings.json",
    )
    for index, row in enumerate(_require_rows(mapping_doc["mappings"], label="province mappings")):
        _require_object_fields(
            row,
            {"display_name", "location_key", "province_id", "source_province_id"},
            label=f"province mapping {index}",
        )

    faction_doc = _require_object_fields(
        documents["factions.json"],
        {"active_actors", "dormant_prc_note", "schema_version", "tactical_factions"},
        label="factions.json",
    )
    for index, row in enumerate(_require_rows(faction_doc["tactical_factions"], label="tactical factions")):
        _require_object_fields(
            row,
            {"compatibility_role", "faction_id", "is_human_controlled", "resources"},
            label=f"tactical faction {index}",
        )
    for index, row in enumerate(_require_rows(faction_doc["active_actors"], label="active actors")):
        _require_object_fields(
            row,
            {"actor_id", "manifest_display_name", "resources", "tactical_side"},
            label=f"active actor {index}",
        )

    row_contracts = {
        "alliances.json": ("alliances", {"alliance_id", "display_name", "factions", "notes"}),
        "ownership.json": ("ownership", {"actor_id", "faction", "province_id"}),
        "formations.json": (
            "formations",
            {
                "actor_id", "commander_id", "display_name", "faction", "formation_id",
                "is_player_controlled", "nation", "province_id", "roster",
            },
        ),
        "commanders.json": ("commanders", {"commander_id", "display_name", "formation_id", "rank"}),
        "sites.json": (
            "sites",
            {"display_name", "kind", "owner_actor_id", "province_id", "site_id", "supply_hub_intent"},
        ),
        "objectives.json": (
            "objectives",
            {
                "coalition", "completed", "display_name", "id", "kind",
                "owner_id", "owner_type", "primary", "progress", "required",
                "reward_each", "rewarded", "targets",
            },
        ),
        "deployment_zones.json": ("deployment_zones", {"actor_id", "province_ids"}),
        "tactical_maps.json": ("preferences", {"map_id", "province_id"}),
    }
    root_extras = {
        "commanders.json": {"content_judgment"},
        "sites.json": {"connectivity_authority"},
        "objectives.json": {"capitals"},
    }
    for filename, (array_key, row_fields) in row_contracts.items():
        document = _require_object_fields(
            documents[filename],
            {"schema_version", array_key} | root_extras.get(filename, set()),
            label=filename,
        )
        for index, row in enumerate(_require_rows(document[array_key], label=f"{filename}:{array_key}")):
            _require_object_fields(row, row_fields, label=f"{filename}:{array_key}[{index}]")
            if filename == "formations.json":
                roster = _require_rows(row["roster"], label=f"formation {row['formation_id']} roster")
                for roster_index, roster_row in enumerate(roster):
                    _require_object_fields(
                        roster_row,
                        {"category", "quantity"},
                        label=f"formation {row['formation_id']} roster[{roster_index}]",
                    )


def _validate_bundle_content(
    documents: Mapping[str, dict[str, Any]],
    *,
    authority_root: str | Path | None,
) -> tuple[str, ...]:
    from .earth3.locations import REQUIRED_LOCATIONS
    from .earth3_campaign import load_earth3_authority
    from .faction_wiring_manifest import load_faction_manifest

    bootstrap = documents["bootstrap.json"]
    if (
        bootstrap["bootstrap_id"] != BOOTSTRAP_ID
        or bootstrap["selected_actor_id"] != "usa"
        or bootstrap["current_actor_id"] != "usa"
        or isinstance(bootstrap["turn_number"], bool)
        or bootstrap["turn_number"] != 1
        or bootstrap["movement_authority"] != MOVEMENT_AUTHORITY
        or bootstrap["operational_maneuver_enabled"] is not False
        or not isinstance(bootstrap["campaign_name"], str)
        or not bootstrap["campaign_name"].strip()
        or not isinstance(bootstrap["content_note"], str)
        or not bootstrap["content_note"].strip()
    ):
        raise Earth3BootstrapError("bootstrap.json does not declare the approved P2 opening contract")

    mapping_document = documents["province_mappings.json"]
    if (
        mapping_document["location_authority"]
        != "src/gates_of_codex/earth3/locations.py#REQUIRED_LOCATIONS"
        or mapping_document["stable_id_authority"]
        != "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json#provinces[id,source_id]"
        or not isinstance(mapping_document["justification"], str)
        or not mapping_document["justification"].strip()
    ):
        raise Earth3BootstrapError("province mapping evidence authority is not exact")
    mappings = mapping_document["mappings"]
    _require_unique(mappings, "province_id", label="province mappings")
    _require_unique(mappings, "source_province_id", label="province mappings")
    _require_unique(mappings, "location_key", label="province mappings")
    locations = {row.key: row for row in REQUIRED_LOCATIONS}
    earth3 = load_earth3_authority(authority_root)
    by_source = {int(row["source_id"]): row for row in earth3.provinces}
    footprint: list[str] = []
    for row in mappings:
        key = str(row["location_key"])
        source_id = row["source_province_id"]
        province_id = str(row["province_id"])
        if any(
            not isinstance(row[field], str) or not row[field].strip()
            for field in ("display_name", "location_key", "province_id")
        ):
            raise Earth3BootstrapError("province mapping string fields must be non-empty")
        if isinstance(source_id, bool) or not isinstance(source_id, int):
            raise Earth3BootstrapError(f"province mapping {key} source_province_id must be an int")
        location = locations.get(key)
        if location is None or location.source_province_id != source_id or not location.must_include:
            raise Earth3BootstrapError(f"province mapping {key} is not proven by committed location authority")
        production = by_source.get(source_id)
        if production is None or str(production["id"]) != province_id:
            raise Earth3BootstrapError(f"province mapping {key} does not match the production dataset")
        if bool(production["is_water"]):
            raise Earth3BootstrapError(f"province mapping {key} resolves to water")
        footprint.append(province_id)
    footprint = sorted(footprint)

    manifest = load_faction_manifest()
    manifest_actors = {row["actor_id"]: row for row in manifest["actors"]}
    active_rows = documents["factions.json"]["active_actors"]
    _require_unique(active_rows, "actor_id", label="active actors")
    active = {str(row["actor_id"]): row for row in active_rows}
    if set(active) != {"usa", "deu", "pol", "ukr", "rus"}:
        raise Earth3BootstrapError("P2 active actor set must be usa/deu/pol/ukr/rus")
    for actor_id, row in active.items():
        actor = manifest_actors.get(actor_id)
        if actor is None:
            raise Earth3BootstrapError(f"P2 actor is not manifest-defined: {actor_id}")
        if row["manifest_display_name"] != actor["display_name"] or row["tactical_side"] != actor["tactical_side"]:
            raise Earth3BootstrapError(f"P2 actor identity mismatch: {actor_id}")
        if isinstance(row["resources"], bool) or not isinstance(row["resources"], int) or row["resources"] < 0:
            raise Earth3BootstrapError(f"P2 actor resources invalid: {actor_id}")

    tactical = documents["factions.json"]["tactical_factions"]
    _require_unique(tactical, "faction_id", label="tactical factions")
    if {row["faction_id"] for row in tactical} != {"nato", "ukr", "rusa", "prc"}:
        raise Earth3BootstrapError("P2 tactical compatibility faction set is incomplete")
    if [row["faction_id"] for row in tactical if row["is_human_controlled"]] != ["nato"]:
        raise Earth3BootstrapError("P2 must have exactly one human tactical faction")
    for row in tactical:
        if not isinstance(row["is_human_controlled"], bool):
            raise Earth3BootstrapError(f"P2 tactical human flag invalid: {row['faction_id']}")
        if (
            isinstance(row["resources"], bool)
            or not isinstance(row["resources"], int)
            or row["resources"] != 0
        ):
            raise Earth3BootstrapError(f"P2 tactical compatibility resources invalid: {row['faction_id']}")

    alliances = documents["alliances.json"]["alliances"]
    _require_unique(alliances, "alliance_id", label="alliances")
    alliance_factions = alliances[0]["factions"] if len(alliances) == 1 else None
    if not isinstance(alliance_factions, list):
        raise Earth3BootstrapError("P2 NATO–Ukraine alliance factions must be an array")
    if set(alliance_factions) != {"nato", "ukr"}:
        raise Earth3BootstrapError("P2 must explicitly ally NATO and Ukraine")
    if len(alliance_factions) != 2:
        raise Earth3BootstrapError("P2 NATO–Ukraine alliance shape is invalid")

    ownership = documents["ownership.json"]["ownership"]
    _require_unique(ownership, "province_id", label="ownership")
    if {row["province_id"] for row in ownership} != set(footprint):
        raise Earth3BootstrapError("P2 ownership must cover exactly the proven footprint")
    owner_by_province: dict[str, tuple[str, str]] = {}
    for row in ownership:
        actor_id = str(row["actor_id"])
        if any(not isinstance(row[field], str) for field in ("actor_id", "faction", "province_id")):
            raise Earth3BootstrapError("P2 ownership fields must be strings")
        if actor_id not in active or row["faction"] != active[actor_id]["tactical_side"]:
            raise Earth3BootstrapError(f"P2 ownership actor/faction mismatch: {row['province_id']}")
        owner_by_province[str(row["province_id"])] = (str(row["faction"]), actor_id)

    formations = documents["formations.json"]["formations"]
    _require_unique(formations, "formation_id", label="formations")
    commander_rows = documents["commanders.json"]["commanders"]
    _require_unique(commander_rows, "commander_id", label="commanders")
    commander_by_id = {str(row["commander_id"]): row for row in commander_rows}
    for row in commander_rows:
        if any(
            not isinstance(row[field], str) or not row[field].strip()
            for field in ("commander_id", "display_name", "formation_id", "rank")
        ):
            raise Earth3BootstrapError("P2 commander fields must be non-empty strings")
    for row in formations:
        province_id = str(row["province_id"])
        actor_id = str(row["actor_id"])
        if any(
            not isinstance(row[field], str) or not row[field].strip()
            for field in (
                "actor_id", "commander_id", "display_name", "faction",
                "formation_id", "nation", "province_id",
            )
        ):
            raise Earth3BootstrapError("P2 formation fields must be non-empty strings")
        if province_id not in footprint:
            raise Earth3BootstrapError(f"formation {row['formation_id']} is outside the footprint")
        if owner_by_province[province_id] != (row["faction"], actor_id):
            raise Earth3BootstrapError(f"formation {row['formation_id']} ownership mismatch")
        if not isinstance(row["is_player_controlled"], bool):
            raise Earth3BootstrapError(f"formation {row['formation_id']} player flag invalid")
        commander = commander_by_id.get(str(row["commander_id"]))
        if commander is None or commander["formation_id"] != row["formation_id"]:
            raise Earth3BootstrapError(f"formation {row['formation_id']} commander mismatch")
        roster = row["roster"]
        categories = [str(item["category"]) for item in roster]
        if not roster or len(categories) != len(set(categories)):
            raise Earth3BootstrapError(f"formation {row['formation_id']} roster categories invalid")
        for item in roster:
            if item["category"] not in {"infantry", "tank", "artillery"}:
                raise Earth3BootstrapError(f"formation {row['formation_id']} category invalid")
            if isinstance(item["quantity"], bool) or not isinstance(item["quantity"], int) or item["quantity"] < 1:
                raise Earth3BootstrapError(f"formation {row['formation_id']} quantity invalid")
    if {row["formation_id"] for row in commander_rows} != {row["formation_id"] for row in formations}:
        raise Earth3BootstrapError("P2 commanders must map one-to-one to formations")

    sites = documents["sites.json"]["sites"]
    _require_unique(sites, "site_id", label="sites")
    if documents["sites.json"]["connectivity_authority"] != "none_until_p3":
        raise Earth3BootstrapError("P2 sites must not claim connectivity before P3")
    for row in sites:
        province_id = str(row["province_id"])
        if province_id not in footprint or owner_by_province[province_id][1] != row["owner_actor_id"]:
            raise Earth3BootstrapError(f"site {row['site_id']} is outside or ownership-mismatched")
        if row["kind"] not in {"command", "depot", "objective", "port"}:
            raise Earth3BootstrapError(f"site {row['site_id']} kind is invalid")
        if not isinstance(row["supply_hub_intent"], bool):
            raise Earth3BootstrapError(f"site {row['site_id']} supply intent must be bool")

    objectives = documents["objectives.json"]["objectives"]
    _require_unique(objectives, "id", label="objectives")
    alliance_ids = {str(row["alliance_id"]) for row in alliances}
    for row in objectives:
        targets = [str(value) for value in row["targets"]]
        if not targets or len(targets) != len(set(targets)) or not set(targets) <= set(footprint):
            raise Earth3BootstrapError(f"objective {row['id']} target outside footprint")
        if row["completed"] is not False or row["rewarded"] is not False or row["progress"] != 0:
            raise Earth3BootstrapError(f"objective {row['id']} must open incomplete")
        if not isinstance(row["primary"], bool):
            raise Earth3BootstrapError(f"objective {row['id']} primary flag invalid")
        if (
            isinstance(row["progress"], bool)
            or not isinstance(row["progress"], int)
            or isinstance(row["reward_each"], bool)
            or not isinstance(row["reward_each"], int)
            or row["reward_each"] != 0
        ):
            raise Earth3BootstrapError(f"objective {row['id']} numeric fields invalid")
        if isinstance(row["required"], bool) or not isinstance(row["required"], int) or not 1 <= row["required"] <= len(targets):
            raise Earth3BootstrapError(f"objective {row['id']} required count invalid")
        if row["owner_type"] == "alliance" and row["owner_id"] not in alliance_ids:
            raise Earth3BootstrapError(f"objective {row['id']} alliance missing")
        if row["owner_type"] == "actor" and row["owner_id"] not in active:
            raise Earth3BootstrapError(f"objective {row['id']} actor missing")
        if row["owner_type"] not in {"alliance", "actor"}:
            raise Earth3BootstrapError(f"objective {row['id']} owner type invalid")
    capitals = _require_rows(
        documents["objectives.json"]["capitals"], label="strategic capitals"
    )
    _require_unique(capitals, "capital_id", label="strategic capitals")
    for index, row in enumerate(capitals):
        _require_object_fields(
            row,
            {"capital_id", "display_name", "owner_id", "owner_type", "province_id"},
            label=f"strategic capital {index}",
        )
        if str(row["province_id"]) not in footprint:
            raise Earth3BootstrapError(f"strategic capital {row['capital_id']} is outside footprint")
        if row["owner_type"] == "alliance" and row["owner_id"] not in alliance_ids:
            raise Earth3BootstrapError(f"strategic capital {row['capital_id']} alliance missing")
        if row["owner_type"] == "actor" and row["owner_id"] not in active:
            raise Earth3BootstrapError(f"strategic capital {row['capital_id']} actor missing")
        if row["owner_type"] not in {"alliance", "actor"}:
            raise Earth3BootstrapError(f"strategic capital {row['capital_id']} owner type invalid")

    zones = documents["deployment_zones.json"]["deployment_zones"]
    _require_unique(zones, "actor_id", label="deployment zones")
    if {str(row["actor_id"]) for row in zones} != set(active):
        raise Earth3BootstrapError("P2 deployment zones must be actor-scoped")
    for row in zones:
        if not isinstance(row["province_ids"], list):
            raise Earth3BootstrapError(f"deployment zone {row['actor_id']} provinces must be an array")
        provinces = [str(value) for value in row["province_ids"]]
        if not provinces or len(provinces) != len(set(provinces)) or not set(provinces) <= set(footprint):
            raise Earth3BootstrapError(f"deployment zone {row['actor_id']} is outside footprint")
        if any(owner_by_province[province][1] != row["actor_id"] for province in provinces):
            raise Earth3BootstrapError(f"deployment zone {row['actor_id']} ownership mismatch")

    preferences = documents["tactical_maps.json"]["preferences"]
    _require_unique(preferences, "province_id", label="tactical map preferences")
    if {str(row["province_id"]) for row in preferences} != set(footprint):
        raise Earth3BootstrapError("P2 tactical map preferences must cover the footprint only")
    if any(
        not isinstance(row["province_id"], str)
        or not isinstance(row["map_id"], str)
        or not row["map_id"].strip()
        for row in preferences
    ):
        raise Earth3BootstrapError("P2 tactical map preference cannot be empty")
    return tuple(footprint)


def load_earth3_bootstrap(
    *,
    authority_root: str | Path | None = None,
) -> Earth3BootstrapBundle:
    root = _canonical_data_root(_bootstrap_data_root())
    try:
        present = sorted(path.name for path in root.iterdir())
    except OSError as exc:
        raise Earth3BootstrapError("Earth3 P2 data directory cannot be enumerated") from exc
    if present != list(_FIXED_FILES):
        raise Earth3BootstrapError(
            f"unexpected bootstrap file set: expected={list(_FIXED_FILES)} got={present}"
        )
    captured = {name: _read_fixed_bootstrap_json(root, name) for name in _FIXED_FILES}
    actual_hashes = {name: captured[name].raw_sha256 for name in _FIXED_FILES}
    if set(_APPROVED_RAW_FILE_SHA256) != set(_FIXED_FILES):
        raise Earth3BootstrapError("P2 approved raw-file contract is incomplete")
    for filename in _FIXED_FILES:
        if actual_hashes[filename] != _APPROVED_RAW_FILE_SHA256[filename]:
            raise Earth3BootstrapError(
                f"{filename} raw SHA-256 mismatch: expected "
                f"{_APPROVED_RAW_FILE_SHA256[filename]}, got {actual_hashes[filename]}"
            )
    documents = {name: captured[name].parsed_json for name in _FIXED_FILES}
    _validate_document_schemas(documents)
    footprint = _validate_bundle_content(documents, authority_root=authority_root)
    return Earth3BootstrapBundle(
        root=root,
        documents=documents,
        raw_sha256=actual_hashes,
        raw_bundle_sha256=_canonical_sha256(actual_hashes),
        logical_bundle_sha256=_canonical_sha256(documents),
        footprint_sha256=_canonical_sha256(list(footprint)),
        footprint=footprint,
    )


def _normalize_source_path(value: str, layer_paths: list[str]) -> str:
    normalized = str(value).replace("\\", "/")
    for root in layer_paths:
        prefix = root.replace("\\", "/").rstrip("/")
        if prefix and normalized.casefold().startswith((prefix + "/").casefold()):
            return normalized[len(prefix) + 1 :]
    if Path(value).is_absolute():
        raise Earth3BootstrapError(f"resolved catalog contains an unscoped absolute source path: {value}")
    return normalized


def _canonicalize_resolved_catalog(payload: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        value = copy.deepcopy(dict(payload))
    except Exception as exc:
        raise Earth3BootstrapError("resolved catalog is not a materializable mapping") from exc
    raw_layers = value.get("source_layers")
    if not isinstance(raw_layers, list):
        raise Earth3BootstrapError("resolved catalog source_layers must be an array")
    layer_paths = [str(row.get("path", "")) for row in raw_layers if isinstance(row, dict)]
    from .modstack import STACK_ROLE_ORDER

    logical_layers: dict[int, str] = {}
    for row in raw_layers:
        if not isinstance(row, dict) or set(row) != {"priority", "name", "path"}:
            raise Earth3BootstrapError("resolved catalog source layer shape is invalid")
        raw_priority = row["priority"]
        if isinstance(raw_priority, bool) or not isinstance(raw_priority, int):
            raise Earth3BootstrapError("resolved catalog source layer priority must be an int")
        priority = raw_priority
        if priority in logical_layers:
            raise Earth3BootstrapError("resolved catalog contains duplicate source layer priorities")
        logical_name = (
            STACK_ROLE_ORDER[priority]
            if 0 <= priority < len(STACK_ROLE_ORDER)
            else f"layer_{priority}"
        )
        logical_layers[priority] = logical_name
        row["name"] = logical_name
        row["path"] = ""
    raw_layers.sort(key=lambda row: (row["priority"], row["name"]))
    actors = value.get("actors")
    if not isinstance(actors, list):
        raise Earth3BootstrapError("resolved catalog actors must be an array")
    from .faction_wiring_manifest import (
        _canonical_sha256 as _manifest_sha256,
        load_faction_manifest,
    )

    expected_manifest = load_faction_manifest()
    if value.get("manifest_sha256") != _manifest_sha256(expected_manifest):
        raise Earth3BootstrapError("resolved catalog manifest identity mismatch")
    if value.get("source_policy") != expected_manifest.get("source_policy"):
        raise Earth3BootstrapError("resolved catalog source policy mismatch")
    for actor in actors:
        if not isinstance(actor, dict):
            raise Earth3BootstrapError("resolved catalog actor row must be an object")
        for unit in actor.get("units", []):
            if not isinstance(unit, dict):
                raise Earth3BootstrapError("resolved catalog unit row must be an object")
            files = unit.get("source_files", [])
            unit["source_files"] = sorted(
                _normalize_source_path(str(item), layer_paths) for item in files
            )
            priority = int(unit.get("source_priority", -1))
            unit["source_layer"] = logical_layers.get(priority, f"layer_{priority}")
            for key in ("actions", "vehicles"):
                if isinstance(unit.get(key), list):
                    unit[key] = sorted(unit[key])
        for node in actor.get("research_nodes", []):
            if not isinstance(node, dict):
                raise Earth3BootstrapError("resolved catalog research row must be an object")
            source_file = str(node.get("source_file", ""))
            if source_file:
                node["source_file"] = _normalize_source_path(source_file, layer_paths)
            for key in ("prerequisites", "unlock_units"):
                if isinstance(node.get(key), list):
                    node[key] = sorted(node[key])
        actor["units"] = sorted(actor.get("units", []), key=lambda row: str(row.get("unit_name", "")))
        actor["research_nodes"] = sorted(
            actor.get("research_nodes", []), key=lambda row: str(row.get("key", ""))
        )
        for key in ("components", "missing_categories", "notes", "required_categories"):
            if isinstance(actor.get(key), list):
                actor[key] = sorted(actor[key])
    value["actors"] = sorted(actors, key=lambda row: str(row.get("actor_id", "")))
    logical = copy.deepcopy(value)
    logical.pop("stack_signature", None)
    logical.pop("wiring_signature", None)
    logical.pop("problems", None)
    identity = _canonical_sha256(logical)
    value["stack_signature"] = identity
    value["wiring_signature"] = identity
    return value, identity


def _resolved_catalog(
    *,
    resolved_catalog: Mapping[str, Any] | None,
    resource_stack: Iterable[str | Path] | None,
    stack_config: str | Path | None,
) -> tuple[dict[str, Any], str]:
    provided_stack = list(resource_stack or ())
    if resolved_catalog is not None and (provided_stack or stack_config is not None):
        raise Earth3BootstrapError("provide either resolved catalog or active stack authority, not both")
    if resolved_catalog is None:
        if stack_config is not None:
            from .modstack import load_stack_config

            if provided_stack:
                raise Earth3BootstrapError("stack_config and resource_stack cannot both be provided")
            provided_stack = load_stack_config(stack_config)
        if not provided_stack:
            raise Earth3BootstrapError("Earth3 P2 requires an active stack or resolved catalog authority")
        from .faction_wiring_compiler import FactionWiringCompiler

        resolved_catalog = FactionWiringCompiler(provided_stack).compile()
    return _canonicalize_resolved_catalog(resolved_catalog)


def _materialize_roster(
    actor: Mapping[str, Any],
    requests: list[dict[str, Any]],
) -> list[BattalionRosterEntry]:
    units = [row for row in actor.get("units", []) if row.get("materializable")]
    roster: list[BattalionRosterEntry] = []
    for request in requests:
        category = str(request["category"])
        candidates = [row for row in units if row.get("category") == category]
        if not candidates:
            raise Earth3BootstrapError(f"actor {actor.get('actor_id')} cannot materialize {category}")
        chosen = min(candidates, key=lambda row: (int(row.get("tier", 1)), str(row["unit_name"])))
        roster.append(
            BattalionRosterEntry(
                unit_name=str(chosen["unit_name"]),
                quantity=int(request["quantity"]),
                category=category,
            )
        )
    return roster


def _copy_roster(roster: list[BattalionRosterEntry]) -> list[BattalionRosterEntry]:
    return [
        BattalionRosterEntry(
            unit_name=row.unit_name,
            quantity=row.quantity,
            stage=row.stage,
            category=row.category,
            preserved_objects=list(row.preserved_objects),
        )
        for row in roster
    ]


def build_earth3_v1_campaign(
    *,
    resolved_catalog: Mapping[str, Any] | None = None,
    resource_stack: Iterable[str | Path] | None = None,
    stack_config: str | Path | None = None,
    authority_root: str | Path | None = None,
) -> CampaignState:
    bundle = load_earth3_bootstrap(authority_root=authority_root)
    catalog, catalog_identity = _resolved_catalog(
        resolved_catalog=resolved_catalog,
        resource_stack=resource_stack,
        stack_config=stack_config,
    )
    actors_by_id = {str(row["actor_id"]): row for row in catalog.get("actors", [])}
    active_actor_ids = [
        str(row["actor_id"])
        for row in bundle.documents["factions.json"]["active_actors"]
    ]
    missing = sorted(set(active_actor_ids) - set(actors_by_id))
    if missing:
        raise Earth3BootstrapError(f"resolved catalog is missing required P2 actors: {missing}")

    from .earth3_campaign import build_earth3_campaign

    state = build_earth3_campaign(authority_root)
    bootstrap = bundle.documents["bootstrap.json"]
    state.campaign_name = str(bootstrap["campaign_name"])
    state.catalog_signature = catalog_identity
    state.turn_number = int(bootstrap["turn_number"])
    state.selected_faction = Faction.NATO
    state.current_faction = Faction.NATO
    state.factions = {
        str(row["faction_id"]): FactionState(
            faction=Faction(row["faction_id"]),
            resources=int(row["resources"]),
            is_human_controlled=bool(row["is_human_controlled"]),
            is_eliminated=row["compatibility_role"] == "inherited_actor_installation_only",
        )
        for row in bundle.documents["factions.json"]["tactical_factions"]
    }
    state.alliances = {
        str(row["alliance_id"]): Alliance(
            alliance_id=str(row["alliance_id"]),
            display_name=str(row["display_name"]),
            factions=[Faction(value) for value in row["factions"]],
            notes=str(row["notes"]),
        )
        for row in bundle.documents["alliances.json"]["alliances"]
    }

    # Install the manifest actors before assigning actor-specific ownership or
    # forces. The legacy compatibility normalizer intentionally collapses a
    # tactical side to one actor and therefore must not see P2 actor ownership.
    from .strategic_actors import install_bundled_strategic_actors

    install_bundled_strategic_actors(state, selected_actor_id="usa")

    names = {
        str(row["province_id"]): str(row["display_name"])
        for row in bundle.documents["province_mappings.json"]["mappings"]
    }
    footprint = set(bundle.footprint)
    for province in state.provinces.values():
        province.metadata["scenario_actionable"] = province.province_id in footprint
        if province.province_id in names:
            province.display_name = names[province.province_id]
            province.metadata["name_is_human_readable"] = True
            province.metadata["name_source"] = "earth3_v1/province_mappings.json"
    for row in bundle.documents["ownership.json"]["ownership"]:
        province = state.provinces[str(row["province_id"])]
        province.owner = Faction(row["faction"])
        province.metadata["owner_actor_id"] = str(row["actor_id"])

    commander_rows = {
        str(row["commander_id"]): row
        for row in bundle.documents["commanders.json"]["commanders"]
    }
    for row in bundle.documents["formations.json"]["formations"]:
        force_id = str(row["formation_id"])
        template_id = f"toe_{force_id}"
        battalion_id = f"bn_{force_id}"
        faction = Faction(row["faction"])
        actor_id = str(row["actor_id"])
        roster = _materialize_roster(actors_by_id[actor_id], row["roster"])
        state.formations[template_id] = Formation(
            formation_id=template_id,
            display_name=str(row["display_name"]),
            faction=faction,
            nation=str(row["nation"]),
            deployment_zone=actor_id,
            preferred_categories=[str(value["category"]) for value in row["roster"]],
            notes=f"Earth3 P2 actor-scoped template for {actor_id}",
        )
        state.battalions[battalion_id] = Battalion(
            battalion_id=battalion_id,
            faction=faction,
            province_id=str(row["province_id"]),
            battalion_type=BattalionType.COMBINED_ARMS,
            roster=roster,
            authorized_roster=_copy_roster(roster),
            formation_id=template_id,
            strategic_formation_id=force_id,
            is_player_controlled=bool(row["is_player_controlled"]),
            movement_remaining=1,
            combat_actions_remaining=1,
            supply=100,
            condition=100,
        )
        state.strategic_formations[force_id] = StrategicFormation(
            strategic_formation_id=force_id,
            display_name=str(row["display_name"]),
            faction=faction,
            province_id=str(row["province_id"]),
            echelon=ForceEchelon.BRIGADE,
            commander_id=str(row["commander_id"]),
            battalion_ids=[battalion_id],
            template_formation_id=template_id,
            actor_id=actor_id,
            is_player_controlled=bool(row["is_player_controlled"]),
            movement_state="p3_routes_unavailable",
        )
        commander = commander_rows[str(row["commander_id"])]
        state.commanders[str(row["commander_id"])] = Commander(
            commander_id=str(row["commander_id"]),
            display_name=str(commander["display_name"]),
            rank=str(commander["rank"]),
            assigned_strategic_formation_id=force_id,
            status=CommanderStatus.ACTIVE,
            source="scenario_authored_fictional_role",
            provenance="src/gates_of_codex/data/earth3_v1/commanders.json",
        )

    from .actor_economy import install_actor_content, validate_actor_content_runtime
    from .strategic_actors import ACTOR_RUNTIME_KEY, validate_strategic_actor_runtime

    install_actor_content(state, catalog, allow_warnings=True)
    runtime = state.map_metadata[ACTOR_RUNTIME_KEY]
    state.map_metadata["actor_content_runtime"]["earth3_bootstrap_id"] = BOOTSTRAP_ID
    resources = {
        str(row["actor_id"]): int(row["resources"])
        for row in bundle.documents["factions.json"]["active_actors"]
    }
    for actor_id, actor in runtime["actors"].items():
        actor["resources"] = resources.get(actor_id, 0)
        actor["is_eliminated"] = actor_id not in resources
        if actor_id not in resources:
            actor["researched_keys"] = []
    validate_strategic_actor_runtime(state)
    validate_actor_content_runtime(state)

    sites = copy.deepcopy(bundle.documents["sites.json"]["sites"])
    zones = copy.deepcopy(bundle.documents["deployment_zones.json"]["deployment_zones"])
    objectives = copy.deepcopy(bundle.documents["objectives.json"]["objectives"])
    capitals = copy.deepcopy(bundle.documents["objectives.json"]["capitals"])
    preferences = copy.deepcopy(bundle.documents["tactical_maps.json"]["preferences"])
    state.map_metadata.update(
        {
            "scenario_content_phase": "p2_campaign_bootstrap",
            "operational_graph": None,
            "operational_maneuver_enabled": False,
            "operational_objectives": objectives,
            "coalition_capitals": {
                "western_coalition": ["e3_0592", "e3_1937"],
                "russian_command": ["e3_2793"],
            },
            "earth3_p2_capitals": capitals,
            "victory_hold_rounds": {},
            "campaign_outcome": {
                "status": "active",
                "winner_coalition": "",
                "loser_coalition": "",
                "reason": "",
                "selected_faction_result": "active",
                "victory_hold_rounds": 0,
            },
            "earth3_p2_site_intents": sites,
            "earth3_p2_deployment_zones": zones,
            "earth3_p2_tactical_map_preferences": preferences,
            BOOTSTRAP_METADATA_KEY: {
                "bootstrap_id": BOOTSTRAP_ID,
                "schema_version": BOOTSTRAP_SCHEMA_VERSION,
                "raw_file_sha256": dict(sorted(bundle.raw_sha256.items())),
                "raw_bundle_sha256": bundle.raw_bundle_sha256,
                "logical_bundle_sha256": bundle.logical_bundle_sha256,
                "footprint_sha256": bundle.footprint_sha256,
                "footprint": list(bundle.footprint),
                "catalog_identity": catalog_identity,
                "active_actor_ids": sorted(active_actor_ids),
                "movement_authority": MOVEMENT_AUTHORITY,
                "route_ids": [],
                "operational_node_ids": [],
                "scenario_references": {
                    "sites": sorted({str(row["province_id"]) for row in sites}),
                    "deployment_zones": sorted({str(value) for row in zones for value in row["province_ids"]}),
                    "objective_targets": sorted({str(value) for row in objectives for value in row["targets"]}),
                    "capital_provinces": sorted({str(row["province_id"]) for row in capitals}),
                    "tactical_map_provinces": sorted({str(row["province_id"]) for row in preferences}),
                },
                "dormant_prc_state": "inherited_actor_installation_compatibility_only",
                "commander_content_judgment": str(bundle.documents["commanders.json"]["content_judgment"]),
                "supply_connectivity_authority": "none_until_p3",
            },
        }
    )
    validate_earth3_bootstrap_campaign_state(state)
    state.validate()
    return state


def is_earth3_p2_campaign(state: CampaignState) -> bool:
    metadata = state.map_metadata.get(BOOTSTRAP_METADATA_KEY)
    return isinstance(metadata, dict) and metadata.get("bootstrap_id") == BOOTSTRAP_ID


def earth3_p2_footprint(state: CampaignState) -> frozenset[str]:
    if not is_earth3_p2_campaign(state):
        return frozenset()
    metadata = state.map_metadata[BOOTSTRAP_METADATA_KEY]
    value = metadata.get("footprint")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise Earth3BootstrapError("Earth3 P2 footprint provenance is invalid")
    return frozenset(value)


def require_earth3_p2_actionable(
    state: CampaignState,
    province_id: str,
    *,
    action: str,
) -> None:
    if is_earth3_p2_campaign(state) and province_id not in earth3_p2_footprint(state):
        raise ValueError(f"{action} target {province_id} is outside Earth3 P2 footprint")


def earth3_p2_movement_unavailable(state: CampaignState) -> bool:
    return is_earth3_p2_campaign(state) and state.map_metadata[BOOTSTRAP_METADATA_KEY].get(
        "movement_authority"
    ) == MOVEMENT_AUTHORITY


def earth3_p2_actor_resources(
    state: CampaignState,
    province_id: str,
    faction: Faction,
) -> tuple[dict[str, Any], str] | None:
    if not is_earth3_p2_campaign(state):
        return None
    require_earth3_p2_actionable(state, province_id, action="construction")
    province = state.provinces[province_id]
    actor_id = str(province.metadata.get("owner_actor_id") or "")
    runtime = state.map_metadata.get("strategic_actor_runtime")
    if not actor_id or not isinstance(runtime, dict) or actor_id not in runtime.get("actors", {}):
        raise Earth3BootstrapError(f"P2 province {province_id} has no actor-scoped economy")
    actor = runtime["actors"][actor_id]
    if actor.get("tactical_side") != faction.value:
        raise Earth3BootstrapError(f"P2 province {province_id} actor tactical side mismatch")
    return actor, actor_id


def validate_earth3_bootstrap_provenance(state: CampaignState) -> None:
    raw_metadata = state.map_metadata.get(BOOTSTRAP_METADATA_KEY)
    if raw_metadata is None:
        actor_content = state.map_metadata.get("actor_content_runtime")
        if (
            state.map_metadata.get("scenario_content_phase") == "p2_campaign_bootstrap"
            or (
                isinstance(actor_content, dict)
                and actor_content.get("earth3_bootstrap_id") == BOOTSTRAP_ID
            )
        ):
            raise Earth3BootstrapError("Earth3 P2 immutable provenance is missing")
        return
    if not isinstance(raw_metadata, dict) or raw_metadata.get("bootstrap_id") != BOOTSTRAP_ID:
        raise Earth3BootstrapError("Earth3 P2 bootstrap identity mismatch")
    metadata = raw_metadata
    required = {
        "active_actor_ids", "bootstrap_id", "catalog_identity", "commander_content_judgment",
        "dormant_prc_state", "footprint", "footprint_sha256", "logical_bundle_sha256",
        "movement_authority", "operational_node_ids", "raw_bundle_sha256", "raw_file_sha256",
        "route_ids", "scenario_references", "schema_version", "supply_connectivity_authority",
    }
    if set(metadata) != required:
        raise Earth3BootstrapError("Earth3 P2 immutable provenance fields mismatch")
    if metadata["schema_version"] != BOOTSTRAP_SCHEMA_VERSION:
        raise Earth3BootstrapError("Earth3 P2 bootstrap schema version mismatch")
    if metadata["raw_file_sha256"] != dict(sorted(_APPROVED_RAW_FILE_SHA256.items())):
        raise Earth3BootstrapError("Earth3 P2 raw-file provenance mismatch")
    if metadata["raw_bundle_sha256"] != _canonical_sha256(_APPROVED_RAW_FILE_SHA256):
        raise Earth3BootstrapError("Earth3 P2 raw bundle provenance mismatch")
    bundle = load_earth3_bootstrap()
    for key, expected in (
        ("logical_bundle_sha256", bundle.logical_bundle_sha256),
        ("footprint_sha256", bundle.footprint_sha256),
        ("footprint", list(bundle.footprint)),
    ):
        if metadata[key] != expected:
            raise Earth3BootstrapError(f"Earth3 P2 {key} provenance mismatch")
    if not isinstance(metadata["catalog_identity"], str) or not _HEX_SHA256.fullmatch(metadata["catalog_identity"]):
        raise Earth3BootstrapError("Earth3 P2 catalog identity is invalid")
    if state.catalog_signature != metadata["catalog_identity"]:
        raise Earth3BootstrapError("Earth3 P2 campaign catalog signature mismatch")
    expected_active = sorted(
        str(row["actor_id"])
        for row in bundle.documents["factions.json"]["active_actors"]
    )
    if metadata["active_actor_ids"] != expected_active:
        raise Earth3BootstrapError("Earth3 P2 active actor provenance mismatch")
    expected_references = {
        "sites": sorted(
            {str(row["province_id"]) for row in bundle.documents["sites.json"]["sites"]}
        ),
        "deployment_zones": sorted(
            {
                str(value)
                for row in bundle.documents["deployment_zones.json"]["deployment_zones"]
                for value in row["province_ids"]
            }
        ),
        "objective_targets": sorted(
            {
                str(value)
                for row in bundle.documents["objectives.json"]["objectives"]
                for value in row["targets"]
            }
        ),
        "capital_provinces": sorted(
            {
                str(row["province_id"])
                for row in bundle.documents["objectives.json"]["capitals"]
            }
        ),
        "tactical_map_provinces": sorted(
            {
                str(row["province_id"])
                for row in bundle.documents["tactical_maps.json"]["preferences"]
            }
        ),
    }
    if metadata["scenario_references"] != expected_references:
        raise Earth3BootstrapError("Earth3 P2 scenario-reference provenance mismatch")
    if metadata["commander_content_judgment"] != bundle.documents["commanders.json"]["content_judgment"]:
        raise Earth3BootstrapError("Earth3 P2 commander provenance mismatch")
    if metadata["dormant_prc_state"] != "inherited_actor_installation_compatibility_only":
        raise Earth3BootstrapError("Earth3 P2 dormant PRC provenance mismatch")
    actor_content = state.map_metadata.get("actor_content_runtime")
    if (
        not isinstance(actor_content, dict)
        or actor_content.get("earth3_bootstrap_id") != BOOTSTRAP_ID
        or any(
            actor_content.get(key) != metadata["catalog_identity"]
            for key in ("stack_signature", "wiring_signature")
        )
    ):
        raise Earth3BootstrapError("Earth3 P2 catalog provenance does not match actor content")
    if metadata["movement_authority"] != MOVEMENT_AUTHORITY:
        raise Earth3BootstrapError("Earth3 P2 movement authority mismatch")
    if metadata["route_ids"] or metadata["operational_node_ids"]:
        raise Earth3BootstrapError("Earth3 P2 cannot persist route or operational-node authority")
    if metadata["supply_connectivity_authority"] != "none_until_p3":
        raise Earth3BootstrapError("Earth3 P2 cannot claim operational supply connectivity")


def validate_earth3_bootstrap_campaign_state(state: CampaignState) -> None:
    validate_earth3_bootstrap_provenance(state)
    if not is_earth3_p2_campaign(state):
        return
    footprint = earth3_p2_footprint(state)
    if state.map_metadata.get("operational_graph") not in (None, ""):
        raise Earth3BootstrapError("Earth3 P2 cannot enable an operational graph")
    if state.map_metadata.get("operational_maneuver_enabled") is not False:
        raise Earth3BootstrapError("Earth3 P2 operational maneuver must remain disabled")
    for province in state.provinces.values():
        expected_actionable = province.province_id in footprint
        if province.metadata.get("scenario_actionable") is not expected_actionable:
            raise Earth3BootstrapError(f"province {province.province_id} scenario actionability mismatch")
        if not expected_actionable and province.owner != Faction.NEUTRAL:
            raise Earth3BootstrapError(f"province {province.province_id} ownership is outside footprint")
        if not expected_actionable and province.metadata.get("owner_actor_id"):
            raise Earth3BootstrapError(f"province {province.province_id} actor ownership is outside footprint")
    for force in state.strategic_formations.values():
        if force.province_id not in footprint:
            raise Earth3BootstrapError(f"formation {force.strategic_formation_id} is outside footprint")
    for battalion in state.battalions.values():
        if battalion.province_id not in footprint:
            raise Earth3BootstrapError(f"battalion {battalion.battalion_id} is outside footprint")
    for objective in state.map_metadata.get("operational_objectives", []):
        targets = objective.get("targets", [])
        if any(str(value) not in footprint for value in targets):
            raise Earth3BootstrapError(f"objective {objective.get('objective_id', objective.get('id', ''))} target outside footprint")
    for capital in state.map_metadata.get("earth3_p2_capitals", []):
        if not isinstance(capital, dict) or str(capital.get("province_id", "")) not in footprint:
            raise Earth3BootstrapError("Earth3 P2 strategic capital is outside footprint")
    for site in state.map_metadata.get("earth3_p2_site_intents", []):
        if not isinstance(site, dict) or str(site.get("province_id", "")) not in footprint:
            raise Earth3BootstrapError("Earth3 P2 site intent is outside footprint")
        if any(key in site for key in ("route_node_id", "routes", "edges")):
            raise Earth3BootstrapError("Earth3 P2 site intent cannot add route authority")
    for zone in state.map_metadata.get("earth3_p2_deployment_zones", []):
        if not isinstance(zone, dict) or any(
            str(value) not in footprint for value in zone.get("province_ids", [])
        ):
            raise Earth3BootstrapError("Earth3 P2 deployment target is outside footprint")
    for preference in state.map_metadata.get("earth3_p2_tactical_map_preferences", []):
        if (
            not isinstance(preference, dict)
            or str(preference.get("province_id", "")) not in footprint
        ):
            raise Earth3BootstrapError("Earth3 P2 tactical-map target is outside footprint")
    reference_lists = state.map_metadata[BOOTSTRAP_METADATA_KEY]["scenario_references"]
    if not isinstance(reference_lists, dict):
        raise Earth3BootstrapError("Earth3 P2 scenario references are invalid")
    for key, values in reference_lists.items():
        if not isinstance(values, list) or any(str(value) not in footprint for value in values):
            raise Earth3BootstrapError(f"Earth3 P2 {key} reference outside footprint")
