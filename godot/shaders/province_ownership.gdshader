shader_type canvas_item;

// Ownership LUT via UV.x. Geometry immutable.
// Terrain: sample a small precomputed smooth noise texture (set from PolygonMap).
// Organic (no square cells), Compatibility-cheap (one texture fetch + mix).
uniform sampler2D ownership_colors : filter_nearest, repeat_disable;
uniform sampler2D terrain_noise : filter_linear, repeat_enable;
uniform float ownership_mix : hint_range(0.0, 1.0) = 0.46;
uniform vec3 terrain_low = vec3(0.38, 0.43, 0.34);
uniform vec3 terrain_high = vec3(0.50, 0.48, 0.40);
uniform float terrain_contrast : hint_range(0.0, 1.0) = 0.18;
uniform vec2 terrain_noise_scale = vec2(0.0045, 0.0045);
uniform vec2 terrain_noise_transform_x = vec2(0.92, 0.38);
uniform vec2 terrain_noise_transform_y = vec2(-0.31, 0.88);

void fragment() {
	vec4 own = texture(ownership_colors, UV);
	// Skewed domain so sampling is not axis-aligned to the map grid.
	vec2 p = VERTEX.xy;
	vec2 uv_n = vec2(
		dot(p, terrain_noise_transform_x),
		dot(p, terrain_noise_transform_y)
	) * terrain_noise_scale;
	float n = texture(terrain_noise, uv_n).r;
	float roll = 0.5 + 0.5 * sin(p.x * 0.008 + p.y * 0.006) * cos(p.x * 0.004 - p.y * 0.009);
	float elev = clamp(n * 0.75 + roll * 0.25, 0.0, 1.0);
	vec3 terrain = mix(terrain_low, terrain_high, elev);
	terrain *= mix(1.0 - terrain_contrast * 0.28, 1.0 + terrain_contrast * 0.18, elev);
	vec3 tinted = mix(terrain, own.rgb, clamp(ownership_mix * own.a, 0.0, 1.0));
	COLOR = vec4(tinted, 1.0);
}
