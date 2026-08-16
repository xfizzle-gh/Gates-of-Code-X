from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


AUTHORITY_SCHEMA = "gates-of-codex.ww3-2028-authority"
AUTHORITY_VERSION = 1
AUTHORITY_RELATIVE_PATH = Path("config/earth3/ww3_2028_authority.json")
PROVINCE_AUTHORITY_RELATIVE_PATH = Path("config/earth3/ww3_2028_province_authority.json")
PROVINCE_AUTHORITY_SCHEMA = "gates-of-codex.ww3-2028-province-authority"
PROVINCE_AUTHORITY_VERSION = 1
CORE_POWERS = ("nato", "ukr", "rusa", "prc")
CORE_CONTROLLER_VALUES = frozenset((*CORE_POWERS, "neutral"))
EXPECTED_SELECTABLE_PROVINCES = 3299
BELARUS_COUNTRY_ID = "BLR"
UKRAINE_COUNTRY_ID = "UKR"
UKRAINE_FRONT_REFERENCE_DATE = "2026-08-12"
UKRAINE_FRONT_METHOD = "owner_approved_approximate_august_2026_gameplay_line"
_REQUIRED_PROVINCE_KEYS = frozenset(
    {
        "province_id",
        "sovereign_owner",
        "military_controller",
        "core_controller",
        "expanded_controller",
        "garrison_actor",
        "neighbors",
        "hostile_neighbors",
        "metrics",
        "strategic",
    }
)


class Scenario2028AuthorityError(ValueError):
    """Raised when the frozen 2028 world authority is absent or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class ControllerBalance:
    counts: dict[str, int]
    mean: float
    lower_bound: float
    upper_bound: float
    deficits: dict[str, int]
    surpluses: dict[str, int]

    @property
    def within_target(self) -> bool:
        return not self.deficits and not self.surpluses


def repository_root(start: Path | None = None) -> Path:
    cursor = (start or Path(__file__)).resolve()
    if cursor.is_file():
        cursor = cursor.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src" / "gates_of_codex").exists():
            return candidate
    raise Scenario2028AuthorityError("repository_root_not_found")


def authority_document_path(root: Path | None = None) -> Path:
    return (root or repository_root()) / AUTHORITY_RELATIVE_PATH


def province_authority_path(root: Path | None = None) -> Path:
    return (root or repository_root()) / PROVINCE_AUTHORITY_RELATIVE_PATH


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise Scenario2028AuthorityError(f"authority_file_missing:{path.as_posix()}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Scenario2028AuthorityError(f"authority_file_invalid:{path.as_posix()}") from exc


def load_authority_document(root: Path | None = None) -> dict[str, Any]:
    payload = _read_json(authority_document_path(root))
    if not isinstance(payload, dict):
        raise Scenario2028AuthorityError("authority_document_must_be_object")
    validate_authority_document(payload)
    return payload


def authority_hash(document: Mapping[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_earth3_selectable(
    root: Path | None = None,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    from .earth3_campaign import load_earth3_authority

    authority = load_earth3_authority(root or repository_root())
    selectable = {
        str(row["id"]): dict(row)
        for row in authority.provinces
        if not bool(row["is_water"])
    }
    if len(selectable) != EXPECTED_SELECTABLE_PROVINCES:
        raise Scenario2028AuthorityError(
            f"canonical_earth3_selectable_count_mismatch:{len(selectable)}:{EXPECTED_SELECTABLE_PROVINCES}"
        )
    return authority, selectable


def selectable_ids_hash(province_ids: Iterable[str]) -> str:
    canonical = "\n".join(sorted(str(value) for value in province_ids))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def province_rows_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    canonical_rows = sorted((dict(row) for row in rows), key=lambda row: str(row.get("province_id", "")))
    canonical = json.dumps(
        canonical_rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _articulation_points(adjacency: Mapping[str, tuple[str, ...]]) -> frozenset[str]:
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    points: set[str] = set()
    clock = 0

    def visit(node: str) -> None:
        nonlocal clock
        discovery[node] = clock
        low[node] = clock
        clock += 1
        children = 0
        for neighbor in adjacency[node]:
            if neighbor not in discovery:
                parent[neighbor] = node
                children += 1
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
                if parent.get(node) is None and children > 1:
                    points.add(node)
                if parent.get(node) is not None and low[neighbor] >= discovery[node]:
                    points.add(node)
            elif neighbor != parent.get(node):
                low[node] = min(low[node], discovery[neighbor])

    for node in sorted(adjacency):
        if node not in discovery:
            parent[node] = None
            visit(node)
    return frozenset(points)


def _canonical_graph(
    selectable: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, tuple[str, ...]], frozenset[str]]:
    ids = set(selectable)
    adjacency = {
        province_id: tuple(sorted(str(value) for value in row["neighbors"] if str(value) in ids))
        for province_id, row in selectable.items()
    }
    return adjacency, _articulation_points(adjacency)


def validate_province_authority_payload(
    payload: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    if payload.get("schema") != PROVINCE_AUTHORITY_SCHEMA:
        raise Scenario2028AuthorityError("province_authority_schema_mismatch")
    if payload.get("version") != PROVINCE_AUTHORITY_VERSION:
        raise Scenario2028AuthorityError("province_authority_version_mismatch")
    if payload.get("authority_id") != "earth3_ww3_2028_v1":
        raise Scenario2028AuthorityError("province_authority_id_mismatch")

    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        raise Scenario2028AuthorityError("province_authority_provenance_required")
    authority, selectable = _canonical_earth3_selectable(root)
    expected_ids_hash = selectable_ids_hash(selectable)
    expected_document_hash = authority_hash(load_authority_document(root))
    required_provenance = {
        "earth3_dataset_sha256": authority.dataset_sha256,
        "earth3_geometry_sha256": authority.geometry_sha256,
        "earth3_included_ids_sha256": authority.included_ids_sha256,
        "earth3_selectable_ids_sha256": expected_ids_hash,
        "authority_document_sha256": expected_document_hash,
        "ukraine_front_method": UKRAINE_FRONT_METHOD,
    }
    for field, expected in required_provenance.items():
        if provenance.get(field) != expected:
            raise Scenario2028AuthorityError(f"province_authority_provenance_mismatch:{field}")
    generator = provenance.get("generator")
    if not isinstance(generator, str) or not generator.strip():
        raise Scenario2028AuthorityError("province_authority_generator_required")
    if provenance.get("owner_visual_audit_required") is not True:
        raise Scenario2028AuthorityError("province_authority_owner_visual_audit_required")

    rows = payload.get("provinces")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise Scenario2028AuthorityError("province_authority_must_contain_provinces_list")
    typed_rows = [dict(row) for row in rows]
    validate_province_rows(
        typed_rows,
        expected_count=EXPECTED_SELECTABLE_PROVINCES,
        expected_province_ids=set(selectable),
        canonical_rows=selectable,
    )
    if payload.get("rows_sha256") != province_rows_hash(typed_rows):
        raise Scenario2028AuthorityError("province_authority_rows_sha256_mismatch")
    return typed_rows


def load_province_authority(root: Path | None = None) -> list[dict[str, Any]]:
    payload = _read_json(province_authority_path(root))
    if not isinstance(payload, dict):
        raise Scenario2028AuthorityError("province_authority_payload_must_be_object")
    return validate_province_authority_payload(payload, root=root)


def validate_authority_document(document: Mapping[str, Any]) -> None:
    if document.get("schema") != AUTHORITY_SCHEMA:
        raise Scenario2028AuthorityError("authority_schema_mismatch")
    if document.get("version") != AUTHORITY_VERSION:
        raise Scenario2028AuthorityError("authority_version_mismatch")
    if document.get("authority_id") != "earth3_ww3_2028_v1":
        raise Scenario2028AuthorityError("authority_id_mismatch")
    if document.get("scenario_year") != 2028:
        raise Scenario2028AuthorityError("scenario_year_mismatch")

    dataset = document.get("earth3_dataset")
    if not isinstance(dataset, Mapping):
        raise Scenario2028AuthorityError("earth3_dataset_required")
    if dataset.get("selectable_province_count") != EXPECTED_SELECTABLE_PROVINCES:
        raise Scenario2028AuthorityError("earth3_selectable_count_mismatch")
    if dataset.get("stable_ids_required") is not True:
        raise Scenario2028AuthorityError("earth3_stable_ids_required")
    if "exact non-water province IDs" not in str(dataset.get("canonical_selectable_set_source", "")):
        raise Scenario2028AuthorityError("earth3_canonical_selectable_set_source_required")

    profiles = document.get("profiles")
    if not isinstance(profiles, Mapping):
        raise Scenario2028AuthorityError("profiles_required")
    core = profiles.get("core")
    expanded = profiles.get("expanded")
    if not isinstance(core, Mapping) or not isinstance(expanded, Mapping):
        raise Scenario2028AuthorityError("core_and_expanded_profiles_required")
    if tuple(core.get("campaign_powers", ())) != CORE_POWERS:
        raise Scenario2028AuthorityError("core_campaign_powers_mismatch")
    alliances = core.get("alliances")
    if alliances != [["nato", "ukr"], ["rusa", "prc"]]:
        raise Scenario2028AuthorityError("core_alliances_mismatch")

    province_contract = document.get("province_authority_contract")
    if not isinstance(province_contract, Mapping):
        raise Scenario2028AuthorityError("province_authority_contract_required")
    if not _REQUIRED_PROVINCE_KEYS <= set(province_contract.get("required_fields", ())):
        raise Scenario2028AuthorityError("province_authority_required_fields_mismatch")
    authentication = province_contract.get("authentication")
    if not isinstance(authentication, Mapping) or any(
        authentication.get(key) is not True
        for key in (
            "exact_selectable_id_set_required",
            "earth3_exact_byte_authority_required",
            "canonical_adjacency_required",
            "derived_graph_metrics_required",
            "payload_provenance_required",
            "rows_sha256_required",
        )
    ):
        raise Scenario2028AuthorityError("province_authority_authentication_contract_required")

    belarus = document.get("belarus")
    if not isinstance(belarus, Mapping):
        raise Scenario2028AuthorityError("belarus_authority_required")
    if belarus.get("sovereign_owner") != BELARUS_COUNTRY_ID:
        raise Scenario2028AuthorityError("belarus_sovereignty_mismatch")
    if belarus.get("mandatory_military_controller") != "prc":
        raise Scenario2028AuthorityError("belarus_controller_mismatch")
    if belarus.get("sovereignty_transfer") is not False:
        raise Scenario2028AuthorityError("belarus_sovereignty_transfer_forbidden")

    neutral = document.get("neutral_nations")
    if not isinstance(neutral, Mapping):
        raise Scenario2028AuthorityError("neutral_nation_contract_required")
    if neutral.get("retain_sovereignty") is not True:
        raise Scenario2028AuthorityError("neutral_sovereignty_required")
    if neutral.get("automatic_coalition_entry") is not False:
        raise Scenario2028AuthorityError("neutral_automatic_coalition_forbidden")
    if neutral.get("casualties_persist") is not True:
        raise Scenario2028AuthorityError("neutral_casualty_persistence_required")

    balance = document.get("controller_balance")
    if not isinstance(balance, Mapping):
        raise Scenario2028AuthorityError("controller_balance_contract_required")
    if tuple(balance.get("powers", ())) != CORE_POWERS:
        raise Scenario2028AuthorityError("controller_balance_powers_mismatch")
    tolerance = balance.get("target_tolerance_ratio")
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or float(tolerance) != 0.15:
        raise Scenario2028AuthorityError("controller_balance_tolerance_mismatch")
    if "never invent disconnected" not in str(balance.get("prc_shortfall_policy", "")).lower():
        raise Scenario2028AuthorityError("prc_shortfall_policy_mismatch")

    front = document.get("ukraine_front")
    if not isinstance(front, Mapping):
        raise Scenario2028AuthorityError("ukraine_front_authority_required")
    if front.get("reference_date") != UKRAINE_FRONT_REFERENCE_DATE:
        raise Scenario2028AuthorityError("ukraine_front_reference_date_mismatch")
    primary = front.get("primary_source")
    if not isinstance(primary, Mapping) or primary.get("publisher") != "DeepState":
        raise Scenario2028AuthorityError("ukraine_front_primary_source_mismatch")
    mapping_rule = front.get("whole_province_mapping_rule")
    if not isinstance(mapping_rule, Mapping):
        raise Scenario2028AuthorityError("ukraine_mapping_rule_required")
    if mapping_rule.get("method") != UKRAINE_FRONT_METHOD:
        raise Scenario2028AuthorityError("ukraine_mapping_method_mismatch")
    if mapping_rule.get("geometry_input_required") is not False:
        raise Scenario2028AuthorityError("ukraine_approximate_geometry_contract_mismatch")
    if mapping_rule.get("owner_visual_audit_required") is not True:
        raise Scenario2028AuthorityError("ukraine_owner_visual_audit_required")


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise Scenario2028AuthorityError(f"province_{field}_required")
    return value.strip()


def _required_string_list(row: Mapping[str, Any], field: str) -> list[str]:
    value = row.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise Scenario2028AuthorityError(f"province_{field}_must_be_string_list")
    if value != sorted(set(value)):
        raise Scenario2028AuthorityError(f"province_{field}_must_be_sorted_unique")
    return value


def validate_province_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_count: int = EXPECTED_SELECTABLE_PROVINCES,
    expected_province_ids: set[str] | frozenset[str] | None = None,
    canonical_rows: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    materialized = [dict(row) for row in rows]
    if len(materialized) != expected_count:
        raise Scenario2028AuthorityError(
            f"province_authority_count_mismatch:{len(materialized)}:{expected_count}"
        )

    if canonical_rows is None and expected_count == EXPECTED_SELECTABLE_PROVINCES:
        _, canonical_rows = _canonical_earth3_selectable()
    if expected_province_ids is None and canonical_rows is not None:
        expected_province_ids = set(canonical_rows)

    province_ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    belarus_count = 0
    ukraine_count = 0
    for row in materialized:
        missing_keys = _REQUIRED_PROVINCE_KEYS - set(row)
        if missing_keys:
            raise Scenario2028AuthorityError(
                f"province_required_fields_missing:{row.get('province_id', '<unknown>')}:{','.join(sorted(missing_keys))}"
            )
        province_id = _required_text(row, "province_id")
        sovereign_owner = _required_text(row, "sovereign_owner")
        military_controller = _required_text(row, "military_controller")
        core_controller = _required_text(row, "core_controller")
        _required_text(row, "expanded_controller")
        garrison_actor = row.get("garrison_actor")
        if garrison_actor is not None and (not isinstance(garrison_actor, str) or not garrison_actor.strip()):
            raise Scenario2028AuthorityError(f"province_garrison_actor_invalid:{province_id}")
        if province_id in province_ids:
            raise Scenario2028AuthorityError(f"duplicate_province_id:{province_id}")
        province_ids.add(province_id)
        by_id[province_id] = row
        if core_controller not in CORE_CONTROLLER_VALUES:
            raise Scenario2028AuthorityError(
                f"invalid_core_controller:{province_id}:{core_controller}"
            )
        if military_controller != core_controller and row.get("controller_profile", "core") == "core":
            raise Scenario2028AuthorityError(
                f"core_military_controller_mismatch:{province_id}:{military_controller}:{core_controller}"
            )
        _required_string_list(row, "neighbors")
        _required_string_list(row, "hostile_neighbors")
        if not isinstance(row.get("metrics"), Mapping):
            raise Scenario2028AuthorityError(f"province_metrics_required:{province_id}")
        if not isinstance(row.get("strategic"), Mapping):
            raise Scenario2028AuthorityError(f"province_strategic_required:{province_id}")
        if sovereign_owner == BELARUS_COUNTRY_ID:
            belarus_count += 1
            if core_controller != "prc" or military_controller != "prc":
                raise Scenario2028AuthorityError(
                    f"belarus_prc_control_required:{province_id}"
                )
        if sovereign_owner == UKRAINE_COUNTRY_ID:
            ukraine_count += 1
            if row.get("front_reference_date") != UKRAINE_FRONT_REFERENCE_DATE:
                raise Scenario2028AuthorityError(
                    f"ukraine_front_reference_required:{province_id}"
                )
            if row.get("front_source") != "deepstate_approximate":
                raise Scenario2028AuthorityError(
                    f"ukraine_front_source_required:{province_id}"
                )
            if row.get("front_method") != UKRAINE_FRONT_METHOD:
                raise Scenario2028AuthorityError(
                    f"ukraine_front_method_required:{province_id}"
                )

    if expected_province_ids is not None and province_ids != set(expected_province_ids):
        missing = sorted(set(expected_province_ids) - province_ids)
        unexpected = sorted(province_ids - set(expected_province_ids))
        raise Scenario2028AuthorityError(
            "province_authority_id_set_mismatch:"
            f"missing={','.join(missing[:8])}:unexpected={','.join(unexpected[:8])}"
        )

    if canonical_rows is not None:
        adjacency, chokepoints = _canonical_graph(canonical_rows)
        coalition = {
            "nato": "west",
            "ukr": "west",
            "rusa": "east",
            "prc": "east",
            "neutral": "neutral",
        }
        for province_id, row in by_id.items():
            canonical = canonical_rows.get(province_id)
            if canonical is None:
                raise Scenario2028AuthorityError(f"province_not_selectable:{province_id}")
            expected_neighbors = list(adjacency[province_id])
            if row["neighbors"] != expected_neighbors:
                raise Scenario2028AuthorityError(f"province_adjacency_mismatch:{province_id}")
            metrics = row["metrics"]
            if metrics.get("graph_degree") != len(canonical["neighbors"]):
                raise Scenario2028AuthorityError(f"province_graph_degree_mismatch:{province_id}")
            if metrics.get("selectable_degree") != len(expected_neighbors):
                raise Scenario2028AuthorityError(f"province_selectable_degree_mismatch:{province_id}")
            strategic = row["strategic"]
            if strategic.get("is_chokepoint") is not (province_id in chokepoints):
                raise Scenario2028AuthorityError(f"province_chokepoint_mismatch:{province_id}")
            strategic_value = strategic.get("strategic_value")
            if (
                isinstance(strategic_value, bool)
                or not isinstance(strategic_value, (int, float))
                or float(strategic_value) < 0
            ):
                raise Scenario2028AuthorityError(f"province_strategic_value_invalid:{province_id}")

        for province_id, row in by_id.items():
            own_coalition = coalition[row["core_controller"]]
            expected_hostile = sorted(
                neighbor
                for neighbor in adjacency[province_id]
                if neighbor in by_id
                and own_coalition in {"west", "east"}
                and coalition[by_id[neighbor]["core_controller"]] in {"west", "east"}
                and coalition[by_id[neighbor]["core_controller"]] != own_coalition
            )
            if row["hostile_neighbors"] != expected_hostile:
                raise Scenario2028AuthorityError(f"province_hostile_adjacency_mismatch:{province_id}")

    if not belarus_count:
        raise Scenario2028AuthorityError("belarus_provinces_required")
    if not ukraine_count:
        raise Scenario2028AuthorityError("ukraine_provinces_required")


def audit_controller_balance(
    rows: Iterable[Mapping[str, Any]],
    *,
    tolerance_ratio: float = 0.15,
) -> ControllerBalance:
    if tolerance_ratio < 0:
        raise Scenario2028AuthorityError("controller_balance_tolerance_negative")
    counts_counter = Counter(
        str(row.get("core_controller", ""))
        for row in rows
        if row.get("core_controller") in CORE_POWERS
    )
    counts = {power: int(counts_counter.get(power, 0)) for power in CORE_POWERS}
    mean = sum(counts.values()) / len(CORE_POWERS)
    lower = mean * (1.0 - tolerance_ratio)
    upper = mean * (1.0 + tolerance_ratio)
    deficits = {
        power: max(0, int(lower - count + 0.999999999))
        for power, count in counts.items()
        if count < lower
    }
    surpluses = {
        power: max(0, int(count - upper + 0.999999999))
        for power, count in counts.items()
        if count > upper
    }
    return ControllerBalance(
        counts=counts,
        mean=mean,
        lower_bound=lower,
        upper_bound=upper,
        deficits=deficits,
        surpluses=surpluses,
    )
