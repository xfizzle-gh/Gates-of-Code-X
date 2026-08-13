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
_ACTIVE_RESEARCH_LOCALIZATION_RELATIVE = Path(
    "localizations/default/interface/text/dcg_research_goc_active_actor.pot"
)


def project_actor_presentation(
    actor: Mapping[str, Any],
    roots: Sequence[Path],
) -> dict[Path, bytes]:
    """Materialize actor-specific Conquest presentation from the installed stack.

    Every activated Expanded Nations actor receives an actor-scoped Dynamic
    Conquest research localization catalog. This is generated from the normalized
    research graph, after native purchase IDs have been finalized, so qualified
    ``goc_*`` purchase IDs cannot fall through to ``???`` on the research page.

    Portrait source bytes remain owned by the installed upstream mod. The
    activation transaction copies only explicitly approved actor-specific card
    families, records their hashes in the activation manifest, and removes them
    when another actor/Core mode replaces the projection.

    Spain intentionally has no special portrait projection here. Owner #194
    review replaced the old Azov/3rd Assault allocation with compatibility-only
    ILDU wrappers. Squad localization is committed separately; research
    localization is generated here from the active normalized actor.
    """

    outputs: dict[Path, bytes] = {}
    if actor.get("research_nodes"):
        outputs[_ACTIVE_RESEARCH_LOCALIZATION_RELATIVE] = (
            render_actor_research_localization(actor).encode("utf-8")
        )

    actor_id = str(actor.get("actor_id", ""))
    if actor_id != "srb":
        return outputs

    sources = _SERBIA_PORTRAIT_SOURCES
    label = "Serbia"
    actor_units = {str(row.get("unit_name", "")) for row in actor.get("units", [])}
    expected = set(sources)
    selected = expected & actor_units
    if not selected:
        return outputs
    if selected != expected:
        missing = sorted(expected - selected)
        raise ExpandedNationsError(
            f"{label} presentation requires all canonical projected card families; missing={missing}"
        )

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


def render_actor_research_localization(actor: Mapping[str, Any]) -> str:
    """Render ``dcg/research`` labels for every final purchase ID in an actor.

    ``normalize_actor_purchase_ids`` rewrites each research node's unlock list to
    the exact native engine identity before this renderer is called. Using those
    normalized IDs avoids the failure mode where the recruitment card is named
    but the same side-qualified unit renders as ``???`` in Dynamic Conquest's
    research page.
    """

    actor_id = str(actor.get("actor_id", "")).strip()
    display_name = str(actor.get("display_name", actor_id)).strip() or actor_id
    lines = [
        'msgid ""',
        'msgstr ""',
        f'"Project-Id-Version: Gates of Code:X { _po_escape(display_name) } Research\\n"',
        '"Language: en\\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        "",
    ]

    seen: set[str] = set()
    for node in actor.get("research_nodes", []):
        unlocks = [str(item).strip() for item in node.get("unlock_units", [])]
        if not unlocks:
            continue
        if len(unlocks) != 1:
            raise ExpandedNationsError(
                f"Research localization node {node.get('key', '')} unlocks multiple purchases"
            )
        engine_id = unlocks[0]
        if not engine_id:
            raise ExpandedNationsError(
                f"Research localization node {node.get('key', '')} has an empty purchase ID"
            )
        if engine_id in seen:
            raise ExpandedNationsError(
                f"Research localization contains duplicate purchase ID {engine_id}"
            )
        seen.add(engine_id)

        label = str(node.get("display_name", "")).strip()
        if not label or label == "???":
            raise ExpandedNationsError(
                f"Research localization for {engine_id} has no readable display name"
            )
        lines.extend(
            [
                f'msgctxt "dcg/research/{_po_escape(engine_id)}"',
                f'msgid "{_po_escape(label)}"',
                'msgstr ""',
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def _po_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _effective_portrait(name: str, roots: Sequence[Path]) -> Path | None:
    candidates = [name]
    match = name.rsplit("_", 1)
    if len(match) == 2 and match[1].lower().endswith(".png"):
        candidates.append(f"{match[0]}({match[1] if False else 'rusa'})_{match[1]}")
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
