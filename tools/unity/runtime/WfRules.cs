using System;
using System.Collections.Generic;
using UnityEngine;

// Copied into campaign/Assets/Scripts/WfCampaign by tools/patch_campaign_code.py.
// Campaign rules GoW changes or adds on top of the recovered game.
public static class WfRules
{
	// Recruiting. A Manpower-specialization province is a deployment hub: where a faction's forces
	// enter that theater. A battalion can be raised on the hub or in any province of the same owner
	// next to it, so a hub with a battalion standing on it does not block reinforcement.
	public static bool IsRecruitProvince(ProvinceDefinition province, Dictionary<string, ProvinceDefinition> provincesById)
	{
		if (province == null)
		{
			return false;
		}
		if (province.ParsedSpecialization == ProvinceSpecialization.Manpower)
		{
			return true;
		}
		if (province.NeighborProvinceIds == null || provincesById == null)
		{
			return false;
		}
		for (int i = 0; i < province.NeighborProvinceIds.Count; i++)
		{
			if (provincesById.TryGetValue(province.NeighborProvinceIds[i], out ProvinceDefinition neighbour) && neighbour != null
				&& neighbour.Owner == province.Owner && neighbour.ParsedSpecialization == ProvinceSpecialization.Manpower)
			{
				return true;
			}
		}
		return false;
	}

	public static bool IsRecruitProvince(ProvinceDefinition province, CampaignState campaignState)
	{
		if (province == null || campaignState == null || campaignState.Provinces == null)
		{
			return province != null && province.ParsedSpecialization == ProvinceSpecialization.Manpower;
		}
		// The campaign state holds current owners; static definitions hold the starting ones.
		Dictionary<string, ProvinceDefinition> current = new Dictionary<string, ProvinceDefinition>();
		ProvinceDefinition self = province;
		for (int i = 0; i < campaignState.Provinces.Count; i++)
		{
			ProvinceDefinition p = campaignState.Provinces[i];
			if (p != null && !string.IsNullOrEmpty(p.ProvinceId))
			{
				current[p.ProvinceId] = p;
				if (p.ProvinceId == province.ProvinceId)
				{
					self = p;
				}
			}
		}
		return IsRecruitProvince(self, current);
	}
}

// Starting order of battle. The scenario describes a war already under way, so each faction begins with
// covering forces on its fronts and at least one battalion in every separate territory. Without them the
// first turn was a race through undefended provinces.
public static class WfOrderOfBattle
{
	[Serializable]
	public class Entry
	{
		public string tag;
		public string province;
		public int strength;
	}

	[Serializable]
	public class Table
	{
		public List<Entry> battalions = new List<Entry>();
	}

	// Units in a human player's starting battalion.
	private const int PlayerStartingUnits = 8;

	public static void Apply(CampaignState state, BattalionTypeRulesAsset typeRules, Func<FactionType, bool> isHuman)
	{
		try
		{
			TextAsset asset = Resources.Load<TextAsset>("WfContent/order_of_battle");
			if (state == null || asset == null)
			{
				return;
			}
			Table table = JsonUtility.FromJson<Table>(asset.text);
			Dictionary<string, ProvinceDefinition> provinces = new Dictionary<string, ProvinceDefinition>();
			for (int i = 0; i < state.Provinces.Count; i++)
			{
				provinces[state.Provinces[i].ProvinceId] = state.Provinces[i];
			}
			Dictionary<string, int> perFaction = new Dictionary<string, int>();
			int placed = 0;
			for (int i = 0; i < table.battalions.Count; i++)
			{
				Entry entry = table.battalions[i];
				WfFaction faction = FindFaction(entry.tag);
				if (faction == null || !provinces.TryGetValue(entry.province, out ProvinceDefinition province)
					|| province.Owner != faction.Slot || !string.IsNullOrEmpty(province.OccupyingBattalionId))
				{
					continue;
				}
				perFaction.TryGetValue(entry.tag, out int index);
				perFaction[entry.tag] = index + 1;
				bool human = isHuman != null && isHuman(faction.Slot);
				BattalionData battalion = new BattalionData
				{
					BattalionId = entry.tag + "_start_" + (index + 1),
					Faction = faction.Slot,
					ProvinceId = entry.province,
					IsPlayerControlled = human,
					GohFactionTag = entry.tag,
					BattalionType = BattalionType.Infantry,
					Roster = new List<BattalionRosterEntry>(),
					RemainingMovement = BattalionRulesValidator.GetMovementAllowance(typeRules, BattalionType.Infantry),
					FriendlyTerritoryMovementRemaining = 1,
					RemainingCombatActions = 1
				};
				if (human)
				{
					// A human's battalions need real units: battle export writes them into the save.
					Dictionary<string, int> units = WfBattleContext.DrawUnits(entry.tag, battalion.BattalionId, PlayerStartingUnits);
					foreach (KeyValuePair<string, int> unit in units)
					{
						battalion.Roster.Add(new BattalionRosterEntry { UnitName = unit.Key, Quantity = unit.Value });
					}
					BattalionStrengthUtility.RefreshPlayerRosterStrength(battalion, typeRules);
				}
				else
				{
					BattalionStrengthUtility.InitializeAiAbstractStrength(battalion, typeRules, (BattalionStrengthLevel)Mathf.Clamp(entry.strength, 0, 3));
				}
				state.Battalions.Add(battalion);
				province.OccupyingBattalionId = battalion.BattalionId;
				placed++;
			}
			Debug.Log("GoW order of battle: placed " + placed + " starting battalions.");
		}
		catch (Exception ex)
		{
			Debug.LogError("GoW order of battle could not be applied; the campaign starts without armies.\n" + ex);
		}
	}

	private static WfFaction FindFaction(string tag)
	{
		for (int i = 0; i < WfFactions.All.Length; i++)
		{
			if (WfFactions.All[i].Tag == tag)
			{
				return WfFactions.All[i];
			}
		}
		return null;
	}
}
