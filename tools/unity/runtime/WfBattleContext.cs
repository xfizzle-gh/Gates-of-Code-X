using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

// Copied into campaign/Assets/Scripts/WfCampaign by tools/patch_campaign_code.py.
// Writes the per-battle context that GoW's in-game Lua (gow_bridge.lua) reads, so WarFighter's AI fields
// the strategic enemy battalion instead of buying freely from its whole faction list.
public static class WfBattleContext
{
	// Share of a defending AI's opening garrison placed at the start. The rest is held in reserve and
	// arrives in timed bursts from the AI's side of the map.
	public const float OpeningShare = 0.5f;

	// Seconds between reserve bursts, and the purchase budget of one burst.
	public const int ReinforceIntervalSeconds = 150;
	public const int ReinforceBurst = 6;

	// WarFighter sizes the battle itself; the battalion's strength scales that. A battalion at full
	// strength fights at 1.5x WarFighter's normal budget, an almost empty one at 0.75x.
	public const float MinStrength = 0.75f;
	public const float MaxStrength = 1.5f;

	// A full-strength battalion in the recovered rules holds this many units.
	private const int FullBattalionUnits = 26;

	// Section weights for giving an abstract AI battalion a concrete composition:
	// Inf1, Inf2, Emplacements, Vehicles, Tanks (GohUnitSection 1..5).
	private static readonly int[] SectionWeights = { 0, 55, 15, 5, 15, 10 };

	public static string ContextPath => Path.Combine(Paths.GatesOfEuropaDocumentsDirectory, "gow_battle_context.lua");

	public static void Write(GohStatusExportContext context)
	{
		try
		{
			if (context == null || context.EnemyBattalion == null || string.IsNullOrWhiteSpace(context.EnemyArmyCode))
			{
				return;
			}
			Dictionary<string, int> roster = BuildRoster(context.EnemyBattalion, context.EnemyArmyCode);
			float strength = GetStrength(context.EnemyBattalion);
			System.Globalization.CultureInfo inv = System.Globalization.CultureInfo.InvariantCulture;
			StringBuilder sb = new StringBuilder();
			sb.AppendLine("-- Written by the GoW campaign application for one battle. Do not edit.");
			sb.AppendLine("GOW_BATTLE_ID = " + Quote(context.BattleName));
			sb.AppendLine("GOW_ENEMY_ARMY = " + Quote(context.EnemyArmyCode));
			sb.AppendLine("GOW_STRENGTH = " + strength.ToString("0.00", inv));
			sb.AppendLine("GOW_OPENING_SHARE = " + OpeningShare.ToString(inv));
			sb.AppendLine("GOW_REINFORCE_INTERVAL = " + ReinforceIntervalSeconds);
			sb.AppendLine("GOW_REINFORCE_BURST = " + ReinforceBurst);
			sb.AppendLine("GOW_ENEMY_TYPES = {");
			foreach (KeyValuePair<string, int> unit in roster)
			{
				sb.AppendLine("\t" + Quote(unit.Key) + ",");
			}
			sb.AppendLine("}");
			Directory.CreateDirectory(Path.GetDirectoryName(ContextPath));
			File.WriteAllText(ContextPath, sb.ToString(), new UTF8Encoding(false));
			string statePath = Path.Combine(Path.GetDirectoryName(ContextPath), "gow_battle_state.txt");
			if (File.Exists(statePath))
			{
				File.Delete(statePath);
			}
			Debug.Log("GoW battle context written: " + context.EnemyBattalion.BattalionId + " (" + context.EnemyArmyCode + "), " + roster.Count + " unit types -> " + ContextPath);
		}
		catch (Exception ex)
		{
			Debug.LogError("GoW battle context could not be written; the AI will buy from its full list.\n" + ex);
		}
	}

	public static float GetStrength(BattalionData battalion)
	{
		float ratio;
		if (battalion.AbstractMaxUnitCount > 0)
		{
			ratio = (float)battalion.AbstractUnitCount / battalion.AbstractMaxUnitCount;
		}
		else
		{
			int units = 0;
			for (int i = 0; battalion.Roster != null && i < battalion.Roster.Count; i++)
			{
				units += battalion.Roster[i] != null ? Mathf.Max(0, battalion.Roster[i].Quantity) : 0;
			}
			ratio = (float)units / FullBattalionUnits;
		}
		return Mathf.Lerp(MinStrength, MaxStrength, Mathf.Clamp01(ratio));
	}

	// A battalion with a real roster is used as it is. AI battalions are abstract (a unit count and a
	// strength level), so they get a composition drawn from the units WarFighter's AI can actually buy
	// for that faction. The draw is seeded by the battalion id, so the same battalion always fields
	// the same force until its strength changes.
	public static Dictionary<string, int> BuildRoster(BattalionData battalion, string armyTag)
	{
		Dictionary<string, int> roster = new Dictionary<string, int>();
		if (battalion.Roster != null)
		{
			for (int i = 0; i < battalion.Roster.Count; i++)
			{
				BattalionRosterEntry entry = battalion.Roster[i];
				if (entry != null && !string.IsNullOrWhiteSpace(entry.UnitName) && entry.Quantity > 0)
				{
					roster.TryGetValue(entry.UnitName, out int have);
					roster[entry.UnitName] = have + entry.Quantity;
				}
			}
		}
		if (roster.Count > 0)
		{
			return roster;
		}
		int count = Mathf.Max(1, battalion.AbstractUnitCount);
		System.Random random = new System.Random(StableHash(battalion.BattalionId + ":" + count));
		for (int i = 0; i < count; i++)
		{
			string unit = PickUnit(armyTag, random);
			if (unit == null)
			{
				break;
			}
			roster.TryGetValue(unit, out int have);
			roster[unit] = have + 1;
		}
		return roster;
	}

	private static string PickUnit(string armyTag, System.Random random)
	{
		int total = 0;
		for (int s = 1; s < SectionWeights.Length; s++)
		{
			if (WfAiUnits.For(armyTag, s).Length > 0)
			{
				total += SectionWeights[s];
			}
		}
		if (total == 0)
		{
			return null;
		}
		int roll = random.Next(total);
		for (int s = 1; s < SectionWeights.Length; s++)
		{
			string[] units = WfAiUnits.For(armyTag, s);
			if (units.Length == 0)
			{
				continue;
			}
			if (roll < SectionWeights[s])
			{
				return units[random.Next(units.Length)];
			}
			roll -= SectionWeights[s];
		}
		return null;
	}

	private static int StableHash(string value)
	{
		unchecked
		{
			uint hash = 2166136261u;
			for (int i = 0; i < value.Length; i++)
			{
				hash = (hash ^ value[i]) * 16777619u;
			}
			return (int)(hash & 0x7fffffff);
		}
	}

	private static string Quote(string value)
	{
		return "\"" + (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", " ").Replace("\r", " ") + "\"";
	}
}

public static partial class WfAiUnits
{
	private static readonly string[] None = new string[0];

	// Units of a faction's catalog section that WarFighter's conquest AI is able to buy.
	public static string[] For(string armyTag, int section)
	{
		return BySection.TryGetValue(armyTag + ":" + section, out string[] units) ? units : None;
	}
}
