from __future__ import annotations

from .codex.catalog import CodeXCatalog
from .models import CampaignState
from .presentation import (
    category_icon,
    portrait_key,
    readable_unit_name,
    unit_presentation_from_catalog,
)


def register_materialized_presentations(
    state: CampaignState,
    catalog: CodeXCatalog,
) -> None:
    presentations = state.map_metadata.setdefault("unit_presentations", {})
    units = catalog.units.raw_values() if hasattr(catalog.units, "raw_values") else catalog.units.values()
    for unit in units:
        group_presentation = unit_presentation_from_catalog(unit)
        presentations[unit.name] = group_presentation
        for object_name in sorted(set(unit.members) | set(unit.vehicles)):
            presentation = dict(group_presentation)
            presentation["display_name"] = readable_unit_name(object_name)
            presentation["portrait_key"] = portrait_key(object_name)
            presentation["category_icon"] = category_icon(unit.category)
            presentation["catalog_unit"] = unit.name
            presentations[object_name] = presentation
