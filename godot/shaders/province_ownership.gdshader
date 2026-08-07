shader_type canvas_item;

// Ownership LUT sampled by UV.x (province index). Geometry is immutable.
// Clean-room procedural terrain base + translucent faction tint (no archive art).
uniform sampler2D ownership_colors : filter_nearest, repeat_disable;
uniform float ownership_mix : hint_range(0.0, 1.0) = 0.46;
uniform vec3 terrain_low = vec3(0.38, 0.43, 0.34);
uniform vec3 terrain_high = vec3(0.50, 0.48, 0.40);
uniform float terrain_contrast : hint_range(0.0, 1.0) = 0.22;

float hash21(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float value_noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	float a = hash21(i);
	float b = hash21(i + vec2(1.0, 0.0));
	float c = hash21(i + vec2(0.0, 1.0));
	float d = hash21(i + vec2(1.0, 1.0));
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

void fragment() {
	vec4 own = texture(ownership_colors, UV);
	// Multi-scale procedural land underlay (clean-room; not Earth3 archive art).
	float n1 = value_noise(VERTEX.xy * 0.035);
	float n2 = value_noise(VERTEX.xy * 0.11 + 17.0);
	float n3 = value_noise(VERTEX.xy * 0.28 + 41.0);
	float elev = clamp(n1 * 0.55 + n2 * 0.30 + n3 * 0.15, 0.0, 1.0);
	vec3 terrain = mix(terrain_low, terrain_high, elev);
	// Soft ridge shading for geographic readability without claiming real DEM authority.
	float ridge = 0.5 + 0.5 * sin(VERTEX.x * 0.012 + elev * 2.5) * cos(VERTEX.y * 0.01);
	terrain *= mix(1.0 - terrain_contrast * 0.35, 1.0 + terrain_contrast * 0.25, ridge);
	vec3 tinted = mix(terrain, own.rgb, clamp(ownership_mix * own.a, 0.0, 1.0));
	COLOR = vec4(tinted, 1.0);
}
