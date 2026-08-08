from __future__ import annotations

import prepare_wrapper_engine_test as target
from gates_of_codex.scenario import load_bundled_scenario as load_base_scenario
from gates_of_codex.strategic import ensure_strategic_layer


def qualified_wrappers() -> dict[str, tuple[str, int]]:
    """Return the exact native unit IDs committed in the Gates wrapper set.

    The catalog and GoH source definitions retain their tactical-side suffixes,
    such as ``goc_ildu_rifle(ukr)``. The first audit runner accidentally used
    display-style base names, causing a correct fail-closed catalog miss.
    """

    qualified: dict[str, tuple[str, int]] = {}
    for name, (side, count) in target.WRAPPERS.items():
        expected_suffix = f"({side})"
        if name.endswith(expected_suffix):
            exact_name = name
        elif "(" in name or ")" in name:
            raise ValueError(f"Malformed wrapper identifier: {name}")
        else:
            exact_name = f"{name}{expected_suffix}"
        if exact_name in qualified:
            raise ValueError(f"Duplicate wrapper identifier: {exact_name}")
        qualified[exact_name] = (side, count)
    return qualified


def load_migrated_scenario():
    """Load the bundled schema-3 campaign and install its strategic layer.

    ``prepare_wrapper_engine_test`` selects strategic formations before it
    constructs ``CampaignEngine``. Production normally performs this migration
    when the engine is constructed, so the audit runner must invoke the same
    deterministic migration first rather than assuming formations already exist.
    """

    state = load_base_scenario()
    ensure_strategic_layer(state)
    state.validate()
    return state


target.WRAPPERS = qualified_wrappers()
target.load_bundled_scenario = load_migrated_scenario


if __name__ == "__main__":
    raise SystemExit(target.main())
