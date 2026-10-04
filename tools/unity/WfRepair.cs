using TMPro;
using UnityEditor;
using UnityEngine;

// Copied into campaign/Assets/Editor by tools/build_campaign.ps1.
public static class WfRepair
{
	// Dynamic TMP font assets are stripped of their atlas at build time, so AssetRipper recovers a
	// dangling texture reference. Give each one a fresh empty atlas; TMP fills it from the source font.
	public static void RepairFontAtlases()
	{
		int repaired = 0;
		foreach (string guid in AssetDatabase.FindAssets("t:TMP_FontAsset"))
		{
			string path = AssetDatabase.GUIDToAssetPath(guid);
			TMP_FontAsset font = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(path);
			if (font == null || font.atlasPopulationMode != AtlasPopulationMode.Dynamic)
			{
				continue;
			}
			Texture2D[] atlases = font.atlasTextures;
			if (atlases != null && atlases.Length > 0 && atlases[0] != null)
			{
				continue;
			}
			if (font.sourceFontFile == null)
			{
				Debug.LogWarning("WfRepair: " + path + " has no source font file; left unrepaired.");
				continue;
			}
			Texture2D atlas = new Texture2D(1, 1, TextureFormat.Alpha8, false) { name = font.name + " Atlas" };
			AssetDatabase.AddObjectToAsset(atlas, font);
			font.atlasTextures = new[] { atlas };
			if (font.material != null)
			{
				font.material.SetTexture(ShaderUtilities.ID_MainTex, atlas);
				EditorUtility.SetDirty(font.material);
			}
			font.ClearFontAssetData(true);
			EditorUtility.SetDirty(font);
			repaired++;
			Debug.Log("WfRepair: new atlas for " + path);
		}
		AssetDatabase.SaveAssets();
		Debug.Log("WfRepair: font assets repaired: " + repaired);
	}
}
