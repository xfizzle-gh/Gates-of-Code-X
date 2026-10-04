using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

// Copied into campaign/Assets/Editor by tools/build_campaign.ps1.
public static class WfBuild
{
	public static void BuildWindows()
	{
		string[] scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
		if (scenes.Length == 0)
		{
			scenes = new[] { "Assets/Scenes/StartMenu.unity", "Assets/Scenes/SampleScene.unity" };
		}
		Debug.Log("WfBuild scenes: " + string.Join(", ", scenes));
		BuildReport report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
		{
			scenes = scenes,
			locationPathName = "../build/campaign-win64/WarfighterCampaign.exe",
			target = BuildTarget.StandaloneWindows64,
			options = BuildOptions.None
		});
		Debug.Log("WfBuild result: " + report.summary.result + ", errors: " + report.summary.totalErrors + ", size: " + report.summary.totalSize);
		EditorApplication.Exit(report.summary.result == BuildResult.Succeeded ? 0 : 1);
	}
}
