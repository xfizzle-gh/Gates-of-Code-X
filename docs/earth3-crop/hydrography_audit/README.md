# Earth3 hydrography audit

## Regenerate

```bash
set GATES_EARTH3_ARCHIVE=/path/to/AOH3_Earth3_map_provinces.zip
python tools/earth3/hydrography_audit_main.py --archive %GATES_EARTH3_ARCHIVE%
```

**Authoritative entry:** `tools/earth3/hydrography_audit_main.py`

- Geometry: emitted **triangle union** only (no convex hull / synthetic circle)
- Metrics: local **Lambert azimuthal equal-area** meters
- Production path is never modified
- Kolguyev preview is not production

Superseded: `build_hydrography_audit.py`, `build_hydrography_audit_v2.py`, `build_hydrography_georef.py`
