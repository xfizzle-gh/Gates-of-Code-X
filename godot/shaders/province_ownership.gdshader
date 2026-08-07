shader_type canvas_item;

uniform sampler2D ownership_colors : filter_nearest, repeat_disable;

void fragment() {
	COLOR = texture(ownership_colors, UV);
}
