# Gates of CodeX implementation report

Gates of CodeX is a standalone strategic campaign application and Dynamic Conquest bridge for Call to Arms: Gates of Hell with Code:X.

## Implemented systems

- NATO, Ukraine, Russia, and PRC strategic factions
- Province ownership, adjacency, resources, fortifications, and display coordinates
- Persistent battalions, rosters, movement, capture, battles, casualties, retreat, supply, and turns
- Atomic JSON campaign persistence
- Steam, Gates of Hell, profile, Workshop, and local Code:X discovery
- Runtime Code:X `.set` and Lua catalog scanning
- Dynamic starter rosters generated from the installed Code:X catalog
- Dynamic Conquest `status`, `campaign.scn`, and `campaign.sav` generation
- Post-battle counter and surviving-squad import
- Export manifests that prevent stale or unrelated saves from being applied
- Command-line workflow, desktop strategic map, Windows installer, CI, and executable packaging

## Safety boundaries

The application does not replace Code:X tactical AI scripts. Code:X remains responsible for tactical purchasing, waves, capture behavior, doctrines, and mission logic. The repository contains newly written source code and no bundled third-party executable or game assets.

## Validation boundary

Automated tests cover campaign persistence, catalog scanning, roster generation, strategic movement, status generation, campaign-scene object graphs, archive handling, and CLI parsing. Final compatibility still requires a live Windows test against the currently installed versions of Gates of Hell and Code:X.
