"""Gate 0 benchmark harness for pinned OpenGS Map Tool generation logic.

This script does not vendor or modify OpenGS generation code. It imports the
pinned upstream checkout, supplies synthetic aligned inputs, and measures the
existing raster generation functions. Synthetic inputs measure feasibility and
failure behavior only. They do not establish geographic quality or provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import tracemalloc
import types
from typing import Any

PINNED_COMMIT = "06e7ec8517bd45872cf44d77cb8784e5ffca49bb"
PINNED_REPOSITORY = "Thomas-Holtvedt/opengs-maptool"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_upstream(upstream_root: Path) -> str:
    required = (
        upstream_root / "config.py",
        upstream_root / "logic" / "numb_gen.py",
        upstream_root / "logic" / "utils.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"upstream checkout is missing required files: {missing}")

    try:
        result = subprocess.run(
            ["git", "-C", str(upstream_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("unable to verify upstream Git commit") from exc

    commit = result.stdout.strip()
    if commit != PINNED_COMMIT:
        raise RuntimeError(
            f"wrong OpenGS commit: expected {PINNED_COMMIT}, got {commit}"
        )
    return commit


def _install_pyqt_stub() -> None:
    """Satisfy the upstream utils import without introducing GUI behavior."""

    if "PyQt6.QtWidgets" in sys.modules:
        return

    pyqt6 = types.ModuleType("PyQt6")
    widgets = types.ModuleType("PyQt6.QtWidgets")

    class QApplication:
        @staticmethod
        def processEvents() -> None:
            return None

    widgets.QApplication = QApplication
    pyqt6.QtWidgets = widgets
    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtWidgets"] = widgets


def _load_upstream(upstream_root: Path):
    _install_pyqt_stub()
    sys.path.insert(0, str(upstream_root))
    importlib.invalidate_caches()
    config = importlib.import_module("config")
    utils = importlib.import_module("logic.utils")
    number_module = importlib.import_module("logic.numb_gen")
    return config, utils, number_module.NumberSeries


def _synthetic_inputs(config, width: int, height: int):
    import numpy as np
    from PIL import Image, ImageDraw

    pixels = np.full((height, width, 3), config.OCEAN_COLOR, dtype=np.uint8)
    land_image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(land_image)

    sx = width / 1200.0
    sy = height / 800.0

    def point(x: int, y: int) -> tuple[int, int]:
        return int(round(x * sx)), int(round(y * sy))

    mainland = [
        point(90, 120),
        point(250, 70),
        point(390, 100),
        point(520, 55),
        point(700, 95),
        point(850, 150),
        point(1020, 180),
        point(1110, 310),
        point(1040, 520),
        point(880, 650),
        point(650, 700),
        point(430, 650),
        point(300, 560),
        point(180, 480),
        point(100, 330),
    ]
    draw.polygon(mainland, fill=(220, 220, 220))
    draw.ellipse((*point(30, 200), *point(85, 260)), fill=(220, 220, 220))
    draw.ellipse((*point(1080, 90), *point(1140, 150)), fill=(220, 220, 220))

    density = np.full((height, width), 160.0, dtype=np.float64)
    yy, xx = np.mgrid[0:height, 0:width]
    for center_x, center_y, sigma, depth in (
        (450, 300, 150, 120),
        (700, 350, 170, 105),
        (850, 450, 130, 90),
    ):
        cx = center_x * sx
        cy = center_y * sy
        scaled_sigma = sigma * min(sx, sy)
        gaussian = np.exp(
            -((xx - cx) ** 2 + (yy - cy) ** 2)
            / (2.0 * scaled_sigma * scaled_sigma)
        )
        density -= depth * gaussian
    density = np.clip(density, 0, 255).astype(np.uint8)
    return land_image, density


def _distribute(territories, total_provinces, pixel_counts, density_weights):
    n = len(territories)
    if n == 0 or total_provinces <= 0:
        return [0] * n

    weighted_pixels = [
        pixel_counts.get(row["_pmap_index"], 0)
        * density_weights.get(row["_pmap_index"], 1.0)
        for row in territories
    ]
    total_pixels = sum(weighted_pixels)
    if total_pixels == 0:
        return [1] * n

    allocation = [
        max(1, round(value / total_pixels * total_provinces))
        for value in weighted_pixels
    ]
    difference = sum(allocation) - total_provinces
    if difference != 0 and total_provinces >= n:
        indices = sorted(
            range(n),
            key=lambda index: weighted_pixels[index],
            reverse=difference > 0,
        )
        for index in indices:
            if difference == 0:
                break
            if difference > 0 and allocation[index] > 1:
                allocation[index] -= 1
                difference -= 1
            elif difference < 0:
                allocation[index] += 1
                difference += 1
    return allocation


def _run_generation(upstream_root: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    config, utils, NumberSeries = _load_upstream(upstream_root)
    width = int(scenario["width"])
    height = int(scenario["height"])
    density_strength = float(scenario.get("density_strength", 2.0))
    jagged = bool(scenario.get("jagged", False))

    land_image, density = _synthetic_inputs(config, width, height)
    masks = utils.extract_masks(None, land_image)

    utils.clear_used_colors()
    territory_series = NumberSeries(
        config.TERRITORY_ID_PREFIX,
        config.TERRITORY_ID_START,
        config.TERRITORY_ID_END,
    )
    land_map, land_metadata, next_index = utils.create_region_map(
        masks["land_fill"],
        masks["land_border"],
        int(scenario["land_territories"]),
        0,
        "land",
        territory_series,
        "territory_id",
        "territory_type",
        density=density,
        density_strength=density_strength,
        jagged=jagged,
    )
    ocean_map, ocean_metadata, _ = utils.create_region_map(
        masks["sea_fill"],
        masks["sea_border"],
        int(scenario["ocean_territories"]),
        next_index,
        "ocean",
        territory_series,
        "territory_id",
        "territory_type",
        density=density,
        density_strength=density_strength,
        jagged=jagged,
    )
    territory_metadata = land_metadata + ocean_metadata
    _, territory_labels = utils.combine_maps(
        land_map,
        ocean_map,
        territory_metadata,
        masks["land_mask"],
        masks["sea_mask"],
    )

    unique_labels, pixel_totals = np.unique(
        territory_labels[territory_labels >= 0], return_counts=True
    )
    pixel_counts = dict(zip(unique_labels.tolist(), pixel_totals.tolist()))
    density_weights: dict[int, float] = {}
    for label in unique_labels:
        territory_mask = territory_labels == label
        mean_value = density[territory_mask].mean()
        density_weights[int(label)] = (256.0 - mean_value) ** density_strength

    land_rows = [
        row for row in territory_metadata if row["territory_type"] == "land"
    ]
    ocean_rows = [
        row for row in territory_metadata if row["territory_type"] == "ocean"
    ]
    land_allocation = _distribute(
        land_rows,
        int(scenario["land_provinces"]),
        pixel_counts,
        density_weights,
    )
    ocean_allocation = _distribute(
        ocean_rows,
        int(scenario["ocean_provinces"]),
        pixel_counts,
        density_weights,
    )

    province_labels = np.full((height, width), -1, np.int32)
    utils.clear_used_colors()
    province_series = NumberSeries(
        config.PROVINCE_ID_PREFIX,
        config.PROVINCE_ID_START,
        config.PROVINCE_ID_END,
    )
    province_metadata: list[dict[str, Any]] = []
    start_index = 0

    for territory, province_count in (
        list(zip(land_rows, land_allocation))
        + list(zip(ocean_rows, ocean_allocation))
    ):
        territory_mask = territory_labels == territory["_pmap_index"]
        local_labels, local_metadata, next_start = utils.create_region_map(
            territory_mask,
            np.zeros((height, width), dtype=bool),
            province_count,
            start_index,
            territory["territory_type"],
            province_series,
            "province_id",
            "province_type",
            density=density,
            density_strength=density_strength,
            jagged=jagged,
        )
        valid = (local_labels >= 0) & (province_labels < 0)
        province_labels[valid] = local_labels[valid]
        for row in local_metadata:
            row["territory_id"] = territory["territory_id"]
        province_metadata.extend(local_metadata)
        start_index = next_start

    canonical_metadata = [
        {
            "province_id": row["province_id"],
            "province_type": row["province_type"],
            "territory_id": row["territory_id"],
            "R": int(row["R"]),
            "G": int(row["G"]),
            "B": int(row["B"]),
            "x": round(float(row["x"]), 8),
            "y": round(float(row["y"]), 8),
            "label": int(row["_pmap_index"]),
        }
        for row in province_metadata
    ]

    return {
        "territory_count": len(territory_metadata),
        "province_count": len(province_metadata),
        "land_requested": int(scenario["land_provinces"]),
        "ocean_requested": int(scenario["ocean_provinces"]),
        "land_pixels": int(masks["land_mask"].sum()),
        "ocean_pixels": int(masks["sea_mask"].sum()),
        "province_label_sha256": _sha256_bytes(province_labels.tobytes()),
        "province_metadata_sha256": _sha256_bytes(
            _json_bytes(canonical_metadata)
        ),
    }


def _peak_rss() -> tuple[int | None, str]:
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform == "darwin":
            return value, "resource_ru_maxrss_bytes"
        return value * 1024, "resource_ru_maxrss_kib"
    except (ImportError, OSError):
        try:
            import psutil

            value = int(psutil.Process(os.getpid()).memory_info().rss)
            return value, "psutil_final_rss_bytes"
        except (ImportError, OSError):
            return None, "unavailable"


def _worker(args: argparse.Namespace) -> int:
    scenario = json.loads(args.scenario_json)
    upstream_root = Path(args.upstream_root).resolve()
    commit = _verify_upstream(upstream_root)

    tracemalloc.start()
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    error = None
    result: dict[str, Any] = {}
    try:
        result = _run_generation(upstream_root, scenario)
    except Exception as exc:  # benchmark must preserve the failure in output
        error = f"{type(exc).__name__}: {exc}"
    wall_seconds = time.perf_counter() - started_wall
    cpu_seconds = time.process_time() - started_cpu
    _, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_rss_bytes, peak_rss_source = _peak_rss()

    payload = {
        "scenario_id": scenario["id"],
        "upstream_commit": commit,
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
        "tracemalloc_peak_bytes": traced_peak,
        "peak_rss_bytes": peak_rss_bytes,
        "peak_rss_source": peak_rss_source,
        "error": error,
        **result,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if error is None else 1


def _run_suite(args: argparse.Namespace) -> int:
    upstream_root = Path(args.upstream_root).resolve()
    commit = _verify_upstream(upstream_root)
    suite_path = Path(args.scenarios).resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8"))

    results: list[dict[str, Any]] = []
    any_failure = False
    for scenario in suite["scenarios"]:
        repeats = int(scenario.get("repeats", 1))
        for repeat_index in range(repeats):
            worker_command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--upstream-root",
                str(upstream_root),
                "--scenario-json",
                json.dumps(scenario, sort_keys=True),
            ]
            completed = subprocess.run(
                worker_command,
                capture_output=True,
                text=True,
            )
            stdout_lines = [
                line for line in completed.stdout.splitlines() if line.strip()
            ]
            if not stdout_lines:
                payload = {
                    "scenario_id": scenario["id"],
                    "repeat_index": repeat_index,
                    "error": completed.stderr.strip() or "worker returned no JSON",
                }
                any_failure = True
            else:
                payload = json.loads(stdout_lines[-1])
                payload["repeat_index"] = repeat_index
                if completed.returncode != 0 or payload.get("error"):
                    any_failure = True
            results.append(payload)
            print(json.dumps(payload, sort_keys=True), flush=True)

    hash_sets: dict[str, list[str]] = {}
    for row in results:
        label_hash = row.get("province_label_sha256")
        if label_hash:
            hash_sets.setdefault(row["scenario_id"], []).append(label_hash)

    repeat_analysis = {
        scenario_id: {
            "run_count": len(hashes),
            "unique_label_hash_count": len(set(hashes)),
            "nondeterministic_observed": len(set(hashes)) > 1,
        }
        for scenario_id, hashes in sorted(hash_sets.items())
    }

    output = {
        "schema": "gates-of-codex.opengs-gate0-benchmark-result",
        "schema_version": 1,
        "status": "provisional_generator_feasibility",
        "source_repository": PINNED_REPOSITORY,
        "source_commit": commit,
        "synthetic_inputs": True,
        "geographic_quality_evaluated": False,
        "production_replacement_authorized": False,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "suite_sha256": _sha256_bytes(suite_path.read_bytes()),
        "results": results,
        "repeat_analysis": repeat_analysis,
    }
    output["result_sha256"] = _sha256_bytes(_json_bytes(output))

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 1 if any_failure else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument(
        "--scenarios",
        default=str(Path(__file__).with_name("benchmark_scenarios.json")),
    )
    parser.add_argument(
        "--output",
        default="build/opengs_eval/gate0_benchmark.json",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scenario-json", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.worker:
        if not args.scenario_json:
            raise SystemExit("--worker requires --scenario-json")
        return _worker(args)
    return _run_suite(args)


if __name__ == "__main__":
    raise SystemExit(main())
