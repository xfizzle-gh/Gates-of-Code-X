class_name StrategicMapLayerControl
extends PanelContainer

signal layer_toggled(layer_key: String, enabled: bool)

## #212 Phase D compact debug-only layer control. This prototype is intentionally
## event-driven and does not implement _process(). It is not mounted by main.tscn.

var _boxes: Dictionary = {}
var _built := false


func configure(toggles: Dictionary) -> void:
	if not _built:
		_build()
	for key_value in StrategicMapLodPolicy.LAYER_KEYS:
		var key := String(key_value)
		var box := _boxes.get(key) as CheckBox
		if box != null:
			box.set_pressed_no_signal(bool(toggles.get(key, false)))


func toggles() -> Dictionary:
	var result := {}
	for key_value in StrategicMapLodPolicy.LAYER_KEYS:
		var key := String(key_value)
		var box := _boxes.get(key) as CheckBox
		result[key] = box.button_pressed if box != null else false
	return result


func _build() -> void:
	_built = true
	custom_minimum_size = Vector2(220, 0)
	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 8)
	margin.add_theme_constant_override("margin_right", 8)
	margin.add_theme_constant_override("margin_top", 6)
	margin.add_theme_constant_override("margin_bottom", 6)
	add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 2)
	margin.add_child(column)
	var title := Label.new()
	title.text = "MAP LAYERS"
	column.add_child(title)
	for key_value in StrategicMapLodPolicy.LAYER_KEYS:
		var key := String(key_value)
		var box := CheckBox.new()
		box.text = key.replace("_", " ").capitalize()
		box.focus_mode = Control.FOCUS_NONE
		box.toggled.connect(_on_box_toggled.bind(key))
		column.add_child(box)
		_boxes[key] = box


func _on_box_toggled(enabled: bool, key: String) -> void:
	layer_toggled.emit(key, enabled)
