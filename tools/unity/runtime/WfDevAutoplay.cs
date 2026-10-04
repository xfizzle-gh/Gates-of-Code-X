using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEngine;

// Copied into campaign/Assets/Scripts/WfCampaign by tools/patch_campaign_code.py.
// Developer-only acceptance driver. Inert unless the app is started with:  -wfAutoplay <script file>
// It calls the map controller's own methods (the same ones the buttons call), so the strategic rules
// still apply. One command per line:
//   wait <seconds> | shot <name> | endturn | dump <label> | quit
//   setup <unit;unit;...>   create a battalion of those units in an own province next to an enemy battalion
//   attack                  attack that enemy battalion (creates the pending battle and exports the save)
//   resolve                 resolve the pending battle from the save the game wrote
public class WfDevAutoplay : MonoBehaviour
{
	private const BindingFlags Any = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

	private string scriptPath;
	private string outDir;
	private ProvinceMapController map;
	private BattalionData created;
	private string targetProvinceId;

	[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
	private static void Boot()
	{
		string[] args = Environment.GetCommandLineArgs();
		for (int i = 0; i < args.Length - 1; i++)
		{
			if (args[i] == "-wfAutoplay")
			{
				GameObject go = new GameObject("WfDevAutoplay");
				DontDestroyOnLoad(go);
				WfDevAutoplay autoplay = go.AddComponent<WfDevAutoplay>();
				autoplay.scriptPath = args[i + 1];
				autoplay.outDir = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(args[i + 1])), "autoplay-out");
				return;
			}
		}
	}

	private IEnumerator Start()
	{
		Directory.CreateDirectory(outDir);
		yield return StartCampaignFromArgs();
		while ((map = FindFirstObjectByType<ProvinceMapController>()) == null || Field<CampaignState>("campaignState") == null)
		{
			yield return new WaitForSeconds(0.5f);
		}
		yield return new WaitForSeconds(2f);
		string[] lines = File.ReadAllLines(scriptPath);
		for (int i = 0; i < lines.Length; i++)
		{
			string line = lines[i].Trim();
			if (line.Length == 0 || line.StartsWith("#"))
			{
				continue;
			}
			string[] parts = line.Split(new[] { ' ' }, 2);
			string arg = parts.Length > 1 ? parts[1].Trim() : "";
			Log("> " + line);
			switch (parts[0])
			{
			case "wait":
				yield return new WaitForSeconds(float.Parse(arg, System.Globalization.CultureInfo.InvariantCulture));
				break;
			case "shot":
				ScreenCapture.CaptureScreenshot(Path.Combine(outDir, arg + ".png"));
				yield return new WaitForSeconds(0.5f);
				break;
			case "endturn":
				Try(() => map.EndTurn());
				break;
			case "setup":
				Try(() => Setup(arg.Split(';')));
				break;
			case "attack":
				Try(Attack);
				break;
			case "createpanel":
				Try(OpenCreatePanel);
				break;
			case "resolve":
				Try(() => map.ResolvePendingBattleFromBridgeFile());
				break;
			case "dump":
				Try(() => Dump(arg));
				break;
			case "quit":
				Application.Quit();
				yield break;
			default:
				Log("unknown command: " + parts[0]);
				break;
			}
			yield return null;
		}
	}

	// -wfNewCampaign <dropdown index> -wfGameDir <dir> -wfProfileDir <dir> [-wfCampaignName <name>]
	// fills the New Campaign form and presses its own Start button, so no mouse input is needed.
	private IEnumerator StartCampaignFromArgs()
	{
		string choice = Arg("-wfNewCampaign");
		if (choice == null)
		{
			yield break;
		}
		StartMenuController menu = null;
		while ((menu = FindFirstObjectByType<StartMenuController>()) == null)
		{
			yield return new WaitForSeconds(0.5f);
		}
		yield return new WaitForSeconds(1.5f);
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
		Type type = typeof(StartMenuController);
		type.GetMethod("ShowSinglePlayerNewCampaign", flags).Invoke(menu, null);
		yield return new WaitForSeconds(0.5f);
		((TMPro.TMP_Dropdown)type.GetField("factionDropdown", flags).GetValue(menu)).value = int.Parse(choice);
		((TMPro.TMP_InputField)type.GetField("gameDirectoryInput", flags).GetValue(menu)).text = Arg("-wfGameDir") ?? "";
		((TMPro.TMP_InputField)type.GetField("profileDirectoryInput", flags).GetValue(menu)).text = Arg("-wfProfileDir") ?? "";
		FieldInfo nameField = type.GetField("campaignNameInput", flags);
		if (nameField != null && nameField.GetValue(menu) is TMPro.TMP_InputField nameInput)
		{
			nameInput.text = Arg("-wfCampaignName") ?? "WF Autoplay";
		}
		Log("starting new campaign, faction choice " + choice);
		type.GetMethod("StartNewCampaign", flags).Invoke(menu, null);
	}

	private static string Arg(string name)
	{
		string[] args = Environment.GetCommandLineArgs();
		for (int i = 0; i < args.Length - 1; i++)
		{
			if (args[i] == name)
			{
				return args[i + 1];
			}
		}
		return null;
	}

	private void Setup(string[] units)
	{
		CampaignState state = Field<CampaignState>("campaignState");
		Dictionary<string, ProvinceDefinition> provinces = Field<Dictionary<string, ProvinceDefinition>>("runtimeProvincesById");
		FactionType me = Call<FactionType>("GetLocalPlayerFaction");
		foreach (ProvinceDefinition own in provinces.Values)
		{
			if (own.Owner != me || Call<BattalionData>("GetBattalionInProvince", own.ProvinceId) != null)
			{
				continue;
			}
			for (int n = 0; n < own.NeighborProvinceIds.Count; n++)
			{
				BattalionData enemy = Call<BattalionData>("GetBattalionInProvince", own.NeighborProvinceIds[n]);
				if (enemy == null || !Call<bool>("CanFactionAttackOrConquer", me, enemy.Faction))
				{
					continue;
				}
				string tag = Call<string>("GetFactionUnitTag", me);
				if (units.Length == 1 && units[0].Trim() == "auto")
				{
					units = PickUnits(tag);
				}
				BattalionData battalion = new BattalionData
				{
					BattalionId = Call<string>("GenerateNewBattalionId", tag),
					Faction = me,
					ProvinceId = own.ProvinceId,
					IsPlayerControlled = true,
					GohFactionTag = tag
				};
				for (int u = 0; u < units.Length; u++)
				{
					battalion.Roster.Add(new BattalionRosterEntry { UnitName = units[u].Trim(), Quantity = 1 });
				}
				CampaignFactionState factionState = Call<CampaignFactionState>("GetFactionState", me);
				BattalionManagementResult result = new BattalionManagementResult { Battalion = battalion, RecruitedPool = factionState.RecruitedPool };
				Call<object>("ApplyBattalionManagementResultInternal", result, me);
				created = FindBattalion(state, battalion.BattalionId);
				targetProvinceId = enemy.ProvinceId;
				Log("setup units: " + string.Join(", ", units));
				Log("setup: battalion " + battalion.BattalionId + " (" + tag + ") in " + own.ProvinceId + " [" + own.DisplayName + "], created=" + (created != null)
					+ "; target " + enemy.BattalionId + " (" + enemy.Faction + ", tag " + enemy.GohFactionTag + ") in " + enemy.ProvinceId);
				return;
			}
		}
		Log("setup: no own empty province is adjacent to an attackable enemy battalion");
	}

	// "setup auto": the faction's first visible infantry squad, support squad and armoured unit.
	private static string[] PickUnits(string tag)
	{
		List<string> picked = new List<string>();
		GohUnitCatalog catalog = WfFactions.Catalog(tag);
		GohUnitSection[] wanted = { GohUnitSection.Inf1, GohUnitSection.Inf2, GohUnitSection.Tanks };
		for (int w = 0; catalog != null && w < wanted.Length; w++)
		{
			for (int i = 0; i < catalog.Entries.Count; i++)
			{
				GohUnitCatalogEntry entry = catalog.Entries[i];
				if (entry != null && !entry.HideFromBattalionManagement && entry.Section == wanted[w])
				{
					picked.Add(entry.RawName);
					break;
				}
			}
		}
		return picked.ToArray();
	}

	// Selects the first own province where the game allows a battalion and opens the real creation screen.
	private void OpenCreatePanel()
	{
		Dictionary<string, ProvinceDefinition> provinces = Field<Dictionary<string, ProvinceDefinition>>("runtimeProvincesById");
		int allowed = 0;
		string first = null;
		foreach (ProvinceDefinition province in provinces.Values)
		{
			if (Call<bool>("CanCreateBattalionInProvince", province.ProvinceId))
			{
				allowed++;
				first = first ?? province.ProvinceId;
			}
		}
		Log("createpanel: provinces where a battalion can be created now: " + allowed);
		if (first == null)
		{
			return;
		}
		Call<object>("SelectProvince", first);
		map.OpenCreateBattalionInSelectedProvince();
		Log("createpanel: opened for " + first + " [" + provinces[first].DisplayName + "]");
	}

	private void Attack()
	{
		if (created == null)
		{
			Log("attack: no battalion from setup");
			return;
		}
		MethodInfo start = typeof(ProvinceMapController).GetMethod("StartAttack", Any, null, new[] { typeof(BattalionData), typeof(string) }, null);
		start.Invoke(map, new object[] { created, targetProvinceId });
		PendingBattleRecord pending = Call<PendingBattleRecord>("LoadPendingBattle");
		Log(pending == null
			? "attack: no pending battle was created"
			: "attack: pending " + pending.BattleId + " playerIsAttacker=" + pending.PlayerIsAttacker + " sav=" + pending.ExportedSavPath
				+ " counters=" + pending.HasExportedResultCounters + " played=" + pending.ExportedPlayedGames + " won=" + pending.ExportedWonGames);
	}

	private void Dump(string label)
	{
		CampaignState state = Field<CampaignState>("campaignState");
		Dictionary<string, ProvinceDefinition> provinces = Field<Dictionary<string, ProvinceDefinition>>("runtimeProvincesById");
		StringBuilder sb = new StringBuilder();
		sb.AppendLine("turn=" + state.TurnNumber + " current=" + state.CurrentTurnFaction + " battalions=" + state.Battalions.Count);
		PendingBattleRecord pending = Call<PendingBattleRecord>("LoadPendingBattle");
		sb.AppendLine("pending=" + (pending == null ? "none" : pending.BattleId));
		if (created != null)
		{
			BattalionData b = FindBattalion(state, created.BattalionId);
			sb.AppendLine(b == null ? "created battalion: GONE" : "created battalion: " + b.BattalionId + " in " + b.ProvinceId + " roster=" + b.Roster.Count);
			for (int i = 0; b != null && i < b.Roster.Count; i++)
			{
				sb.AppendLine("  " + b.Roster[i].UnitName + " x" + b.Roster[i].Quantity + " squadStates=" + (b.Roster[i].SquadStates != null ? b.Roster[i].SquadStates.Count : 0));
			}
		}
		if (targetProvinceId != null && provinces.TryGetValue(targetProvinceId, out ProvinceDefinition target))
		{
			sb.AppendLine("target province " + targetProvinceId + " owner=" + target.Owner + " occupier=" + target.OccupyingBattalionId);
		}
		File.WriteAllText(Path.Combine(outDir, "dump-" + label + ".txt"), sb.ToString());
		Log("dump " + label + ":\n" + sb);
	}

	private static BattalionData FindBattalion(CampaignState state, string id)
	{
		for (int i = 0; i < state.Battalions.Count; i++)
		{
			if (state.Battalions[i] != null && state.Battalions[i].BattalionId == id)
			{
				return state.Battalions[i];
			}
		}
		return null;
	}

	private T Field<T>(string name)
	{
		FieldInfo field = typeof(ProvinceMapController).GetField(name, Any);
		return field == null ? default(T) : (T)field.GetValue(map);
	}

	private T Call<T>(string name, params object[] args)
	{
		Type[] types = new Type[args.Length];
		for (int i = 0; i < args.Length; i++)
		{
			types[i] = args[i].GetType();
		}
		MethodInfo method = typeof(ProvinceMapController).GetMethod(name, Any, null, types, null);
		if (method == null)
		{
			throw new MissingMethodException("ProvinceMapController." + name);
		}
		object value = method.Invoke(map, args);
		return value == null ? default(T) : (T)value;
	}

	private void Try(Action action)
	{
		try
		{
			action();
		}
		catch (Exception ex)
		{
			Log("FAILED: " + (ex.InnerException ?? ex));
		}
	}

	private void Log(string message)
	{
		Debug.Log("[WfAutoplay] " + message);
		File.AppendAllText(Path.Combine(outDir, "autoplay.log"), message + "\n");
	}
}
