extends SceneTree

## Adversarial harness fixture for the owner-observed false PASS.
## A dependency compile failure must not let this runner claim success.

func _initialize() -> void:
	var broken: Variant = load("res://scripts/tools/broken_extends_layer.gd")
	print("script_error_false_pass_fixture: loaded=", broken)
	print("script_error_false_pass_fixture: PASS")
	quit(0)
