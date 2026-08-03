# Europe map and formation layer

## Map source boundary

The bundled compressed Europe graph is a clean-room data-contract reconstruction from the supplied Gates of Europa alpha runtime campaign state. It contains 517 stable province IDs and the observed reciprocal adjacency graph. It does not contain Unity scenes, textures, sprites, executable code, or other proprietary assets.

The alpha runtime exposed human-readable names for 63 provinces. The remaining nodes retain stable IDs and generated labels until the naming pass is completed. The runtime did not expose complete marker coordinates, so the current coordinates are a newly generated anchored graph layout intended for development and Godot map prototyping, not a claim that the original marker positions were recovered.

## Strategic formations

Strategic factions remain NATO, Ukraine, Russia, and PRC. Formations add national and doctrinal identity beneath those factions without requiring extra GoH army codes.

Initial identities include United States armored and airborne brigades, German Panzergrenadiers, Polish mechanized forces, a British battlegroup, Ukrainian mechanized and air-assault brigades, Russian tank, motor-rifle, VDV, and naval-infantry brigades, and PLA combined-arms and support formations.

The North Korean expeditionary brigade is provisional and Russia-aligned. It is represented as a foreign formation rather than a fifth strategic faction. PRC and North Korean deployment anchors are temporarily assigned to the graph's eastern development area and tagged `central_asia`; exact provinces will be revised during the map naming and ownership pass.

## Data authority

Formation preferences guide starter-roster selection, but the player's installed Code:X catalog remains authoritative for actual squads, vehicles, doctrines, and tactical definitions.
