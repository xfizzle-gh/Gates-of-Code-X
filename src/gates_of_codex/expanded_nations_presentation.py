from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .expanded_nations_models import (
    ExpandedNationsError,
    PORTRAIT_ROOT_RELATIVE,
)

_SERBIA_PORTRAIT_SOURCES: Mapping[str, str] = {
    "goc_serb_rifle(rusa)": "rus4_inf_rifle",
    "goc_serb_at(rusa)": "rus4_inf_rifle_at",
    "goc_serb_recon(rusa)": "rus4_inf_razv",
}

# Exact installed Code:X probing proved that these six source-side Ukraine card
# families own four native portraits each. Spain projects the purchases onto
# tactical side NATO, so the native UI looks for the same card stem with a
# ``(nato)`` suffix. Copy source bytes exactly; do not synthesize placeholder art.
_SPAIN_PORTRAIT_SOURCES: Mapping[str, str] = {
    "3rd_assault_at(nato)": "3rd_assault_at(ukr)",
    "3rd_assault_decepticons(nato)": "3rd_assault_decepticons(ukr)",
    "3rd_assault_javelin(nato)": "3rd_assault_javelin(ukr)",
    "3rd_assault_mg3(nato)": "3rd_assault_mg3(ukr)",
    "3rd_assault_saperi(nato)": "3rd_assault_saperi(ukr)",
    "3rd_assault_saperi_at(nato)": "3rd_assault_saperi_at(ukr)",
}


def project_actor_presentation(
    actor: Mapping[str, Any],
    roots: Sequence[Path],
) -> dict[Path, bytes]:
    """Materialize actor-specific squad portraits from the installed stack.

    Portrait source bytes remain owned by the installed upstream mod. The
    activation transaction copies only the actor-specific card families needed
    by the active projection, records their hashes in the activation manifest,
    and removes them when another actor/Core mode replaces the projection.
    """

    actor_id = str(actor.get("actor_id", ""))
    if actor_id == "srb":
        sources = _SERBIA_PORTRAIT_SOURCES
        label = "Serbia"
    elif actor_id == "esp":
        sources = _SPAIN_PORTRAIT_SOURCES
        label = "Spain"
    else:
        return {}

    actor_units = {str(row.get("unit_name", "")) for row in actor.get("units", [])}
    expected = set(sources)
    selected = expected & actor_units
    if not selected:
        return {}
    if selected != expected:
        missing = sorted(expected - selected)
        raise ExpandedNationsError(
            f"{label} presentation requires all canonical projected card families; missing={missing}"
        )

    outputs: dict[Path, bytes] = {}
    for target_unit, source_stem in sorted(sources.items()):
        for index in range(4):
            source_name = f"{source_stem}_{index:02d}.png"
            source = _effective_portrait(source_name, roots)
            if source is None:
                raise ExpandedNationsError(
                    f"{label} presentation cannot resolve installed portrait {source_name}"
                )
            relative = PORTRAIT_ROOT_RELATIVE / f"{target_unit}_{index:02d}.png"
            data = source.read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ExpandedNationsError(
                    f"{label} presentation source is not a PNG: {source}"
                )
            outputs[relative] = data
    return outputs


def _effective_portrait(name: str, roots: Sequence[Path]) -> Path | None:
    candidates = [name]
    match = name.rsplit("_", 1)
    if len(match) == 2 and match[1].lower().endswith(".png"):
        candidates.append(f"{match[0]}(rusa)_{match[1]}")
    for root in reversed(roots):
        portrait_root = (
            root
            / "resource"
            / "interface"
            / "scene"
            / "portrait_squad"
        )
        for candidate_name in candidates:
            candidate = portrait_root / candidate_name
            if candidate.is_file():
                return candidate
    return None
