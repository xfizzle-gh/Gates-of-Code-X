extends "res://scripts/tools/map_candidate_native_acceptance.gd"

## #212 E3 compatibility entrypoint.
##
## Snapshot loading now happens in the base harness before the expensive hybrid
## and composed presentation gates are activated. Keeping this thin entrypoint
## preserves existing CI/owner commands without rebuilding a throwaway cache.
