using System.Collections.Generic;
using UnityEditor.Build;
using UnityEditor.Rendering;
using UnityEngine;
using UnityEngine.Rendering;

// Copied into campaign/Assets/Editor by tools/build_campaign.ps1.
// URP's own variant stripping lives in its editor assembly, which the recovered project does not have.
// Without it the post-processing shaders compile tens of thousands of variants. This drops XR passes
// and variants for features a windowed SDR 2D strategy map does not use.
public class WfShaderStripper : IPreprocessShaders
{
	private static readonly string[] StrippedKeywords =
	{
		"_FILM_GRAIN", "_DITHERING", "_CHROMATIC_ABERRATION", "_DISTORTION", "_GAMMA_20", "_LINEAR_TO_SRGB_CONVERSION",
		"_RCAS", "_EASU_RCAS_AND_HDR_INPUT", "_POINT_SAMPLING", "_ENABLE_ALPHA_OUTPUT", "_USE_FAST_SRGB_LINEAR_CONVERSION",
		"HDR_INPUT", "HDR_COLORSPACE_CONVERSION", "HDR_ENCODING", "HDR_COLORSPACE_CONVERSION_AND_ENCODING",
		"SCREEN_COORD_OVERRIDE", "_FOVEATED_RENDERING_NON_UNIFORM_RASTER", "USE_FOVEATED_RENDERING",
		"_BLOOM_HQ_DIRT", "_BLOOM_LQ_DIRT", "_HDR_GRADING", "DEBUG_DISPLAY",
	};

	public int callbackOrder => 0;

	public void OnProcessShader(Shader shader, ShaderSnippetData snippet, IList<ShaderCompilerData> data)
	{
		if (!shader.name.StartsWith("Hidden/Universal") && !shader.name.StartsWith("Hidden/Core"))
		{
			return;
		}
		bool xr = snippet.passName.EndsWith("XR") || shader.name.Contains("/XR/");
		int before = data.Count;
		for (int i = data.Count - 1; i >= 0; i--)
		{
			if (xr || HasStrippedKeyword(shader, data[i].shaderKeywordSet))
			{
				data.RemoveAt(i);
			}
		}
		if (before > 64)
		{
			Debug.Log("WfShaderStripper: " + shader.name + " [" + snippet.passName + "] " + before + " -> " + data.Count);
		}
	}

	private static bool HasStrippedKeyword(Shader shader, ShaderKeywordSet set)
	{
		for (int i = 0; i < StrippedKeywords.Length; i++)
		{
			if (set.IsEnabled(new ShaderKeyword(shader, StrippedKeywords[i])) || set.IsEnabled(new ShaderKeyword(StrippedKeywords[i])))
			{
				return true;
			}
		}
		return false;
	}
}
