# Expanded Nations activation architecture

## Authority

The accepted faction compiler and actor runtime remain authoritative for actor identity, roster membership, research, economy, and tactical-side export. This activation layer only translates one selected actor into native Gates of Hell Conquest files.

## Core boundary

Core Code:X has no generated final-layer roster or research override. Removing the verified managed projection restores inherited Code:X behavior.

## Expanded boundary

Expanded mode creates exactly three generated files under the final Gates layer:

1. the native roster root;
2. one selected-actor purchase-definition file;
3. one selected-actor research file for the actor's tactical side.

The roster root includes canonical settings and infantry settings, then only the selected actor unit file. It never includes a broad tactical-side unit roster.

## Provenance

Purchase definitions are extracted at activation time from exact source files recorded by the resolved payload. Later stack priority remains authoritative. The source entry is retained except for rewriting its single tactical `side(...)` declaration to the selected actor's export side. Virtual units resolve only through committed Gates wrapper definitions.

No upstream source definition is committed by this feature. No upstream tree is modified.

## Safety

Generated files carry hashes in `live/expanded_nations/active.json`. Switching and deactivation verify those hashes before changing files. Unmanaged files at managed paths cause a fail-closed stop. Installation stages all new files before replacement and restores the previous projection on failure.

## Determinism

Actor units, research nodes, file order, layout, provenance rows, JSON, and signatures use stable sorting. Repeated activation from identical payload and stack bytes must produce byte-identical output.
