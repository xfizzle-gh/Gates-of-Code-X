extends "res://scripts/main_perf_measured.gd"

## #221 startup telemetry layer.
## Emits one durable cross-process timing marker after the inherited strategic
## scene has completed `_ready()` and one process frame has elapsed. The epoch is
## set by the packaged Python entry script before importing the application.

const STARTUP_TELEMETRY_ENV := "GATES_OF_CODEX_STARTUP_TELEMETRY"
const STARTUP_EPOCH_ENV := "GATES_OF_CODEX_STARTUP_EPOCH_MS"


func _ready() -> void:
	super._ready()
	if OS.get_environment(STARTUP_TELEMETRY_ENV) != "1":
		return
	await get_tree().process_frame
	var raw := OS.get_environment(STARTUP_EPOCH_ENV).strip_edges()
	if raw.is_empty() or not raw.is_valid_float():
		return
	var started_ms := raw.to_float()
	var now_ms := Time.get_unix_time_from_system() * 1000.0
	var payload := {
		"stage": "first_usable_strategic_frame",
		"since_process_entry_ms": maxf(0.0, now_ms - started_ms),
	}
	print("GOC_STARTUP " + JSON.stringify(payload))
