"""#194 owner correction: Spain uses ILDU/NATO personnel, never Azov/3rd Assault."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from gates_of_codex.faction_wiring_manifest import load_faction_manifest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ILDU_IDS = {
    "goc_ildu_rifle(goc_esp)",
    "goc_ildu_at(goc_esp)",
    "goc_ildu_javelin(goc_esp)",
    "goc_ildu_recon(goc_esp)",
    "goc_ildu_engineer(goc_esp)",
    "goc_ildu_manpads(goc_esp)",
}
ILDU_PRICED_BREEDS = {
    "nato_squadlead", "nato_seniorrifleman", "nato_rifleman", "nato_rifleman1",
    "nato_rifleman2", "nato_grenadier", "nato_mg", "nato_mgassist", "nato_medic",
    "nato_antitank", "nato_atassist", "nato_javelin", "nato_sniper", "nato_spotter",
    "nato_eng", "nato_manpad_operator", "nato_manpad_supporter",
}
ILDU_NATIVE_UNPRICED_BREEDS = {"nato_antitank_pzf3"}
FORBIDDEN_SPAIN_TOKENS = ("azov3", "3rd_assault", "squad_3rd_rozv_hatred")
_RESOLVED_UNIT_RE = re.compile(r"^;\s*resolved_unit=(.+?)\s*$", re.MULTILINE)
_GOC_NODE_RE = re.compile(r"^;\s*goc-node\s+(\{.*\})\s*$", re.MULTILINE)
_PURCHASE_RE = re.compile(r'\bunit\s*=\s*"([^"]+)"')
_INF_MARKER = "; goc-inf-cost "


class Phase194SpainIlduAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.units_path = ROOT / "resource/set/multiplayer/units/conquest/units_goc_esp.set"
        cls.inf_path = ROOT / "resource/set/multiplayer/units/conquest/inf_goc_esp.set"
        cls.research_path = ROOT / "resource/set/dynamic_campaign/unit_research_goc_esp.set"
        cls.lua_path = ROOT / "resource/script/multiplayer/units/goc_esp/conquest.goc_esp.lua"
        cls.units = cls.units_path.read_text(encoding="utf-8")
        cls.inf = cls.inf_path.read_text(encoding="utf-8")
        cls.research = cls.research_path.read_text(encoding="utf-8")
        cls.lua = cls.lua_path.read_text(encoding="utf-8")

    def test_manifest_owner_override_is_exact(self) -> None:
        manifest = load_faction_manifest()
        spain = next(row for row in manifest["actors"] if row["actor_id"] == "esp")
        self.assertEqual(
            ["ukraine_ildu", "nato_fallback_heavy", "nato_common_support"],
            spain["components"],
        )

    def test_committed_spain_surfaces_contain_no_rejected_prior_allocation(self) -> None:
        for path, text in (
            (self.units_path, self.units),
            (self.inf_path, self.inf),
            (self.research_path, self.research),
            (self.lua_path, self.lua),
        ):
            lowered = text.lower()
            for token in FORBIDDEN_SPAIN_TOKENS:
                self.assertNotIn(token, lowered, f"{path} retains rejected Spain content {token}")

    def test_units_research_and_ai_have_exact_six_ildu_purchases(self) -> None:
        unit_ids = set(_RESOLVED_UNIT_RE.findall(self.units))
        ildu_units = {unit for unit in unit_ids if unit.startswith("goc_ildu_")}
        self.assertEqual(EXPECTED_ILDU_IDS, ildu_units)

        research_rows = [json.loads(raw) for raw in _GOC_NODE_RE.findall(self.research)]
        research_ids = {str(row["unlock_unit"]) for row in research_rows}
        ildu_research = {unit for unit in research_ids if unit.startswith("goc_ildu_")}
        self.assertEqual(EXPECTED_ILDU_IDS, ildu_research)

        purchase_ids = set(_PURCHASE_RE.findall(self.lua))
        ildu_ai = {unit for unit in purchase_ids if unit.startswith("goc_ildu_")}
        self.assertEqual(EXPECTED_ILDU_IDS, ildu_ai)

        self.assertEqual(unit_ids, research_ids)
        self.assertEqual(unit_ids, purchase_ids)
        self.assertEqual(49, len(unit_ids))

    def test_inf_pack_preserves_exact_ildu_native_cost_authority(self) -> None:
        rows: dict[str, dict] = {}
        for line in self.inf.splitlines():
            stripped = line.strip()
            if not stripped.startswith(_INF_MARKER):
                continue
            metadata = json.loads(stripped[len(_INF_MARKER) :])
            target = str(metadata.get("target_path") or "")
            if not target.startswith("mp/goc_esp/"):
                continue
            breed = target.rsplit("/", 1)[-1]
            rows[breed] = metadata

        missing = sorted(ILDU_PRICED_BREEDS - set(rows))
        self.assertEqual([], missing, f"Spain ILDU personnel costs missing: {missing}")
        for breed in sorted(ILDU_PRICED_BREEDS):
            self.assertGreater(float(rows[breed]["cost"]), 0.0, breed)

        for breed in ILDU_NATIVE_UNPRICED_BREEDS:
            self.assertNotIn(
                breed,
                rows,
                f"Spain ILDU native-unpriced breed gained fabricated cost authority: {breed}",
            )

        expected_authority = {
            "nato_atassist": ("mp/ukr/2022s/ukr_atassist", 7.0),
            "nato_mgassist": ("mp/ukr/2022s/ukr_lmgassist", 7.0),
            "nato_manpad_operator": ("mp/ukr/2022s/ukr_manpad_operator", 17.5),
            "nato_manpad_supporter": ("mp/ukr/2022s/ukr_manpad_supporter", 17.5),
            "nato_medic": ("mp/nato/2022s/nato_medic", 28.0),
        }
        for breed, (source_path, cost) in expected_authority.items():
            self.assertEqual(source_path, rows[breed]["source_path"], breed)
            self.assertEqual(cost, float(rows[breed]["cost"]), breed)

    def test_units_header_records_current_owner_components(self) -> None:
        self.assertIn("components=ukraine_ildu,nato_fallback_heavy,nato_common_support", self.units)
        self.assertNotIn("components=spain_3rd_assault_legion", self.units)


if __name__ == "__main__":
    unittest.main()
