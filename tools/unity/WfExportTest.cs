using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;
using UnityEditor;
using UnityEngine;

// Copied into campaign/Assets/Editor by tools/build_campaign.ps1.
// Headless export fixture: builds a battle save for a small force with the application's own exporter
// classes and writes it under build/export-test. Touches no game profile.
//   Unity -batchmode -projectPath campaign -executeMethod WfExportTest.Run -wfTag usa -wfEnemy rus -wfUnits "a;b;c"
public static class WfExportTest
{
	public static void Run()
	{
		try
		{
			string tag = Arg("-wfTag", "usa");
			string enemy = Arg("-wfEnemy", "rus");
			string[] units = Arg("-wfUnits", "squad1(usa);command_team_t2(usa);stryker_m2hb;humvee_m240").Split(';');
			string outDir = Path.GetFullPath(Path.Combine(Application.dataPath, "../../build/export-test"));
			Directory.CreateDirectory(outDir);

			GohUnitCatalog catalog = WfFactions.Catalog(tag);
			GohFullUnitTemplateCache cache = Resources.Load<GohFullUnitTemplateCache>("GohFullUnitTemplateCache");
			if (catalog == null || cache == null)
			{
				throw new Exception("catalog or template cache missing for tag " + tag);
			}
			List<GohUnitCatalog> catalogs = new List<GohUnitCatalog> { catalog };
			int attached = GohFullUnitTemplateCacheAttacher.Attach(cache, catalogs);

			BattalionData battalion = new BattalionData
			{
				BattalionId = "wf_test_battalion",
				GohFactionTag = tag,
				IsPlayerControlled = true,
				ProvinceId = "province_0001"
			};
			for (int i = 0; i < units.Length; i++)
			{
				battalion.Roster.Add(new BattalionRosterEntry { UnitName = units[i].Trim(), Quantity = 1 });
			}
			string scn = CampaignScnExporter.BuildCampaignScn(battalion, catalogs);

			GohStatusExportSettings settings = AssetDatabase.LoadAssetAtPath<GohStatusExportSettings>("Assets/MonoBehaviour/GohStatusExportSettings.asset");
			GohConquestMapEntry map = settings.MapCatalog.FindByMapId(Arg("-wfMap", "dcg_8v8_woodland"));
			GohStatusExportContext context = new GohStatusExportContext
			{
				BattleName = "WarfighterCampaign_export_test",
				TargetProvinceId = "province_0002",
				PlayerBattalion = battalion,
				StrategicAttacker = battalion,
				PlayerIsAttacker = true,
				PlayerArmyCode = tag,
				EnemyArmyCode = enemy,
				Difficulty = "normal",
				PlayedGames = 0,
				UnlockedResearchKeys = new List<string>
				{
					"reinforcement_stage_1", "reinforcement_stage_2", "reinforcement_stage_3",
					"reinforcement_stage_4", "reinforcement_stage_5"
				}
			};
			string status = GohModDependencyUtility.EnsureRequiredModInStatusText(StatusExporter.BuildStatusText(settings, map, context));

			UTF8Encoding utf8 = new UTF8Encoding(false);
			File.WriteAllText(Path.Combine(outDir, "campaign.scn"), scn, utf8);
			File.WriteAllText(Path.Combine(outDir, "status"), status, utf8);
			string sav = Path.Combine(outDir, "WarfighterCampaign_export_test.sav");
			File.Delete(sav);
			using (ZipArchive zip = ZipFile.Open(sav, ZipArchiveMode.Create))
			{
				zip.CreateEntryFromFile(Path.Combine(outDir, "campaign.scn"), "campaign.scn");
				zip.CreateEntryFromFile(Path.Combine(outDir, "status"), "status");
			}
			Debug.Log("WfExportTest: templates attached=" + attached + ", scn chars=" + scn.Length + ", wrote " + sav);
			EditorApplication.Exit(0);
		}
		catch (Exception ex)
		{
			Debug.LogError("WfExportTest FAILED: " + ex);
			EditorApplication.Exit(1);
		}
	}

	// Exports every non-hidden catalog unit of every faction, one unit at a time, and writes a
	// per-unit result table to build/export-test/sweep.tsv.
	//   Unity -batchmode -projectPath campaign -executeMethod WfExportTest.Sweep
	public static void Sweep()
	{
		try
		{
			string outDir = Path.GetFullPath(Path.Combine(Application.dataPath, "../../build/export-test"));
			Directory.CreateDirectory(outDir);
			GohFullUnitTemplateCache cache = Resources.Load<GohFullUnitTemplateCache>("GohFullUnitTemplateCache");
			StringBuilder table = new StringBuilder("tag\tunit\tresult\tobjects\tdetail\n");
			int ok = 0;
			int failed = 0;
			for (int f = 0; f < WfFactions.All.Length; f++)
			{
				string tag = WfFactions.All[f].Tag;
				GohUnitCatalog catalog = WfFactions.Catalog(tag);
				List<GohUnitCatalog> catalogs = new List<GohUnitCatalog> { catalog };
				GohFullUnitTemplateCacheAttacher.Attach(cache, catalogs);
				for (int i = 0; i < catalog.Entries.Count; i++)
				{
					GohUnitCatalogEntry entry = catalog.Entries[i];
					if (entry == null || entry.HideFromBattalionManagement)
					{
						continue;
					}
					GohObjectIdAllocator allocator = new GohObjectIdAllocator();
					BattalionRosterEntry rosterEntry = new BattalionRosterEntry { UnitName = entry.RawName, Quantity = 1 };
					bool built = GohCampaignObjectBuilder.TryBuild(rosterEntry, entry, "stage_1", tag, allocator, out GohCampaignScnObjectGraph graph, out string error);
					string warn = (graph != null && graph.Warnings != null && graph.Warnings.Count > 0) ? string.Join(" | ", graph.Warnings) : "";
					if (built)
					{
						ok++;
					}
					else
					{
						failed++;
					}
					table.Append(tag).Append('\t').Append(entry.RawName).Append('\t').Append(built ? "ok" : "FAIL").Append('\t')
						.Append(graph != null ? graph.ExportedObjectIds.Count : 0).Append('\t').Append(built ? warn : error).Append('\n');
				}
			}
			File.WriteAllText(Path.Combine(outDir, "sweep.tsv"), table.ToString(), new UTF8Encoding(false));
			Debug.Log("WfExportTest sweep: ok=" + ok + ", failed=" + failed);
			EditorApplication.Exit(0);
		}
		catch (Exception ex)
		{
			Debug.LogError("WfExportTest sweep FAILED: " + ex);
			EditorApplication.Exit(1);
		}
	}

	// Runs the application's own result reader and survivor importer on a save the game wrote after a
	// battle, then re-exports the imported battalion to prove preserved state survives a second trip.
	//   Unity -batchmode -projectPath campaign -executeMethod WfExportTest.Import -wfSav <path> -wfTag usa -wfUnits "a;b"
	public static void Import()
	{
		try
		{
			string tag = Arg("-wfTag", "usa");
			string sav = Arg("-wfSav", Path.GetFullPath(Path.Combine(Application.dataPath, "../../build/post-battle/post_battle.sav")));
			string[] units = Arg("-wfUnits", "squad1(usa);command_team_t2(usa);stryker_m2hb;humvee_m240").Split(';');
			string outDir = Path.GetDirectoryName(sav);
			StringBuilder report = new StringBuilder();

			GohBattleResultReader.ParsedStatusResult status = GohBattleResultReader.ReadStatusFromSav(sav);
			report.AppendLine("status valid=" + status.IsValid + " playedGames=" + status.PlayedGames + " wonGames=" + status.WonGames);
			// Export wrote playedGames 0 / wonGames 0; same rule as TryResolvePendingBattleFromSavStatus.
			bool finished = status.PlayedGames > 0;
			bool playerWon = status.WonGames > 0;
			report.AppendLine("finished=" + finished + " playerWon=" + playerWon);

			GohUnitCatalog catalog = WfFactions.Catalog(tag);
			GohFullUnitTemplateCacheAttacher.Attach(Resources.Load<GohFullUnitTemplateCache>("GohFullUnitTemplateCache"), new List<GohUnitCatalog> { catalog });
			BattalionData battalion = new BattalionData { BattalionId = "wf_test_battalion", GohFactionTag = tag, IsPlayerControlled = true };
			for (int i = 0; i < units.Length; i++)
			{
				battalion.Roster.Add(new BattalionRosterEntry { UnitName = units[i].Trim(), Quantity = 1 });
			}
			CampaignFactionState factionState = new CampaignFactionState { IsHumanControlled = true };
			BattalionTypeRulesAsset typeRules = AssetDatabase.LoadAssetAtPath<BattalionTypeRulesAsset>("Assets/MonoBehaviour/BattalionTypeRules.asset");

			if (!GohCampaignScnSquadImporter.TryReadCampaignScnFromSav(sav, out string scnText, out string readError))
			{
				throw new Exception("could not read campaign.scn from save: " + readError);
			}
			GohCampaignScnSquadImporter.ImportResult result = GohCampaignScnSquadImporter.ApplyToBattalion(battalion, factionState, scnText, sav, typeRules, catalog);
			report.AppendLine("import success=" + result.Success + " parsedSquads=" + result.ParsedSquads + " kept=" + result.KeptInBattalion
				+ " captured=" + result.CapturedMovedToPool + " overflow=" + result.OverflowMovedToPool + " unknownCategory=" + result.UnknownCategoryCount);
			report.AppendLine("message: " + result.Message);
			for (int i = 0; i < battalion.Roster.Count; i++)
			{
				BattalionRosterEntry e = battalion.Roster[i];
				int objects = 0;
				for (int s = 0; e.SquadStates != null && s < e.SquadStates.Count; s++)
				{
					objects += e.SquadStates[s].Objects != null ? e.SquadStates[s].Objects.Count : 0;
				}
				report.AppendLine("roster: " + e.UnitName + " x" + e.Quantity + " stage='" + e.Stage + "' squadStates=" + (e.SquadStates != null ? e.SquadStates.Count : 0) + " objects=" + objects);
			}
			report.AppendLine("pool entries: " + factionState.RecruitedPool.Count);

			string again = CampaignScnExporter.BuildCampaignScn(battalion, new List<GohUnitCatalog> { catalog });
			File.WriteAllText(Path.Combine(outDir, "reexport_campaign.scn"), again, new UTF8Encoding(false));
			report.AppendLine("re-export chars=" + again.Length);
			File.WriteAllText(Path.Combine(outDir, "import-report.txt"), report.ToString(), new UTF8Encoding(false));
			Debug.Log("WfExportTest import:\n" + report);
			EditorApplication.Exit(result.Success ? 0 : 1);
		}
		catch (Exception ex)
		{
			Debug.LogError("WfExportTest import FAILED: " + ex);
			EditorApplication.Exit(1);
		}
	}

	private static string Arg(string name, string fallback)
	{
		string[] args = Environment.GetCommandLineArgs();
		for (int i = 0; i < args.Length - 1; i++)
		{
			if (args[i] == name)
			{
				return args[i + 1];
			}
		}
		return fallback;
	}
}
