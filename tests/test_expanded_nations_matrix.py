from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations import (
    activate_actor_projection,
    deactivate_actor_projection,
)
from gates_of_codex.expanded_nations_matrix import (
    _verify_git_exact_head,
    build_projection_matrix,
    invalidated_projection_evidence,
    load_projection_matrix,
    render_projection_matrix_markdown,
    write_projection_matrix_evidence,
)
from gates_of_codex.expanded_nations_models import (
    ACTIVE_RESEARCH_LOCALIZATION_RELATIVE,
    MANIFEST_RELATIVE,
    ExpandedNationsError,
    all_managed_candidates,
)


class ExpandedNationsMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [
            self.root / name
            for name in ("vanilla", "west81", "codex", "ai", "gates")
        ]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)
        self.gates = self.layers[-1]
        self._source(
            2,
            "units_nato.set",
            '{"fra_rifle(nato)" ("squad_with1types_conquest" side(nato) c1(fr_rifle:5))}\n',
        )
        self._source(
            2,
            "units_rusa.set",
            '{"serb_line(rusa)" ("squad_with1types_conquest" side(rusa) c1(Serb_rifleman:5))}\n',
        )
        self.payload = _payload()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _source(self, priority: int, name: str, text: str) -> None:
        path = (
            self.layers[priority]
            / "resource/set/multiplayer/units/conquest"
            / name
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_matrix_exercises_every_playable_actor_and_restores_core(self) -> None:
        matrix = build_projection_matrix(
            self.payload,
            self.layers,
            gates_root=self.gates,
            source_head="fixture-head",
        )
        self.assertEqual("complete", matrix["evidence_state"])
        self.assertEqual("fixture-head", matrix["source_head"])
        self.assertEqual(2, matrix["playable_actor_count"])
        self.assertEqual({"fra", "srb"}, set(matrix["actors"]))
        for row in matrix["actors"].values():
            self.assertEqual(1, row["unit_count"])
            self.assertEqual(1, row["research_node_count"])
            self.assertTrue(row["projection_signature"])
            self.assertEqual(5, len(row["managed_files"]))
            self.assertIn(
                ACTIVE_RESEARCH_LOCALIZATION_RELATIVE.as_posix(),
                row["managed_files"],
            )
        self.assertFalse((self.gates / MANIFEST_RELATIVE).exists())
        self.assertFalse(
            any(path.exists() for path in all_managed_candidates(self.gates))
        )

        json_path = self.root / "matrix.json"
        markdown_path = self.root / "matrix.md"
        write_projection_matrix_evidence(
            matrix,
            json_output=json_path,
            markdown_output=markdown_path,
        )
        self.assertEqual(matrix, load_projection_matrix(json_path))
        markdown = markdown_path.read_text(encoding="utf-8")
        self.assertEqual(render_projection_matrix_markdown(matrix), markdown)
        self.assertIn("| fra | nato | 1 |", markdown)
        self.assertIn("| srb | rusa | 1 |", markdown)

    def test_matrix_refuses_active_projection(self) -> None:
        activate_actor_projection(self.payload, self.layers, "fra")
        with self.assertRaisesRegex(ExpandedNationsError, "requires Core mode"):
            build_projection_matrix(
                self.payload,
                self.layers,
                gates_root=self.gates,
                source_head="fixture-head",
            )
        self.assertTrue(deactivate_actor_projection(self.gates))

    def test_exact_head_guard_rejects_wrong_or_dirty_checkout(self) -> None:
        repository = self.root / "repo"
        repository.mkdir()
        subprocess.run(
            ["git", "init", str(repository)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repository), "config", "user.email", "matrix@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repository), "config", "user.name", "Matrix Test"],
            check=True,
        )
        tracked = repository / "tracked.txt"
        tracked.write_text("clean\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repository), "add", "tracked.txt"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )
        head = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        _verify_git_exact_head(repository, head)
        with self.assertRaisesRegex(ExpandedNationsError, "source-head mismatch"):
            _verify_git_exact_head(repository, "0" * 40)
        tracked.write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(ExpandedNationsError, "completely clean"):
            _verify_git_exact_head(repository, head)

    def test_invalidated_evidence_contains_no_stale_signatures(self) -> None:
        evidence = invalidated_projection_evidence(
            invalidated_by_head="new-head",
            reason="native projection contract changed",
            invalidated_actor_ids=("srb", "dprk", "donbas", "blr"),
        )
        path = self.root / "invalidated.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        loaded = load_projection_matrix(path)
        self.assertEqual("invalidated", loaded["evidence_state"])
        self.assertEqual({}, loaded["actors"])
        self.assertEqual(
            ["blr", "donbas", "dprk", "srb"],
            loaded["invalidated_actor_ids"],
        )


def _unit(actor: str, name: str, side: str, source: str) -> dict:
    return {
        "unit_name": name,
        "actor_id": actor,
        "component_id": f"{actor}_component",
        "source_side": side,
        "tactical_side": side,
        "period": "2022s",
        "category": "infantry",
        "members": {"fixture": 5},
        "vehicles": [],
        "actions": [],
        "materializable": True,
        "source_files": [source],
        "source_layer": "fixture",
        "source_priority": 2,
        "virtual": False,
        "tier": 1,
        "research_cost": 1,
    }


def _actor(actor: str, side: str, unit: dict) -> dict:
    root = f"actor:{actor}:root"
    unit_key = f"actor:{actor}:unit:0"
    return {
        "actor_id": actor,
        "display_name": actor.upper(),
        "actor_type": "sovereign",
        "coalition_id": "blue" if side == "nato" else "red",
        "host_actor_id": None,
        "tactical_side": side,
        "playable": True,
        "roster_class": "full_national",
        "components": [f"{actor}_component"],
        "unit_count": 1,
        "modern_unit_count": 1,
        "legacy_unit_count": 0,
        "virtual_unit_count": 0,
        "category_counts": {"infantry": 1},
        "required_categories": ["infantry"],
        "missing_categories": [],
        "units": [unit],
        "research_node_count": 2,
        "research_nodes": [
            {
                "key": root,
                "actor_id": actor,
                "node_type": "root",
                "display_name": root,
                "cost": 0,
                "prerequisites": [],
                "unlock_units": [],
                "source_node": "",
                "source_file": "",
                "component_id": "",
            },
            {
                "key": unit_key,
                "actor_id": actor,
                "node_type": "unit",
                "display_name": unit["unit_name"],
                "cost": 1,
                "prerequisites": [root],
                "unlock_units": [unit["unit_name"]],
                "source_node": unit["unit_name"],
                "source_file": unit["source_files"][0],
                "component_id": unit["component_id"],
            },
        ],
        "notes": [],
    }


def _payload() -> dict:
    actors = [
        _actor(
            "fra",
            "nato",
            _unit(
                "fra",
                "fra_rifle(nato)",
                "nato",
                "2:codex/set/multiplayer/units/conquest/units_nato.set",
            ),
        ),
        _actor(
            "srb",
            "rusa",
            _unit(
                "srb",
                "serb_line(rusa)",
                "rusa",
                "2:codex/set/multiplayer/units/conquest/units_rusa.set",
            ),
        ),
    ]
    payload = {
        "schema": "gates-of-codex.resolved-factions",
        "schema_version": 1,
        "manifest_schema_version": 1,
        "stack_signature": "fixture-stack",
        "manifest_sha256": "fixture-manifest",
        "source_policy": {},
        "source_layers": [],
        "actor_count": len(actors),
        "actors": actors,
        "problems": [],
        "error_count": 0,
        "warning_count": 0,
    }
    payload["wiring_signature"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


if __name__ == "__main__":
    unittest.main()
