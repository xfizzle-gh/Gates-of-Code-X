#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import gate3_package as _package
from gate3_package import *

_BASE_GATE1_CONTRACT = _package.gate3_masked_gate1_contract


def _masked_extract_masks(land: Any, boundary: Any) -> dict[str, Any]:
    import numpy as np

    outside = np.all(boundary == np.asarray(OUTSIDE_COLOR, dtype=np.uint8), axis=2)
    sea = np.all(land == np.asarray(OCEAN_COLOR, dtype=np.uint8), axis=2) & ~outside
    lake = np.all(land == np.asarray(LAKE_COLOR, dtype=np.uint8), axis=2) & ~outside
    land_mask = ~sea & ~lake & ~outside
    boundary_mask = np.all(boundary == np.asarray(BOUNDARY_COLOR, dtype=np.uint8), axis=2) & ~outside
    return {
        "boundary_mask": boundary_mask,
        "land_mask": land_mask,
        "sea_mask": sea,
        "lake_mask": lake,
        "land_fill": land_mask & ~boundary_mask,
        "land_border": boundary_mask | sea | lake | outside,
        "sea_fill": sea & ~boundary_mask,
        "sea_border": boundary_mask | land_mask | lake | outside,
        "height": int(land.shape[0]),
        "width": int(land.shape[1]),
    }


def _recenter_region_metadata(pmap: Any, metadata: Sequence[Mapping[str, Any]]) -> None:
    import numpy as np

    for item in metadata:
        index = int(item["_pmap_index"])
        ys, xs = np.where(pmap == index)
        if len(xs) == 0:
            raise Gate3Error(f"Gate 3 lake parenting removed every pixel from region index {index}")
        item["x"] = float(int(xs.sum(dtype=np.int64)) / len(xs))
        item["y"] = float(int(ys.sum(dtype=np.int64)) / len(ys))


def _land_seed_territory_masks(
    territories: Sequence[Mapping[str, Any]],
    provinces: Sequence[Mapping[str, Any]],
    territory_masks: Mapping[str, Any],
    province_masks: Mapping[str, Any],
) -> dict[str, Any]:
    import numpy as np

    adjusted = {territory_id: mask.copy() for territory_id, mask in territory_masks.items()}
    if not adjusted:
        return adjusted
    first_mask = next(iter(adjusted.values()))
    lake_union = np.zeros_like(first_mask, dtype=bool)
    for province in provinces:
        if province.get("province_type") == "lake":
            lake_union |= province_masks[str(province["province_id"])]
    for territory in territories:
        if territory.get("territory_type") != "land":
            continue
        territory_id = str(territory["territory_id"])
        adjusted[territory_id] &= ~lake_union
        if not bool(np.any(adjusted[territory_id])):
            raise Gate3Error(
                f"land territory {territory_id} has no non-lake seed-authority pixels"
            )
    return adjusted


@contextmanager
def gate3_masked_gate1_contract() -> Iterator[None]:
    import numpy as np
    import gate1_pipeline

    state: dict[str, Any] = {"lake_mask": None}
    original_package_mask = _package._masked_extract_masks

    def extract_masks_with_lake_parenting(land: Any, boundary: Any) -> dict[str, Any]:
        masks = _masked_extract_masks(land, boundary)
        state["lake_mask"] = masks["lake_mask"].copy()
        return masks

    _package._masked_extract_masks = extract_masks_with_lake_parenting
    try:
        with _BASE_GATE1_CONTRACT():
            original_create_region_map = gate1_pipeline.create_region_map
            original_combine_maps = gate1_pipeline.combine_maps
            original_validate_seed_ledger = gate1_pipeline._validate_seed_ledger

            def create_region_map_with_lake_parenting(
                mask: Any,
                border: Any,
                count: int,
                start_index: int,
                province_type: str,
                series: Any,
                id_key: str,
                type_key: str,
                ledger: Any,
                seed_prefix: str,
                **kwargs: Any,
            ) -> tuple[Any, list[dict[str, Any]], int]:
                effective_border = border
                if seed_prefix == "territory.land":
                    lake_mask = state.get("lake_mask")
                    if lake_mask is None or lake_mask.shape != mask.shape:
                        raise Gate3Error(
                            "Gate 3 lake mask was not captured before land territory generation"
                        )
                    effective_border = np.asarray(border, dtype=bool) | lake_mask
                pmap, metadata, next_index = original_create_region_map(
                    mask,
                    effective_border,
                    count,
                    start_index,
                    province_type,
                    series,
                    id_key,
                    type_key,
                    ledger,
                    seed_prefix,
                    **kwargs,
                )
                if seed_prefix == "territory.land":
                    _recenter_region_metadata(pmap, metadata)
                return pmap, metadata, next_index

            def combine_maps_with_lake_parenting(
                land_map: Any,
                ocean_map: Any,
                metadata: Sequence[Mapping[str, Any]],
                land_mask: Any,
                ocean_mask: Any,
            ) -> tuple[Any, Any]:
                lake_mask = state.get("lake_mask")
                if lake_mask is None or lake_mask.shape != land_mask.shape:
                    raise Gate3Error(
                        "Gate 3 lake mask is unavailable during territory combination"
                    )
                return original_combine_maps(
                    land_map,
                    ocean_map,
                    metadata,
                    np.asarray(land_mask, dtype=bool) | lake_mask,
                    ocean_mask,
                )

            def validate_seed_ledger_with_lake_parenting(
                manifest: dict[str, Any],
                territories: list[dict[str, Any]],
                provinces: list[dict[str, Any]],
                territory_masks: dict[str, Any],
                province_masks: dict[str, Any],
            ) -> None:
                original_validate_seed_ledger(
                    manifest,
                    territories,
                    provinces,
                    _land_seed_territory_masks(
                        territories, provinces, territory_masks, province_masks
                    ),
                    province_masks,
                )

            gate1_pipeline.create_region_map = create_region_map_with_lake_parenting
            gate1_pipeline.combine_maps = combine_maps_with_lake_parenting
            gate1_pipeline._validate_seed_ledger = validate_seed_ledger_with_lake_parenting
            try:
                yield
            finally:
                gate1_pipeline.create_region_map = original_create_region_map
                gate1_pipeline.combine_maps = original_combine_maps
                gate1_pipeline._validate_seed_ledger = original_validate_seed_ledger
    finally:
        _package._masked_extract_masks = original_package_mask


_package._masked_extract_masks = _masked_extract_masks
_package.gate3_masked_gate1_contract = gate3_masked_gate1_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config")
    validate.add_argument("config", type=Path)
    build = subparsers.add_parser("build-inputs")
    build.add_argument("config", type=Path)
    build.add_argument("--natural-earth-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run = subparsers.add_parser("run")
    run.add_argument("config", type=Path)
    run.add_argument("--natural-earth-root", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    inspect = subparsers.add_parser("inspect-output")
    inspect.add_argument("output", type=Path)
    compare = subparsers.add_parser("compare-runs")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "validate-config":
            config, digest, _raw = load_config(arguments.config)
            result = {"ok": True, "candidate_id": config["candidate_id"], "sha256": digest}
        elif arguments.command == "build-inputs":
            result = build_inputs(arguments.config, arguments.natural_earth_root, arguments.output)
        elif arguments.command == "run":
            result = run_pipeline(arguments.config, arguments.natural_earth_root, arguments.output)
        elif arguments.command == "inspect-output":
            result = inspect_package(arguments.output)
        else:
            result = compare_packages(arguments.left, arguments.right)
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except Gate3Error as error:
        print(f"Gate 3 error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
