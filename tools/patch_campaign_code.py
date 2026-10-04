"""Patch the recovered C# in campaign/ so factions, catalogs and research trees come from WarFighter data.

Idempotent: each method is replaced wholesale by signature, so re-running gives the same result.
Run after tools/build_wf_scenario.py (which writes WfFactions.generated.cs).

    python tools/patch_campaign_code.py
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "campaign" / "Assets" / "Scripts"
SRC = SCRIPTS / "Assembly-CSharp"
WF_DIR = SCRIPTS / "WfCampaign"


def replace_method(text: str, signature: str, body: str) -> str:
    """Replace the body of the method whose declaration line matches `signature` (a regex)."""
    m = re.search(signature, text)
    if not m:
        raise SystemExit(f"method not found: {signature}")
    open_brace = text.index("{", m.end())
    depth, i = 0, open_brace
    while True:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    indent = re.search(r"[ \t]*$", text[:m.start()]).group(0)
    lines = "\n".join((indent + "\t" + ln) if ln else "" for ln in body.strip("\n").split("\n"))
    return text[:open_brace] + "{\n" + lines + "\n" + indent + "}" + text[i + 1:]


def patch_map_controller() -> None:
    path = SRC / "ProvinceMapController.cs"
    t = path.read_text(encoding="utf-8")
    t = replace_method(t, r"private FactionType GetFactionType\(FactionChoice \w+\)\s*", """
return WfFactions.SlotForChoice((int)factionChoice);
""".replace("factionChoice", re.search(r"private FactionType GetFactionType\(FactionChoice (\w+)\)", t).group(1)))
    arg = re.search(r"private GohUnitCatalog GetUnitCatalogForFactionType\(FactionType (\w+)\)", t).group(1)
    t = replace_method(t, r"private GohUnitCatalog GetUnitCatalogForFactionType\(FactionType \w+\)\s*", f"""
GohUnitCatalog wfCatalog = WfFactions.Catalog(GetFactionUnitTag({arg}));
return (wfCatalog != null) ? wfCatalog : activeUnitCatalog;
""")
    arg = re.search(r"private GohResearchTreeAsset GetResearchTreeForFactionType\(FactionType (\w+)\)", t).group(1)
    t = replace_method(t, r"private GohResearchTreeAsset GetResearchTreeForFactionType\(FactionType \w+\)\s*", f"""
GohResearchTreeAsset wfTree = WfFactions.ResearchTree(GetFactionUnitTag({arg}));
return (wfTree != null) ? wfTree : activeResearchTree;
""")
    arg = re.search(r"private GohUnitCatalog GetUnitCatalogForFaction\(FactionChoice (\w+)\)", t).group(1)
    t = replace_method(t, r"private GohUnitCatalog GetUnitCatalogForFaction\(FactionChoice \w+\)\s*",
                       f"return GetUnitCatalogForFactionType(GetFactionType({arg}));")
    arg = re.search(r"private GohResearchTreeAsset GetResearchTreeForFaction\(FactionChoice (\w+)\)", t).group(1)
    t = replace_method(t, r"private GohResearchTreeAsset GetResearchTreeForFaction\(FactionChoice \w+\)\s*",
                       f"return GetResearchTreeForFactionType(GetFactionType({arg}));")
    t = replace_method(t, r"private List<GohUnitCatalog> GetAllUnitCatalogsForLookup\(\)\s*", """
List<GohUnitCatalog> list = GohUnitCatalogLookup.BuildUniqueList(WfFactions.AllCatalogs());
if (activeUnitCatalog != null && !list.Contains(activeUnitCatalog))
{
	list.Insert(0, activeUnitCatalog);
}
return list;
""")
    t = replace_method(t, r"private GohUnitCatalog\[\] GetPostBattleImportCatalogs\(\)\s*", """
List<GohUnitCatalog> list = new List<GohUnitCatalog>();
list.Add(activeUnitCatalog);
list.Add(GetUnitCatalogForFactionType(GetLocalPlayerFaction()));
list.AddRange(WfFactions.AllCatalogs());
return list.ToArray();
""")
    path.write_text(t, encoding="utf-8")


def patch_start_menu() -> None:
    path = SRC / "StartMenuController.cs"
    t = path.read_text(encoding="utf-8")
    sig = re.search(r"private void PopulateFactionDropdown\(TMP_Dropdown (\w+), bool (\w+)\)", t)
    dd, none = sig.group(1), sig.group(2)
    t = replace_method(t, r"private void PopulateFactionDropdown\(TMP_Dropdown \w+, bool \w+\)\s*", f"""
if (!({dd} == null))
{{
	{dd}.ClearOptions();
	List<string> list = new List<string>();
	if ({none})
	{{
		list.Add("None");
	}}
	list.AddRange(WfFactions.DisplayNames());
	{dd}.AddOptions(list);
}}
""")
    # WWII DLC gates on what are now unrelated dropdown indexes.
    t = re.sub(r"\w+(?:\.\w+)? == FactionChoice\.(?:Commonwealth|Finland) && !HasEnabledDlc\(",
               "false && !HasEnabledDlc(", t)
    t = t.replace("if false && !HasEnabledDlc(", "if (false && !HasEnabledDlc(")  # repair of an earlier run
    path.write_text(t, encoding="utf-8")


def patch_turn_panel() -> None:
    # The turn banner reads names and flags from a list serialized in the scene (WWII nations).
    path = SRC / "TurnSequencePanel.cs"
    t = path.read_text(encoding="utf-8")
    arg = re.search(r"private FactionTurnVisual GetVisual\(FactionType (\w+)\)", t).group(1)
    t = replace_method(t, r"private FactionTurnVisual GetVisual\(FactionType \w+\)\s*", f"""
WfFaction wf = WfFactions.ForSlot({arg});
if (wf != null)
{{
	return new FactionTurnVisual
	{{
		Faction = {arg},
		DisplayName = wf.Name,
		Flag = WfFactions.Flag(wf.Tag)
	}};
}}
if (visuals == null)
{{
	return null;
}}
for (int i = 0; i < visuals.Count; i++)
{{
	if (visuals[i] != null && visuals[i].Faction == {arg})
	{{
		return visuals[i];
	}}
}}
return null;
""")
    path.write_text(t, encoding="utf-8")


def main() -> None:
    WF_DIR.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "tools" / "unity" / "runtime").glob("*.cs"):
        shutil.copyfile(f, WF_DIR / f.name)
    # The enum's integer is the faction dropdown index; ten WF factions need ten values.
    (SRC / "FactionChoice.cs").write_text(
        "public enum FactionChoice\n{\n\tGermany,\n\tUSSR,\n\tFinland,\n\tCommonwealth,\n\tUSA,\n"
        "\tChoice5,\n\tChoice6,\n\tChoice7,\n\tChoice8,\n\tChoice9\n}\n", encoding="utf-8")
    patch_map_controller()
    patch_start_menu()
    patch_turn_panel()
    print("campaign code patched for WarFighter factions")


if __name__ == "__main__":
    main()
