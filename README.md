# Warfighter Campaign

Adaptation of the Gates of Europa strategic campaign to the WarFighter GoH mod, following
`docs/implementation-plan.txt`. Progress and blockers are tracked in `docs/milestone-log.md`.

## Layout

| Path | Contents | In git |
| --- | --- | --- |
| `docs/` | plan, milestone log, round-trip trace, feature-parity matrix | yes |
| `tools/` | baseline capture, extraction and archive indexing | yes |
| `evidence/` | baseline summary, provenance; manifests and archive indexes are regenerated | partly |
| `upstream/` | unmodified GOE extraction | no |
| `recovered/` | decompiled reference source | no |
| `build/` | local tools and build output | no |

`campaign/`, `integration-mod/`, `adapters/`, `data/` and `tests/` are created when their milestones start.

## Reproduce the baseline

```
python tools/baseline.py all
dotnet tool install ilspycmd --version 9.1.0.7988 --tool-path build\tools
build\tools\ilspycmd.exe -p -o recovered\csharp -r upstream\goe-portable\current\GatesofEuropa_Data\Managed upstream\goe-portable\current\GatesofEuropa_Data\Managed\Assembly-CSharp.dll
```

Installation roots are in `tools/paths.json`. The tools only read from the GOE, WF and game folders.
