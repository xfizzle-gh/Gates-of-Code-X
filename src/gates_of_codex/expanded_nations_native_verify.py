from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Mapping

from .expanded_nations_actor_sources import (
    defined_macro_name,
    effective_purchase_id,
)
from .expanded_nations_models import (
    ExpandedNationsError,
    MANIFEST_RELATIVE,
    UNITS_RELATIVE,
    safe_target,
    sha256_bytes,
)
from .expanded_nations_verify import (
    load_manifest,
    verify_manifest_files,
    verify_projection_artifacts as _verify_projection_artifacts,
)
from .goh_source import SourceEntry, scan_source_entries

__all__ = [
    "load_manifest",
    "verify_actor_projection_files",
    "verify_manifest_files",
    "verify_projection_artifacts",
]


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
    """Verify native macro IDs while reusing the strict legacy artifact checks.

    The existing semantic verifier expects each parsed entry name to equal the
    manifest purchase ID. Native top-level squad macros instead store a base
    ``name(...)`` and derive the effective ID from their ``side(...)`` call.
    Source-local ``{define ...}`` declarations are runtime dependencies rather
    than purchases. This adapter authenticates both contracts, then creates an
    in-memory verification view containing purchase definitions only. The files
    written to disk are never altered.
    """

    verification_outputs, verification_manifest = _legacy_verification_view(
        outputs,
        manifest,
    )
    _verify_projection_artifacts(
        verification_outputs,
        verification_manifest,
    )


def _legacy_verification_view(
    outputs: Mapping[Path, bytes],
    manifest: Mapping[str, Any],
) -> tuple[dict[Path, bytes], dict[str, Any]]:
    if UNITS_RELATIVE not in outputs:
        raise ExpandedNationsError("Projection is missing the actor-unit artifact")

    actor_text = outputs[UNITS_RELATIVE].decode("utf-8-sig")
    actor_scan = scan_source_entries(actor_text, UNITS_RELATIVE.as_posix())
    if actor_scan.diagnostics:
        raise ExpandedNationsError("Generated actor unit file is malformed")

    define_entries = [
        entry for entry in actor_scan.entries if _is_define_entry(entry)
    ]
    purchase_entries = [
        entry for entry in actor_scan.entries if not _is_define_entry(entry)
    ]
    define_names = [defined_macro_name(entry.raw) for entry in define_entries]
    if any(not name for name in define_names):
        raise ExpandedNationsError(
            "Generated actor unit file contains an unnamed source-local define"
        )
    if len(define_names) != len(set(define_names)):
        raise ExpandedNationsError(
            "Generated actor unit file contains duplicate source-local defines"
        )
    if purchase_entries and any(
        entry.location.line > purchase_entries[0].location.line
        for entry in define_entries
    ):
        raise ExpandedNationsError(
            "Generated source-local defines must precede actor purchases"
        )

    actor_rows = manifest.get("units")
    if not isinstance(actor_rows, list):
        raise ExpandedNationsError("Activation manifest units must be a list")
    if len(purchase_entries) != len(actor_rows):
        raise ExpandedNationsError(
            "Generated actor unit count does not match activation manifest"
        )

    side = str(manifest.get("tactical_side", "")).lower()
    transformed = actor_text
    for entry in define_entries:
        if entry.raw not in transformed:
            raise ExpandedNationsError(
                "Could not construct purchase-only verification view"
            )
        transformed = transformed.replace(entry.raw, "", 1)

    for entry, row in zip(purchase_entries, actor_rows, strict=True):
        canonical = str(row.get("unit_name", ""))
        actual = effective_purchase_id(entry, side)
        if actual != canonical:
            raise ExpandedNationsError(
                "Generated actor unit does not represent its manifest purchase ID: "
                f"expected={canonical}; actual={actual}"
            )
        if entry.form != "macro":
            continue
        pattern = re.compile(
            r"\bname\s*\(\s*" + re.escape(entry.name) + r"\s*\)",
            re.IGNORECASE,
        )
        transformed, count = pattern.subn(
            f"name({canonical})",
            transformed,
            count=1,
        )
        if count != 1:
            raise ExpandedNationsError(
                f"Could not construct verification view for native squad {canonical}"
            )

    transformed_bytes = transformed.encode("utf-8")
    verification_outputs = dict(outputs)
    verification_outputs[UNITS_RELATIVE] = transformed_bytes

    verification_manifest = deepcopy(dict(manifest))
    file_rows = verification_manifest.get("files")
    if not isinstance(file_rows, list):
        raise ExpandedNationsError("Activation manifest files must be a list")
    unit_path = UNITS_RELATIVE.as_posix()
    matches = [
        row for row in file_rows if str(row.get("relative_path", "")) == unit_path
    ]
    if len(matches) != 1:
        raise ExpandedNationsError(
            "Activation manifest must contain one actor-unit artifact row"
        )
    matches[0]["sha256"] = sha256_bytes(transformed_bytes)
    matches[0]["byte_count"] = len(transformed_bytes)
    return verification_outputs, verification_manifest


def _is_define_entry(entry: SourceEntry) -> bool:
    return entry.form == "block" and entry.name.lower() == "define"
