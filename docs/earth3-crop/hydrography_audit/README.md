# Earth3 hydrography audit

## Regenerate

```bash
set GATES_EARTH3_ARCHIVE=/path/to/AOH3_Earth3_map_provinces.zip
python tools/earth3/hydrography_audit_main.py --archive %GATES_EARTH3_ARCHIVE%
```

**Authoritative entry point:** `tools/earth3/hydrography_audit_main.py`

Superseded helpers (do not use): `build_hydrography_audit.py`, `build_hydrography_audit_v2.py`, `build_hydrography_georef.py`.

Production path is never modified.
