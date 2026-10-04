using System.Collections.Generic;
using UnityEngine;

// Copied into campaign/Assets/Scripts/WfCampaign by tools/patch_campaign_code.py.
// The recovered code keys everything on the FactionType integer slot and on four hard-wired WWII
// catalogs. These helpers resolve catalogs and research trees by WarFighter army tag instead.
public class WfFaction
{
	public readonly string Tag;
	public readonly string Name;
	public readonly FactionType Slot;

	public WfFaction(string tag, string name, FactionType slot)
	{
		Tag = tag;
		Name = name;
		Slot = slot;
	}
}

public static partial class WfFactions
{
	private static readonly Dictionary<string, GohUnitCatalog> catalogs = new Dictionary<string, GohUnitCatalog>();
	private static readonly Dictionary<string, GohResearchTreeAsset> trees = new Dictionary<string, GohResearchTreeAsset>();

	// choice is the faction dropdown index, stored in saves as FactionChoice.
	public static FactionType SlotForChoice(int choice)
	{
		return All[Mathf.Clamp(choice, 0, All.Length - 1)].Slot;
	}

	public static WfFaction ForSlot(FactionType slot)
	{
		for (int i = 0; i < All.Length; i++)
		{
			if (All[i].Slot == slot)
			{
				return All[i];
			}
		}
		return null;
	}

	// Player-facing name for a slot. The enum identifiers are still the WWII ones.
	public static string NameOf(FactionType slot)
	{
		WfFaction faction = ForSlot(slot);
		if (faction != null)
		{
			return faction.Name;
		}
		return (slot == FactionType.Neutral) ? "Neutral" : "Unassigned";
	}

	public static Sprite Flag(string tag)
	{
		return Resources.Load<Sprite>("WfContent/Flags/flag_" + tag);
	}

	public static List<string> DisplayNames()
	{
		List<string> list = new List<string>();
		for (int i = 0; i < All.Length; i++)
		{
			list.Add(All[i].Name);
		}
		return list;
	}

	public static GohUnitCatalog Catalog(string tag)
	{
		if (string.IsNullOrWhiteSpace(tag))
		{
			return null;
		}
		if (!catalogs.TryGetValue(tag, out var value))
		{
			value = Resources.Load<GohUnitCatalog>("WfContent/GohUnitCatalog_" + tag);
			catalogs[tag] = value;
		}
		return value;
	}

	public static GohResearchTreeAsset ResearchTree(string tag)
	{
		if (string.IsNullOrWhiteSpace(tag))
		{
			return null;
		}
		if (!trees.TryGetValue(tag, out var value))
		{
			value = Resources.Load<GohResearchTreeAsset>("WfContent/GohResearchTree_" + tag);
			trees[tag] = value;
		}
		return value;
	}

	public static GohUnitCatalog[] AllCatalogs()
	{
		List<GohUnitCatalog> list = new List<GohUnitCatalog>();
		for (int i = 0; i < All.Length; i++)
		{
			GohUnitCatalog catalog = Catalog(All[i].Tag);
			if (catalog != null)
			{
				list.Add(catalog);
			}
		}
		return list.ToArray();
	}
}
