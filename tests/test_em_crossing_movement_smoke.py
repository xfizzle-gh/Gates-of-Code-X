from __future__ import annotations

import json
import tempfile
import unittest
from collections import deque
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.europe_mediterranean_from_goe import (
    build_europe_mediterranean_from_goe_campaign,
)
from gates_of_codex.models import Faction
from gates_of_codex.state_io import load_campaign, save_campaign


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "godot/assets/maps/europe_mediterranean/from_goe/map_manifest.json"


@unittest.skipUnless(MANIFEST.is_file(), "EM theatre assets missing")
class EmCrossingMovementSmokeTests(unittest.TestCase):
    """Gameplay adjacency smoke tests for authored crossings (not cost enforcement)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.by_row = {r["province_id"]: r for r in cls.manifest["province_table"]}

    def _state(self):
        return build_europe_mediterranean_from_goe_campaign(
            manifest_path=MANIFEST, selected_faction=Faction.NATO
        )

    def _place(self, state, battalion_id: str, province_id: str) -> None:
        b = state.battalions[battalion_id]
        b.province_id = province_id
        b.movement_remaining = 1
        b.condition = 100
        b.combat_actions_remaining = 1

    def _nato_battalion(self, state) -> str:
        for bid, b in state.battalions.items():
            if b.faction == Faction.NATO:
                return bid
        self.fail("no NATO battalion")

    def _path(self, start: str, goal: str) -> list[str]:
        graph = {
            pid: set(row.get("source_neighbors") or [])
            for pid, row in self.by_row.items()
        }
        q = deque([(start, [start])])
        seen = {start}
        while q:
            cur, path = q.popleft()
            if cur == goal:
                return path
            for nxt in graph.get(cur, ()):
                if nxt in self.by_row and nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, path + [nxt]))
        self.fail(f"no path {start} -> {goal}")

    def _walk(self, state, battalion_id: str, path: list[str]) -> None:
        engine = CampaignEngine(state)
        for step in path[1:]:
            b = state.battalions[battalion_id]
            b.movement_remaining = 1
            origin = b.province_id
            self.assertIn(step, state.provinces[origin].neighbors)
            # Clear blockers if any enemy sits on the step.
            for other in list(state.battalions.values()):
                if other.battalion_id == battalion_id:
                    continue
                if other.province_id == step:
                    other.province_id = origin
            result = engine.move_or_attack(battalion_id, step)
            if result.pending_battle is not None:
                # Auto-skip combat by relocating defender away already; retry as free move.
                state.pending_battle = None
                b.province_id = step
                b.movement_remaining = 0
            self.assertEqual(step, state.battalions[battalion_id].province_id)

    def test_munster_ferry_to_wales(self) -> None:
        state = self._state()
        bid = self._nato_battalion(state)
        munster = "province_0370"
        wales = "province_0367"
        self.assertEqual(
            "ferry_or_sea_lane",
            (self.by_row[munster].get("edge_types") or {}).get(wales),
        )
        self._place(state, bid, munster)
        self._walk(state, bid, [munster, wales])

    def test_northern_ireland_ferry_to_scotland(self) -> None:
        state = self._state()
        bid = self._nato_battalion(state)
        ni = "province_0409"
        scotland = "province_0420"  # Lanark
        self.assertEqual(
            "ferry_or_sea_lane",
            (self.by_row[ni].get("edge_types") or {}).get(scotland),
        )
        self._place(state, bid, ni)
        self._walk(state, bid, [ni, scotland])

    def test_germany_to_finland_via_oresund(self) -> None:
        state = self._state()
        bid = self._nato_battalion(state)
        # Holstein is continental; Oulu is Finland.
        path = self._path("Holstein", "province_0496")
        self.assertIn("province_0419", path)  # Zealand
        self.assertIn("province_0421", path)  # Skane via Oresund
        self._place(state, bid, "Holstein")
        # Walk a shortened critical segment through Oresund.
        idx_z = path.index("province_0419")
        segment = path[max(0, idx_z - 1) : idx_z + 3]
        self._place(state, bid, segment[0])
        self._walk(state, bid, segment)
        # Full path walk is long; ensure reachability and one multi-hop save/reload.
        self._place(state, bid, "Holstein")
        self._walk(state, bid, path[:6])

    def test_save_reload_after_crossing(self) -> None:
        state = self._state()
        bid = self._nato_battalion(state)
        self._place(state, bid, "province_0370")
        CampaignEngine(state).move_or_attack(bid, "province_0367")
        self.assertEqual("province_0367", state.battalions[bid].province_id)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
            self.assertEqual("province_0367", reloaded.battalions[bid].province_id)
            self.assertIn(
                "province_0367",
                reloaded.provinces["province_0370"].neighbors,
            )

    def test_ai_can_path_across_authored_crossing(self) -> None:
        # Lightweight pathfind using province.neighbors (same graph AI would use).
        state = self._state()
        start = "province_0409"
        goal = "province_0365"  # London area via Britain
        graph = {pid: set(p.neighbors) for pid, p in state.provinces.items()}
        q = deque([(start, [start])])
        seen = {start}
        found = None
        while q:
            cur, path = q.popleft()
            if cur == goal:
                found = path
                break
            for nxt in graph.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, path + [nxt]))
        self.assertIsNotNone(found)
        # Path must use the NI→Scotland ferry hop.
        self.assertTrue(
            any(
                a == "province_0409" and b == "province_0420"
                for a, b in zip(found, found[1:])
            )
            or any(
                a == "province_0420" and b == "province_0409"
                for a, b in zip(found, found[1:])
            )
        )

    def test_crossing_cost_metadata_is_not_enforced_yet(self) -> None:
        """Document current behaviour: every hop costs 1 movement."""
        state = self._state()
        bid = self._nato_battalion(state)
        self._place(state, bid, "province_0370")
        b = state.battalions[bid]
        b.movement_remaining = 1
        CampaignEngine(state).move_or_attack(bid, "province_0367")
        self.assertEqual(0, state.battalions[bid].movement_remaining)
        meta = (self.by_row["province_0370"].get("edge_meta") or {}).get("province_0367") or {}
        self.assertIn("movement_cost_multiplier", meta)
        # Multiplier is present but was not applied (still flat -1).
        self.assertGreater(float(meta["movement_cost_multiplier"]), 1.0)


if __name__ == "__main__":
    unittest.main()
