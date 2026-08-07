shader_type canvas_item;

// Ownership LUT via UV.x. Geometry immutable.
// Cheap clean-room terrain tint (PR C: reduced noise cost vs PR B; visuals preserved).
uniform sampler2D ownership_colors : filter_nearest, repeat_disable;
uniform float ownership_mix : hint_range(0.0, 1.0) = 0.46;
uniform vec3 terrain_low = vec3(0.38, 0.43, 0.34);
uniform vec3 terrain_high = vec3(0.50, 0.48, 0.40);
uniform float terrain_contrast : hint_range(0.0, 1.0) = 0.18;

void fragment() {
	vec4 own = texture(ownership_colors, UV);
	// Single-hash terrain variation (no multi-octave value noise).
	vec2 p = floor(VERTEX.xy * 0.07);
	float n = fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
	float ridge = 0.5 + 0.5 * sin(VERTEX.x * 0.012) * cos(VERTEX.y * 0.01);
	vec3 terrain = mix(terrain_low, terrain_high, n);
	terrain *= mix(1.0 - terrain_contrast * 0.3, 1.0 + terrain_contrast * 0.2, ridge);
	vec3 tinted = mix(terrain, own.rgb, clamp(ownership_mix * own.a, 0.0, 1.0));
	COLOR = vec4(tinted, 1.0);
}
