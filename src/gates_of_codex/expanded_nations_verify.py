from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from .faction_wiring_scan import _side_from_filename, _side_from_name
from .goh_source import scan_source_entries
from .expanded_nations_models import (
    ACTIVATION_MODE_CODEX_PASSTHROUGH,
    ACTIVATION_SCHEMA,
    ACTIVATION_VERSION,
    BREED_ROOT_RELATIVE,
    BROAD_ROSTER_INCLUDES,
    ExpandedNationsError,
    GENERATED_MARKER,
    MANIFEST_RELATIVE,
    OPPONENT_UNITS_RELATIVE,
    ROSTER_RELATIVE,
    UNITS_RELATIVE,
    all_managed_candidates,
    managed_relatives_for_manifest,
    managed_relatives_for_side,
    manifest_activation_mode,
    presentation_relatives_for_actor,
    research_relative_for_side,
    safe_target,
    sha256_bytes,
    side_family,
)

_STANDARD_RESEARCH_IDS = {
    "reinforcement_stage_1", "reinforcement_stage_2", "reinforcement_stage_3",
    "reinforcement_stage_4", "reinforcement_stage_5", "defense_level_1",
    "defense_level_2", "defense_level_3",
}
_UNIT_RE = re.compile(
    r'^\{"([^"]+)"\s+requires\s+"([^"]*)"\s+costs\s+(-?\d+)'
    r"\s+position\s+-?\d+\s+-?\d+\}$"
)
_TECH_RE = re.compile(
    r'^\{\s*tech\s+"([^"]+)"\s+requires\s+"([^"]*)"\s+costs\s+(-?\d+)'
    r"\s+position\s+-?\d+\s+-?\d+\}$"
)
_LEGACY_RUSA_CREW = {
    "grd_vehicleman", "sup_guncrew", "sup_supporter", "sup_tankman",
    "sup_vehicleman", "vmf_vehicleman",
}


def verify_actor_projection_files(gates_root: str | Path) -> dict[str, Any]:
    root = Path(gates_root).expanduser().resolve()
    manifest_path = root / MANIFEST_RELATIVE
    if not manifest_path.is_file():
        raise ExpandedNationsError(
            f"Expanded Nations activation manifest is missing: {manifest_path}"
        )
    manifest = load_manifest(manifest_path)
    verify_manifest_files(root, manifest)
    outputs = {
        Path(str(row["relative_path"])): safe_target(
            root, str(row["relative_path"])
        ).read_bytes()
        for row in manifest["files"]
    }
    verify_projection_artifacts(outputs, manifest)
    return manifest


def verify_projection_artifacts(
    outputs: Mapping[Path, bytes],
    manifest: Mapping[str, Any],
) -> None:
    if (
        manifest.get("schema") != ACTIVATION_SCHEMA
        or manifest.get("schema_version") != ACTIVATION_VERSION
    ):
        raise ExpandedNationsError("Unsupported activation manifest payload")
    mode = manifest_activation_mode(manifest)
    if mode == ACTIVATION_MODE_CODEX_PASSTHROUGH:
        _verify_codex_passthrough_artifacts(outputs, manifest)
        return
    side = str(manifest.get("tactical_side", ""))
    expected = set(managed_relatives_for_manifest(manifest))
    expected.update(_manifest_presentation_relatives(manifest))
    expected.update(_manifest_breed_relatives(manifest))
    if set(outputs) != expected:
        missing = sorted(path.as_posix() for path in expected - set(outputs))
        extra = sorted(path.as_posix() for path in set(outputs) - expected)
        raise ExpandedNationsError(
            f"Projection artifact set is invalid; missing={missing}; extra={extra}"
        )
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise ExpandedNationsError("Activation manifest files must be a list")
    row_map = {Path(str(row.get("relative_path", ""))): row for row in rows}
    if set(row_map) != expected or len(row_map) != len(rows):
        raise ExpandedNationsError(
            "Activation manifest file rows are duplicate or incomplete"
        )
    for relative, data in outputs.items():
        row = row_map[relative]
        if (
            sha256_bytes(data) != row.get("sha256")
            or len(data) != int(row.get("byte_count", -1))
        ):
            raise ExpandedNationsError(
                f"Projection artifact metadata mismatch: {relative}"
            )

    text_relatives = {
        ROSTER_RELATIVE,
        UNITS_RELATIVE,
        OPPONENT_UNITS_RELATIVE,
        research_relative_for_side(side),
    }
    texts = {
        relative: outputs[relative].decode("utf-8-sig")
        for relative in text_relatives
    }
    roster = texts[ROSTER_RELATIVE]
    actor_text = texts[UNITS_RELATIVE]
    opponent_text = texts[OPPONENT_UNITS_RELATIVE]
    research_text = texts[research_relative_for_side(side)]
    if any(
        GENERATED_MARKER not in value
        for value in (roster, actor_text, opponent_text, research_text)
    ):
        raise ExpandedNationsError(
            "One or more projection artifacts lack the managed marker"
        )
    if roster.count('(include "conquest/goc_active_actor_units.set")') != 1:
        raise ExpandedNationsError(
            "Active roster must include the actor projection exactly once"
        )
    if roster.count('(include "conquest/goc_opponent_units.set")') != 1:
        raise ExpandedNationsError(
            "Active roster must include the opponent projection exactly once"
        )
    for include in BROAD_ROSTER_INCLUDES:
        if f'(include "{include}")' in roster:
            raise ExpandedNationsError(
                f"Active roster contains unfiltered broad roster {include}"
            )

    _verify_actor_units(actor_text, manifest, side)
    _verify_opponents(opponent_text, manifest, side)
    _verify_research(research_text, manifest)
    _verify_presentation(outputs, manifest)
    _verify_breed_projection(outputs, manifest)


def _verify_codex_passthrough_artifacts(
    outputs: Mapping[Path, bytes],
    manifest: Mapping[str, Any],
) -> None:
    if outputs:
        raise ExpandedNationsError(
            "Code:X passthrough activation must not materialize projection artifacts"
        )
    if manifest.get("files"):
        raise ExpandedNationsError(
            "Code:X passthrough activation must not manage projection files"
        )
    if str(manifest.get("actor_id", "")) != "prc":
        raise ExpandedNationsError(
            "Code:X passthrough activation is only authorized for actor prc"
        )
    if str(manifest.get("tactical_side", "")) != "prc":
        raise ExpandedNationsError(
            "Code:X passthrough activation requires tactical_side=prc"
        )
    if int(manifest.get("opponent_entry_count", -1)) != 0:
        raise ExpandedNationsError(
            "Code:X passthrough activation must not project opponent isolation files"
        )
    if list(manifest.get("units") or []):
        raise ExpandedNationsError(
            "Code:X passthrough activation must not clone actor purchase units"
        )
    if list(manifest.get("research_nodes") or []):
        raise ExpandedNationsError(
            "Code:X passthrough activation must not rebuild actor research nodes"
        )
    if int(manifest.get("unit_count", -1)) <= 0:
        raise ExpandedNationsError(
            "Code:X passthrough activation requires positive inherited unit_count"
        )
    if int(manifest.get("research_node_count", -1)) <= 0:
        raise ExpandedNationsError(
            "Code:X passthrough activation requires positive inherited research_node_count"
        )


def _verify_actor_units(
    actor_text: str,
    manifest: Mapping[str, Any],
    side: str,
) -> None:
    actor_rows = manifest.get("units")
    if not isinstance(actor_rows, list):
        raise ExpandedNationsError("Activation manifest units must be a list")
    actor_scan = scan_source_entries(actor_text, UNITS_RELATIVE.as_posix())
    if actor_scan.diagnostics:
        raise ExpandedNationsError("Generated actor unit file is malformed")
    expected_actor_ids = [str(row.get("unit_name", "")) for row in actor_rows]
    actual_actor_ids = [entry.name for entry in actor_scan.entries]
    if actual_actor_ids != expected_actor_ids:
        raise ExpandedNationsError(
            "Generated actor unit IDs do not match manifest: "
            f"expected={expected_actor_ids}; actual={actual_actor_ids}"
        )
    if len(actual_actor_ids) != int(manifest.get("unit_count", -1)):
        raise ExpandedNationsError(
            "Generated actor unit count does not match manifest"
        )
    for entry in actor_scan.entries:
        side_calls = [
            call.value.lower() for call in entry.calls if call.family == "side"
        ]
        if side_calls != [side]:
            raise ExpandedNationsError(
                f"Generated actor unit {entry.name} has tactical sides "
                f"{side_calls}, expected {side}"
            )
        if side != "rusa":
            continue
        periods = [
            call.value.lower() for call in entry.calls if call.family == "period"
        ]
        crews = {
            call.value.split(":", 1)[0].strip().lower()
            for call in entry.calls
            if call.family == "crew" and ":" in call.value
        }
        bad = sorted(crews & _LEGACY_RUSA_CREW)
        if "era1960" in periods and bad:
            raise ExpandedNationsError(
                f"Generated RUSA unit {entry.name} retains legacy "
                f"era1960 crew aliases: {bad}"
            )


def _verify_opponents(
    opponent_text: str,
    manifest: Mapping[str, Any],
    side: str,
) -> None:
    opponent_rows = manifest.get("opponent_units")
    if not isinstance(opponent_rows, list):
        raise ExpandedNationsError(
            "Activation manifest opponent_units must be a list"
        )
    opponent_scan = scan_source_entries(
        opponent_text, OPPONENT_UNITS_RELATIVE.as_posix()
    )
    if (
        opponent_scan.diagnostics
        or len(opponent_scan.entries) != len(opponent_rows)
    ):
        raise ExpandedNationsError(
            "Generated opponent projection is malformed or incomplete"
        )
    selected_family = side_family(side)
    for entry, row in zip(opponent_scan.entries, opponent_rows, strict=True):
        expected_name = str(row.get("entry_name", ""))
        classification_side = str(row.get("tactical_side", ""))
        native_side = str(row.get("native_side", ""))
        source_reference = str(row.get("source_reference", ""))
        actual_sides = [
            call.value.lower() for call in entry.calls if call.family == "side"
        ]
        expected_sides = [native_side] if native_side else []
        if entry.name != expected_name or actual_sides != expected_sides:
            raise ExpandedNationsError(
                f"Generated opponent entry does not match manifest: {expected_name}"
            )

        suffix_side = _side_from_name(entry.name)
        filename_side = _side_from_filename(_source_filename(source_reference))
        derived_classification = suffix_side or native_side or filename_side
        if classification_side != derived_classification:
            raise ExpandedNationsError(
                "Generated opponent classification disagrees with "
                f"source authority: {entry.name}"
            )
        if classification_side != native_side:
            if not (
                suffix_side
                and suffix_side == classification_side
                and filename_side
                and filename_side == native_side
            ):
                raise ExpandedNationsError(
                    "Generated opponent side mismatch lacks "
                    f"source-backed authority: {entry.name}"
                )
        effective_classification = classification_side or native_side
        if effective_classification in selected_family:
            raise ExpandedNationsError(
                "Generated opponent projection leaks selected side family "
                f"{sorted(selected_family)}: {entry.name}"
            )


def _verify_research(
    research_text: str,
    manifest: Mapping[str, Any],
) -> None:
    parsed_nodes = parse_generated_research(research_text)
    expected_nodes = manifest.get("research_nodes")
    if not isinstance(expected_nodes, list) or parsed_nodes != expected_nodes:
        raise ExpandedNationsError(
            "Generated research semantics do not match manifest"
        )
    if len(parsed_nodes) != int(manifest.get("research_node_count", -1)):
        raise ExpandedNationsError(
            "Generated research-node count does not match manifest"
        )
    actor_id = str(manifest.get("actor_id", ""))
    actor_rows = manifest.get("units")
    if not isinstance(actor_rows, list):
        raise ExpandedNationsError("Activation manifest units must be a list")
    expected_actor_ids = [str(row.get("unit_name", "")) for row in actor_rows]
    engine_ids = [str(row["engine_id"]) for row in parsed_nodes]
    if len(engine_ids) != len(set(engine_ids)):
        raise ExpandedNationsError(
            "Generated research contains duplicate engine IDs"
        )
    unlock_ids: list[str] = []
    engine_set = set(engine_ids)
    for row in parsed_nodes:
        key = str(row["key"])
        if not key.startswith(f"actor:{actor_id}:"):
            raise ExpandedNationsError(
                f"Generated research contains foreign actor key: {key}"
            )
        required = str(row["required_engine_id"])
        if required and required not in engine_set:
            raise ExpandedNationsError(
                f"Generated research node {key} requires unknown ID {required}"
            )
        unlock = row.get("unlock_unit")
        if unlock is None:
            raise ExpandedNationsError(
                f"Generated research contains non-purchase node: {key}"
            )
        if str(unlock) != str(row["engine_id"]):
            raise ExpandedNationsError(
                f"Generated research node {key} unlock ID disagrees with engine ID"
            )
        unlock_ids.append(str(unlock))
    if (
        len(unlock_ids) != len(set(unlock_ids))
        or sorted(unlock_ids) != sorted(expected_actor_ids)
    ):
        raise ExpandedNationsError(
            "Generated research unlock IDs do not match actor purchase IDs: "
            f"expected={expected_actor_ids}; actual={unlock_ids}"
        )


def _verify_presentation(
    outputs: Mapping[Path, bytes],
    manifest: Mapping[str, Any],
) -> None:
    expected = set(_manifest_presentation_relatives(manifest))
    actual = {path for path in outputs if path.suffix.lower() == ".png"}
    if actual != expected:
        raise ExpandedNationsError(
            "Generated actor presentation files are incomplete"
        )
    for relative in expected:
        if not outputs[relative].startswith(b"\x89PNG\r\n\x1a\n"):
            raise ExpandedNationsError(
                f"Generated actor presentation is not a PNG: {relative}"
            )


def _manifest_presentation_relatives(
    manifest: Mapping[str, Any],
) -> tuple[Path, ...]:
    raw = manifest.get("presentation_files", [])
    if not isinstance(raw, list):
        raise ExpandedNationsError(
            "Activation manifest presentation_files must be a list"
        )
    values = tuple(Path(str(item)) for item in raw)
    if len(values) != len(set(values)):
        raise ExpandedNationsError(
            "Activation manifest presentation files are duplicate"
        )
    actor_id = str(manifest.get("actor_id", ""))
    allowed = set(presentation_relatives_for_actor(actor_id))
    if not set(values).issubset(allowed):
        raise ExpandedNationsError(
            "Activation manifest contains unauthorized presentation paths"
        )
    if values and set(values) != allowed:
        raise ExpandedNationsError(
            "Activation manifest actor presentation is incomplete"
        )
    return values


def _manifest_breed_relatives(
    manifest: Mapping[str, Any],
) -> tuple[Path, ...]:
    raw = manifest.get("breed_files", [])
    if not isinstance(raw, list):
        raise ExpandedNationsError(
            "Activation manifest breed_files must be a list"
        )
    values = tuple(Path(str(item)) for item in raw)
    if len(values) != len(set(values)):
        raise ExpandedNationsError(
            "Activation manifest breed files are duplicate"
        )
    side = str(manifest.get("tactical_side", "")).lower()
    allowed_root = BREED_ROOT_RELATIVE / side
    for relative in values:
        if relative.suffix.lower() not in {".set", ".inc"}:
            raise ExpandedNationsError(
                f"Activation manifest contains unsupported breed artifact: {relative}"
            )
        try:
            relative.relative_to(allowed_root)
        except ValueError as exc:
            raise ExpandedNationsError(
                f"Activation manifest breed artifact escapes target side: {relative}"
            ) from exc
    return values


def _verify_breed_projection(
    outputs: Mapping[Path, bytes],
    manifest: Mapping[str, Any],
) -> None:
    for relative in _manifest_breed_relatives(manifest):
        data = outputs[relative]
        text = data.decode("utf-8-sig")
        if not text.startswith(GENERATED_MARKER):
            raise ExpandedNationsError(
                f"Generated cross-side breed lacks managed marker: {relative}"
            )
        if relative.suffix.lower() == ".set" and text.count("{") != text.count("}"):
            raise ExpandedNationsError(
                f"Generated cross-side breed has unbalanced braces: {relative}"
            )


def _source_filename(source_reference: str) -> str:
    normalized = source_reference.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1]


def parse_generated_research(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    parsed: list[dict[str, Any]] = []
    tagged_indexes: set[int] = set()
    definitions: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = _UNIT_RE.fullmatch(stripped) or _TECH_RE.fullmatch(stripped)
        if match:
            definitions.append((index, match.group(1)))
        if not stripped.startswith("; goc-node "):
            continue
        try:
            metadata = json.loads(stripped[len("; goc-node "):])
        except json.JSONDecodeError as exc:
            raise ExpandedNationsError(
                f"Invalid generated research metadata on line {index + 1}"
            ) from exc
        if index + 1 >= len(lines):
            raise ExpandedNationsError(
                "Generated research metadata has no following node"
            )
        node_line = lines[index + 1].strip()
        node_match = _UNIT_RE.fullmatch(node_line)
        is_unit = node_match is not None
        if node_match is None:
            node_match = _TECH_RE.fullmatch(node_line)
        if node_match is None:
            raise ExpandedNationsError(
                "Generated research metadata is followed by an invalid node"
            )
        normalized = {
            "key": str(metadata.get("key", "")),
            "engine_id": str(metadata.get("engine_id", "")),
            "required_engine_id": str(metadata.get("required_engine_id", "")),
            "cost": int(metadata.get("cost", -1)),
            "unlock_unit": (
                None
                if metadata.get("unlock_unit") is None
                else str(metadata.get("unlock_unit"))
            ),
        }
        if normalized["engine_id"] != node_match.group(1):
            raise ExpandedNationsError(
                "Generated research metadata engine ID disagrees with node"
            )
        if normalized["required_engine_id"] != node_match.group(2):
            raise ExpandedNationsError(
                "Generated research metadata prerequisite disagrees with node"
            )
        if (
            normalized["cost"] != int(node_match.group(3))
            or normalized["cost"] < 0
        ):
            raise ExpandedNationsError(
                "Generated research metadata cost disagrees with node"
            )
        if is_unit != (normalized["unlock_unit"] is not None):
            raise ExpandedNationsError(
                "Generated research node kind disagrees with unlock metadata"
            )
        parsed.append(normalized)
        tagged_indexes.add(index + 1)
    untagged = {
        engine_id
        for line_index, engine_id in definitions
        if line_index not in tagged_indexes
    }
    if untagged != _STANDARD_RESEARCH_IDS:
        raise ExpandedNationsError(
            "Generated research has unexpected untagged nodes"
        )
    if len(untagged) + len(parsed) != len(definitions):
        raise ExpandedNationsError(
            "Generated research contains duplicate or untracked definitions"
        )
    return parsed


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if (
        payload.get("schema") != ACTIVATION_SCHEMA
        or payload.get("schema_version") != ACTIVATION_VERSION
    ):
        raise ExpandedNationsError(f"Unsupported activation manifest: {path}")
    if not isinstance(payload.get("files"), list):
        raise ExpandedNationsError(
            f"Activation manifest files must be a list: {path}"
        )
    mode = manifest_activation_mode(payload)
    if mode == ACTIVATION_MODE_CODEX_PASSTHROUGH:
        if payload["files"]:
            raise ExpandedNationsError(
                f"Code:X passthrough activation must not manage projection files: {path}"
            )
    elif not payload["files"]:
        raise ExpandedNationsError(
            f"Activation manifest has no managed files: {path}"
        )
    return payload


def verify_manifest_files(root: Path, manifest: Mapping[str, Any]) -> None:
    mode = manifest_activation_mode(manifest)
    if mode == ACTIVATION_MODE_CODEX_PASSTHROUGH:
        if manifest.get("files"):
            raise ExpandedNationsError(
                "Code:X passthrough activation must not manage projection files"
            )
        occupied = [
            path
            for path in all_managed_candidates(root)
            if path.is_file()
            and GENERATED_MARKER
            in path.read_text(encoding="utf-8-sig", errors="replace")
        ]
        if occupied:
            raise ExpandedNationsError(
                "Code:X passthrough activation found leftover managed projection files: "
                + ", ".join(str(path) for path in occupied)
            )
        return
    allowed_paths = set(managed_relatives_for_manifest(manifest))
    allowed_paths.update(_manifest_presentation_relatives(manifest))
    allowed_paths.update(_manifest_breed_relatives(manifest))
    allowed = {item.as_posix() for item in allowed_paths}
    rows = manifest.get("files", [])
    actual = {str(row.get("relative_path", "")) for row in rows}
    if actual != allowed or len(actual) != len(rows):
        raise ExpandedNationsError(
            "Activation manifest managed-file set is invalid"
        )
    for row in rows:
        target = safe_target(root, str(row["relative_path"]))
        if not target.is_file():
            raise ExpandedNationsError(
                f"Managed projection file is missing: {target}"
            )
        data = target.read_bytes()
        if (
            sha256_bytes(data) != row.get("sha256")
            or len(data) != int(row.get("byte_count", -1))
        ):
            raise ExpandedNationsError(
                f"Managed projection file was modified: {target}"
            )
