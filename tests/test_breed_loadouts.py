from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.bridge.scn import CampaignScnBuilder, parse_breed_inventory
from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.starter import populate_starter_rosters


class BreedLoadoutTests(unittest.TestCase):
    def test_parse_breed_inventory_common_shapes(self) -> None:
        text = """
{breed
	{inventory
		{item "m4a1_v3b" filled}
		{item "m16a2 ammo" 180}
		{item "m26 grenade" 2}
		{item "bandage_usa" 3.5 0.5}
		{item "shovel_csa"}
		{item "l403" filling "m16a2 ammo" 30}
		{in_hands 0}
	}
}
"""
        items = parse_breed_inventory(text)
        names = [item.name for item in items]
        self.assertIn("m4a1_v3b", names)
        self.assertTrue(any(item.name == "m4a1_v3b" and item.filled for item in items))
        self.assertTrue(any(item.name == "m16a2" and item.kind == "ammo" and item.quantity == 180 for item in items))
        self.assertTrue(any(item.name == "m26" and item.kind == "grenade" and item.quantity == 2 for item in items))
        self.assertTrue(any(item.name == "bandage_usa" and item.quantity == 3 for item in items))
        self.assertTrue(any(item.name == "shovel_csa" and not item.filled for item in items))
        self.assertTrue(any(item.name == "l403" and item.filled for item in items))
        self.assertTrue(any(item.name == "m16a2" and item.kind == "ammo" and item.quantity == 30 for item in items))

    def test_campaign_scn_embeds_breed_loadouts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            codex = root / "codex"
            breed_dir = codex / "resource/set/breed/mp/nato"
            breed_dir.mkdir(parents=True)
            (breed_dir / "rifleman_nato.set").write_text(
                "{breed\n"
                "\t{inventory\n"
                '\t\t{item "m4a1_v3b" filled}\n'
                '\t\t{item "m16a2 ammo" 180}\n'
                '\t\t{item "bandage_usa" 3}\n'
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            (codex / "resource/set/breed/mp/rusa").mkdir(parents=True)
            (codex / "resource/set/breed/mp/rusa/rifleman_rusa.set").write_text(
                "{breed\n"
                "\t{inventory\n"
                '\t\t{item "ak74m" filled}\n'
                '\t\t{item "ak74 ammo" 120}\n'
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            (codex / "resource/set/multiplayer/units/conquest/2022s").mkdir(parents=True)
            (codex / "resource/script/multiplayer/units/nato").mkdir(parents=True)
            units = []
            lua = []
            for faction in ("nato", "ukr", "rusa", "prc"):
                side_dir = codex / f"resource/set/breed/mp/{faction}"
                side_dir.mkdir(parents=True, exist_ok=True)
                if faction not in {"nato", "rusa"}:
                    (side_dir / f"rifleman_{faction}.set").write_text(
                        '{breed\n\t{inventory\n\t\t{item "pistol" filled}\n\t}\n}\n',
                        encoding="utf-8",
                    )
                units.append(f'{{"rifle({faction})" {{member "rifleman_{faction}" 2}}}}\n')
                lua.append(f'{{priority=1, type={{"Infantry","Squad"}}, unit="rifle({faction})"}},\n')
            (codex / "resource/set/multiplayer/units/conquest/2022s/units.set").write_text("".join(units), encoding="utf-8")
            (codex / "resource/script/multiplayer/units/nato/2022s.nato.lua").write_text("".join(lua), encoding="utf-8")
            (codex / "mod.info").write_text('{name "Code:X"}\n', encoding="utf-8")

            catalog = CodeXCatalogScanner().scan(codex)
            state = load_bundled_scenario()
            populate_starter_rosters(state, catalog)
            engine = CampaignEngine(state)
            nato = next(value for value in state.battalions.values() if value.faction == Faction.NATO)
            rusa = next(value for value in state.battalions.values() if value.faction == Faction.RUSSIA)
            state.battalions[nato.battalion_id].province_id = "Westfalen"
            state.provinces["Westfalen"].owner = Faction.NATO
            state.battalions[rusa.battalion_id].province_id = "Hessen"
            state.provinces["Hessen"].owner = Faction.RUSSIA
            state.battalions[nato.battalion_id].movement_remaining = 1
            engine.move_or_attack(nato.battalion_id, "Hessen")
            text = CampaignScnBuilder(catalog, codex).build(state, state.pending_battle)
            self.assertIn('{item "m4a1_v3b" filled {cell 0 0}{user "hand_right"}}', text)
            self.assertIn('{item "m16a2" "ammo" 180 {cell 2 0}}', text)
            self.assertNotIn("ak74m", text)
            self.assertNotIn("/rusa/", text)
            self.assertIn("{clear}", text)
            self.assertIn("{NameId", text)
            self.assertRegex(text, r"\{Human [^}]+ 0xc000")


if __name__ == "__main__":
    unittest.main()
