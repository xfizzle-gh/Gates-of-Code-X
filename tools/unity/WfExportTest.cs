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
