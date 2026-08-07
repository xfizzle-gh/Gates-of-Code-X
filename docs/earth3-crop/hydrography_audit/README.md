# Earth3 hydrography audit

## Regenerate

```bash
set GATES_EARTH3_ARCHIVE=/path/to/AOH3_Earth3_map_provinces.zip
python tools/earth3/hydrography_audit_main.py --archive %GATES_EARTH3_ARCHIVE%
```

**Authoritative entry:** `tools/earth3/hydrography_audit_main.py`

- Geometry: emitted **triangle union** only
- Metrics: local **LAEA meters**
- Source **11836 is NOT Kolguyev** (mainland Fion / northern Urals)
- Actual Kolguyev island source remains a separate search (`kolguyev_true_island_search.json`)
- Production path is never modified

Diagnostic preview (not production): `godot/assets/maps/earth3_europe_mediterranean_src11836_preview/`
