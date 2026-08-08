from __future__ import annotations

import prepare_wrapper_engine_test as target


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


target.WRAPPERS = qualified_wrappers()


if __name__ == "__main__":
    raise SystemExit(target.main())
