"""Benchmark pinned OpenGS generation against aligned Natural Earth inputs.

This is Gate 0 research. It invokes the pinned upstream territory and province
generation functions with a minimal non-GUI layout object. It does not fork or
modify the generator and does not emit a Gates production map.
"""

from __future__ import annotations

import argparse
from collections import Counter
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

from PIL import Image

PINNED_COMMIT = "06e7ec8517bd45872cf44d77cb8784e5ffca49bb"
PINNED_REPOSITORY = "Thomas-Holtvedt/opengs-maptool"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _verify_upstream(upstream_root: Path) -> str:
    required = (
        upstream_root / "config.py",
        upstream_root / "logic" / "utils.py",
        upstream_root / "logic" / "territory_generator.py",
        upstream_root / "logic" / "province_generator.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"upstream checkout is missing required files: {missing}")
    completed = subprocess.run(
        ["git", "-C", str(upstream_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    if commit != PINNED_COMMIT:
        raise RuntimeError(
            f"wrong OpenGS commit: expected {PINNED_COMMIT}, got {commit}"
        )
    return commit


def _install_pyqt_stub() -> None:
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


class _Progress:
    def __init__(self) -> None:
        self.visible = False
        self.value = 0

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def setValue(self, value: int) -> None:
        self.value = int(value)


class _Button:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _ImageDisplay:
    def __init__(self, image: Image.Image | None = None) -> None:
        self.image = image

    def get_image(self) -> Image.Image | None:
        return self.image

    def set_image(self, image: Image.Image) -> None:
        self.image = image


class _Value:
    def __init__(self, value: int) -> None:
        self._value = int(value)

    def value(self) -> int:
        return self._value


class _Check:
    def __init__(self, checked: bool) -> None:
        self._checked = bool(checked)

    def isChecked(self) -> bool:
        return self._checked


class _BenchmarkLayout:
    def __init__(
        self,
        land_image: Image.Image,
        boundary_image: Image.Image,
        density_image: Image.Image,
        scenario: dict[str, Any],
    ) -> None:
        self.progress = _Progress()
        self.land_image_display = _ImageDisplay(land_image)
        self.boundary_image_display = _ImageDisplay(boundary_image)
        self.density_image = density_image
        self.terrain_image = None

        self.territory_density_strength = _Value(
            int(round(float(scenario.get("territory_density_strength", 2.0)) * 10.0))
        )
        self.territory_exclude_ocean_density = _Check(
            bool(scenario.get("territory_exclude_ocean_density", True))
        )
        self.territory_jagged_land = _Check(
            bool(scenario.get("jagged_land", False))
        )
        self.territory_jagged_ocean = _Check(
            bool(scenario.get("jagged_ocean", False))
        )
        self.territory_land_slider = _Value(
            int(scenario["land_territories"])
        )
        self.territory_ocean_slider = _Value(
            int(scenario["ocean_territories"])
        )

        self.province_density_strength = _Value(
            int(round(float(scenario.get("province_density_strength", 2.0)) * 10.0))
        )
        self.province_exclude_ocean_density = _Check(
            bool(scenario.get("province_exclude_ocean_density", True))
        )
        self.province_jagged_land = _Check(
            bool(scenario.get("jagged_land", False))
        )
        self.province_jagged_ocean = _Check(
            bool(scenario.get("jagged_ocean", False))
        )
        self.land_slider = _Value(int(scenario["land_provinces"]))
        self.ocean_slider = _Value(int(scenario["ocean_provinces"]))

        self.territory_image_display = _ImageDisplay()
        self.province_image_display = _ImageDisplay()
        self.button_gen_prov = _Button()
        self.button_exp_terr_img = _Button()
        self.button_exp_terr_def = _Button()
        self.button_exp_prov_img = _Button()
        self.button_exp_prov_def = _Button()
        self.button_exp_terr_hist = _Button()

        self.territory_data = None
        self.territory_pmap = None
        self.cached_masks = None
        self.province_data = None


def _load_upstream(upstream_root: Path):
    _install_pyqt_stub()
    sys.path.insert(0, str(upstream_root))
    importlib.invalidate_caches()
    territory_module = importlib.import_module("logic.territory_generator")
    province_module = importlib.import_module("logic.province_generator")
    return territory_module, province_module


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

            return (
                int(psutil.Process(os.getpid()).memory_info().rss),
                "psutil_final_rss_bytes",
            )
        except (ImportError, OSError):
            return None, "unavailable"


def _load_inputs(input_root: Path):
    manifest_path = input_root / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = {
        "land": input_root / "land.png",
        "boundary": input_root / "boundary.png",
        "density": input_root / "density.png",
    }
    for name, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f"missing {name} input: {path}")
        expected = str(manifest["outputs"][path.name]["sha256"])
        actual = _sha256_file(path)
        if actual != expected:
            raise RuntimeError(
                f"input checksum mismatch for {path.name}: expected {expected}, got {actual}"
            )
    land = Image.open(paths["land"]).convert("RGB")
    boundary = Image.open(paths["boundary"]).convert("RGB")
    density = Image.open(paths["density"]).convert("L")
    if land.size != boundary.size or land.size != density.size:
        raise RuntimeError("real input image dimensions do not match")
    return manifest, land, boundary, density


def _canonical_metadata(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical = []
    for row in rows:
        canonical.append(
            {
                "province_id": str(row.get("province_id", "")),
                "province_type": str(row.get("province_type", "")),
                "territory_id": str(row.get("territory_id", "")),
                "R": int(row.get("R", 0)),
                "G": int(row.get("G", 0)),
                "B": int(row.get("B", 0)),
                "x": round(float(row.get("x", 0.0)), 8),
                "y": round(float(row.get("y", 0.0)), 8),
                "pmap_index": int(row.get("_pmap_index", -1)),
                "province_terrain": str(row.get("province_terrain", "")),
            }
        )
    return canonical


def _run_once(
    upstream_root: Path,
    input_root: Path,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    territory_module, province_module = _load_upstream(upstream_root)
    input_manifest, land, boundary, density = _load_inputs(input_root)
    layout = _BenchmarkLayout(land, boundary, density, scenario)

    territory_image, territory_rows = territory_module.generate_territory_map(
        layout
    )
    province_image, province_rows = province_module.generate_province_map(layout)

    type_counts = Counter(
        str(row.get("province_type", "unknown")) for row in province_rows
    )
    terrain_counts = Counter(
        str(row.get("province_terrain", "unknown")) for row in province_rows
    )
    unique_colors = {
        (
            int(row.get("R", 0)),
            int(row.get("G", 0)),
            int(row.get("B", 0)),
        )
        for row in province_rows
    }
    canonical = _canonical_metadata(province_rows)
    requested_base = int(scenario["land_provinces"]) + int(
        scenario["ocean_provinces"]
    )
    lake_components = int(
        input_manifest["pixel_counts"]["lake_connected_components"]
    )
    missing_lake_parents = sum(
        1
        for row in province_rows
        if row.get("province_type") == "lake"
        and not str(row.get("territory_id", ""))
    )

    return {
        "input_manifest_sha256": _sha256_file(
            input_root / "input_manifest.json"
        ),
        "input_source_commit": str(input_manifest["source_commit"]),
        "input_width": int(input_manifest["width"]),
        "input_height": int(input_manifest["height"]),
        "requested_land_provinces": int(scenario["land_provinces"]),
        "requested_ocean_provinces": int(scenario["ocean_provinces"]),
        "requested_base_provinces": requested_base,
        "input_lake_components": lake_components,
        "actual_province_count": len(province_rows),
        "actual_type_counts": dict(sorted(type_counts.items())),
        "actual_terrain_counts": dict(sorted(terrain_counts.items())),
        "lake_count_delta_from_requested_base": len(province_rows)
        - requested_base,
        "missing_lake_parent_count": missing_lake_parents,
        "territory_count": len(territory_rows),
        "unique_province_color_count": len(unique_colors),
        "province_image_sha256": _sha256_bytes(province_image.tobytes()),
        "territory_image_sha256": _sha256_bytes(territory_image.tobytes()),
        "province_metadata_sha256": _sha256_bytes(
            _canonical_json_bytes(canonical)
        ),
    }


def _worker(args: argparse.Namespace) -> int:
    upstream_root = Path(args.upstream_root).resolve()
    input_root = Path(args.input_root).resolve()
    scenario = json.loads(args.scenario_json)
    commit = _verify_upstream(upstream_root)

    error = None
    result: dict[str, Any] = {}
    tracemalloc.start()
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    try:
        result = _run_once(upstream_root, input_root, scenario)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    wall_seconds = time.perf_counter() - wall_start
    cpu_seconds = time.process_time() - cpu_start
    _, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_bytes, rss_source = _peak_rss()

    payload = {
        "scenario_id": str(scenario["id"]),
        "upstream_commit": commit,
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
        "tracemalloc_peak_bytes": traced_peak,
        "rss_bytes": rss_bytes,
        "rss_source": rss_source,
        "error": error,
        **result,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if error is None else 1


def _run_suite(args: argparse.Namespace) -> int:
    upstream_root = Path(args.upstream_root).resolve()
    input_root = Path(args.input_root).resolve()
    commit = _verify_upstream(upstream_root)
    suite_path = Path(args.scenarios).resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8"))

    results = []
    any_failure = False
    for scenario in suite["scenarios"]:
        for repeat_index in range(int(scenario.get("repeats", 1))):
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--upstream-root",
                str(upstream_root),
                "--input-root",
                str(input_root),
                "--scenario-json",
                json.dumps(scenario, sort_keys=True),
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
            )
            lines = [line for line in completed.stdout.splitlines() if line]
            if not lines:
                payload = {
                    "scenario_id": str(scenario["id"]),
                    "repeat_index": repeat_index,
                    "error": completed.stderr.strip() or "worker returned no JSON",
                }
                any_failure = True
            else:
                payload = json.loads(lines[-1])
                payload["repeat_index"] = repeat_index
                if completed.returncode != 0 or payload.get("error"):
                    payload["worker_stderr"] = completed.stderr.strip()
                    any_failure = True
            results.append(payload)
            print(json.dumps(payload, sort_keys=True), flush=True)

    repeat_analysis = {}
    for scenario in suite["scenarios"]:
        scenario_id = str(scenario["id"])
        rows = [row for row in results if row["scenario_id"] == scenario_id]
        hashes = [
            str(row["province_image_sha256"])
            for row in rows
            if row.get("province_image_sha256")
        ]
        repeat_analysis[scenario_id] = {
            "run_count": len(rows),
            "successful_hash_count": len(hashes),
            "unique_province_image_hash_count": len(set(hashes)),
            "nondeterministic_observed": len(set(hashes)) > 1,
        }

    input_manifest_path = input_root / "input_manifest.json"
    output = {
        "schema": "gates-of-codex.opengs-gate0-real-input-benchmark",
        "schema_version": 1,
        "status": "real_projection_aligned_gate0_evidence",
        "source_repository": PINNED_REPOSITORY,
        "source_commit": commit,
        "input_manifest_sha256": _sha256_file(input_manifest_path),
        "input_manifest": json.loads(
            input_manifest_path.read_text(encoding="utf-8")
        ),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "suite_sha256": _sha256_file(suite_path),
        "results": results,
        "repeat_analysis": repeat_analysis,
        "production_map_replacement_authorized": False,
    }
    output["result_sha256"] = _sha256_bytes(_canonical_json_bytes(output))
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 1 if any_failure else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--scenarios", required=False)
    parser.add_argument(
        "--output",
        default="build/opengs_eval/natural_earth_benchmark.json",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scenario-json", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.worker:
        if not args.scenario_json:
            raise SystemExit("--worker requires --scenario-json")
        return _worker(args)
    if not args.scenarios:
        raise SystemExit("--scenarios is required")
    return _run_suite(args)


if __name__ == "__main__":
    raise SystemExit(main())
