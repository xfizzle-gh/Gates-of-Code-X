"""Patch the recovered C# in campaign/ so factions, catalogs and research trees come from WarFighter data.

Idempotent: each method is replaced wholesale by signature, so re-running gives the same result.
Run after tools/build_wf_scenario.py (which writes WfFactions.generated.cs).

    python tools/patch_campaign_code.py
"""
from __future__ import annotations

import json
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


def patch_battle_export() -> None:
    settings = json.loads((ROOT / "data" / "export_settings.json").read_text(encoding="utf-8"))

    # Tactical maps: one WF pool; the status region must be WF's conquest region.
    path = SRC / "GohConquestMapEntry.cs"
    t = path.read_text(encoding="utf-8")
    t = replace_method(t, r"public string GetStatusRegionString\(\)\s*", f'return "{settings["region"]}";')
    path.write_text(t, encoding="utf-8")

    # The battle save must require WarFighter, not the Gates of Europa workshop item.
    path = SRC / "GohModDependencyUtility.cs"
    t = path.read_text(encoding="utf-8")
    t = t.replace("mod_3717998771:0", settings["modDependency"]).replace("Gates of Europa mod", "WarFighter mod")
    # "Launch Gates of Hell" inserts the mod into the player's options.set. Keep a one-time copy of
    # the file as it was before this application first changed it.
    backup = 'if (!File.Exists(path + ".wfcampaign.bak")) { File.Copy(path, path + ".wfcampaign.bak"); }'
    if backup not in t:
        t, n = re.subn(r"(\n(\s*))(File\.WriteAllText\(path, )", lambda m: m.group(1) + backup + "\n" + m.group(2) + m.group(3), t, count=1)
        if n != 1:
            raise SystemExit("options.set write site not found")
    # GoW's in-game half is a second mod that must be listed after WarFighter. The recovered code
    # ensures exactly one mod; keep that for WarFighter and add GoW directly below its line.
    if "EnsureWfModInText" not in t:
        companion = settings["companionMod"]
        wf_mod = settings["modDependency"]
        t = t.replace("private static string EnsureRequiredModInText(string text, bool preferTopOfFile)",
                      "private static string EnsureWfModInText(string text, bool preferTopOfFile)", 1)
        addition = f'''	private static string EnsureRequiredModInText(string text, bool preferTopOfFile)
	{{
		text = EnsureWfModInText(text, preferTopOfFile);
		if (text.Contains("{companion}"))
		{{
			return text;
		}}
		int index = text.IndexOf("\\"{wf_mod}\\"", StringComparison.Ordinal);
		if (index < 0)
		{{
			return text;
		}}
		int lineStart = text.LastIndexOf('\\n', index) + 1;
		string indent = text.Substring(lineStart, index - lineStart);
		int insertAt = index + "\\"{wf_mod}\\"".Length;
		return text.Insert(insertAt, GetNewLine(text) + indent + "\\"{companion}\\"");
	}}

'''
        t = t.replace("\tprivate static string EnsureWfModInText(", addition + "\tprivate static string EnsureWfModInText(", 1)
    path.write_text(t, encoding="utf-8")

    # Every export also writes the enemy battalion for GoW's in-game Lua.
    path = SRC / "StatusExporter.cs"
    t = path.read_text(encoding="utf-8")
    if "WfBattleContext.Write" not in t:
        t, n = re.subn(r"(\n(\s*))(File\.WriteAllText\(Paths\.StatusPath, )",
                       lambda m: m.group(1) + "WfBattleContext.Write(context);" + "\n" + m.group(2) + m.group(3), t, count=1)
        if n != 1:
            raise SystemExit("status write site not found")
    path.write_text(t, encoding="utf-8")

    # Keep the bridge exchange files out of Documents and out of the GOE namespace.
    path = SRC / "Paths.cs"
    t = path.read_text(encoding="utf-8")
    t = re.sub(r"(public static string GatesOfEuropaDocumentsDirectory\s*=>\s*)[^;]+;",
               r'\1Path.Combine(Application.persistentDataPath, "Bridge");', t)
    path.write_text(t, encoding="utf-8")

    path = SRC / "ProvinceMapController.cs"
    t = path.read_text(encoding="utf-8")
    t = t.replace('"GatesOfEuropa_" + ', '"WarfighterCampaign_" + ')
    t = t.replace("failed to enable the Gates of Europa mod in options.set", "failed to enable the WarFighter mod in options.set")
    # GOE waits for its own Lua bridge file before reading the result from the save. WF has no such
    # Lua; the save's playedGames/wonGames counters are the result, so read them directly.
    marker = "/* wf: resolve from save counters */"
    if marker not in t:
        m = re.search(r"public void ResolvePendingBattleFromBridgeFile\(\)", t)
        body_start = m.end()
        pending = re.search(r"PendingBattleRecord (\w+) = LoadPendingBattle\(\);", t[body_start:]).group(1)
        read = re.search(r"\n(\s*)GohBridgeResultReader\.BridgeResult \w+ = GohBridgeResultReader\.Read\(", t[body_start:])
        indent = read.group(1)
        insert = (
            f"\n{indent}{marker}"
            f"\n{indent}if ({pending}.HasExportedResultCounters && !File.Exists(Paths.BridgeResultPath))"
            f"\n{indent}{{"
            f"\n{indent}\tif (!TryResolvePendingBattleFromSavStatus({pending}, out var wfReason))"
            f"\n{indent}\t{{"
            f'\n{indent}\t\tShowValidationMessage("Battle is not finished yet. " + wfReason);'
            f"\n{indent}\t}}"
            f"\n{indent}\treturn;"
            f"\n{indent}}}")
        pos = body_start + read.start()
        t = t[:pos] + insert + t[pos:]
    if "WfBattleContext.Clear();" not in t:
        t, n = re.subn(r"(private void ClearPendingBattle\(\)\s*\{)", lambda m: m.group(1) + "\n\t\tWfBattleContext.Clear();", t, count=1)
        if n != 1:
            raise SystemExit("ClearPendingBattle not found")
    path.write_text(t, encoding="utf-8")


def patch_inventory_conversion() -> None:
    # The recovered converter knows WWII item names only ("mp40 ammo", "rifle clip ammo"). WF names put
    # "ammo" first or use five tags, so 1200 rounds became 1200 separate items. Emit what a native WF
    # save contains instead: every tag quoted separately, stacks as one line with a count, and weapons
    # as `filling <ammo tags> <rounds>`.
    path = SRC / "GohCampaignObjectBuilder.cs"
    t = path.read_text(encoding="utf-8")
    t = replace_method(t, r"private static string QuoteCompoundItemName\(string itemName\)\s*", """
if (string.IsNullOrWhiteSpace(itemName))
{
	return "\\"\\"";
}
string[] array = itemName.Split(new char[1] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
return "\\"" + string.Join("\\" \\"", array) + "\\"";
""")
    t = replace_method(t, r"private static bool IsAmmoItem\(string itemName\)\s*", """
string[] array = itemName.Split(new char[1] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
for (int i = 0; i < array.Length; i++)
{
	if (string.Equals(array[i], "ammo", StringComparison.OrdinalIgnoreCase))
	{
		return true;
	}
}
return itemName.EndsWith("_ammo", StringComparison.OrdinalIgnoreCase);
""")
    t = replace_method(t, r"private static void AppendConvertedInventoryItems\(List<string> lines, string itemName, string tail, ref int cell\)\s*", """
string text = QuoteCompoundItemName(itemName);
string cellText = " {cell " + cell % 8 + " " + cell / 8 + "}";
Match filling = Regex.Match(tail, "filling\\\\s+\\"([^\\"]+)\\"\\\\s*(\\\\d+)?", RegexOptions.IgnoreCase);
if (filling.Success)
{
	string rounds = filling.Groups[2].Success ? (" " + filling.Groups[2].Value) : "";
	lines.Add("\\t\\t\\t{item " + text + " filling " + QuoteCompoundItemName(filling.Groups[1].Value) + rounds + cellText + "}");
	cell++;
	return;
}
if (tail.IndexOf("filled", StringComparison.OrdinalIgnoreCase) >= 0)
{
	lines.Add("\\t\\t\\t{item " + text + " filled" + cellText + "}");
	cell++;
	return;
}
List<float> numbers = ExtractNumbers(tail);
// "{item x 0.5 90}" is a chance-based extra in breed files; keep the recovered behaviour (one item).
bool fractional = numbers.Count > 0 && Mathf.Abs(numbers[0] - Mathf.Round(numbers[0])) > 0.001f;
int count = (numbers.Count > 0 && !fractional) ? Mathf.RoundToInt(numbers[0]) : 1;
if (count > 1)
{
	lines.Add("\\t\\t\\t{item " + text + " " + count + cellText + "}");
}
else
{
	lines.Add("\\t\\t\\t{item " + text + cellText + "}");
}
cell++;
""")
    path.write_text(t, encoding="utf-8")


def patch_display_names() -> None:
    # Player-facing text that printed the WWII enum identifier of a faction slot.
    edits = {
        "ProvinceInfoPanel.cs": [('"Owner: " + runtimeProvince.Owner;', '"Owner: " + WfFactions.NameOf(runtimeProvince.Owner);')],
        "PendingBattleResolutionPanel.cs": [("pending.BattleOwnerFaction.ToString()", "WfFactions.NameOf(pending.BattleOwnerFaction)")],
        "ProvinceMapController.cs": [
            ('"Winner: " + winnerFaction.ToString()', '"Winner: " + WfFactions.NameOf(winnerFaction)'),
            ("requestedFaction.ToString()", "WfFactions.NameOf(requestedFaction)"),
            ("hostCoopFaction.ToString()", "WfFactions.NameOf(hostCoopFaction)"),
        ],
    }
    for name, pairs in edits.items():
        path = SRC / name
        t = path.read_text(encoding="utf-8")
        for old, new in pairs:
            t = t.replace(old, new)
        path.write_text(t, encoding="utf-8")


def patch_campaign_rules() -> None:
    manpower_only = "value.ParsedSpecialization != ProvinceSpecialization.Manpower"

    path = SRC / "ProvinceMapController.cs"
    t = path.read_text(encoding="utf-8")
    # Recruit on a deployment hub or next to one.
    t = t.replace("RequireManpowerProvinceForBattalionSpawn && " + manpower_only,
                  "RequireManpowerProvinceForBattalionSpawn && !WfRules.IsRecruitProvince(value, runtimeProvincesById)")
    # A battalion raised this turn cannot attack or capture until the next one.
    # Only the "new battalion" branch: the same statement also appears in the per-turn reset, and
    # replacing it there left every battalion on the map unable to attack or capture.
    new_branch = re.search(r"BattalionData (\w+) = CloneBattalion\(result\.Battalion\);", t)
    var = new_branch.group(1)
    stmt = f"{var}.RemainingCombatActions = GetCombatActionAllowanceForBattalion({var});"
    at = t.find(stmt, new_branch.end())
    if 0 <= at - new_branch.end() < 600:
        t = t[:at] + f"{var}.RemainingCombatActions = 0;" + t[at + len(stmt):]
    # Starting order of battle for a new campaign.
    if "WfOrderOfBattle.Apply" not in t:
        t, n = re.subn(r"(\n(\s*)ApplyNewCampaignSettings\((\w+), campaignState\);)",
                       lambda m: m.group(1) + "\n" + m.group(2) + "WfOrderOfBattle.Apply(campaignState, battalionTypeRulesAsset, IsFactionHumanControlled);", t, count=1)
        if n != 1:
            raise SystemExit("new-campaign hook site not found")
    path.write_text(t, encoding="utf-8")

    path = SRC / "CampaignAiRunner.cs"
    t = path.read_text(encoding="utf-8")
    t = t.replace("if (" + manpower_only + ")", "if (!WfRules.IsRecruitProvince(value, campaignState))")
    t = t.replace("RemainingCombatActions = GetCombatActionAllowanceForBattalionType(chosenType)", "RemainingCombatActions = 0")
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
    patch_battle_export()
    patch_inventory_conversion()
    patch_display_names()
    patch_campaign_rules()
    print("campaign code patched for WarFighter factions")


if __name__ == "__main__":
    main()
