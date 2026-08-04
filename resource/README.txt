Gates of Code:X runtime overlay.

Compatibility shims that must load after West81 / Code:X / AI Overhaul:

- set/interaction_entity/vehicle/Missile_settings1.inc
  Code:X flares_and_chaff.inc includes this exact case. West81 only ships
  missile_settings1.inc (lowercase). GoH virtual FS is case-sensitive, so the
  missing capital-M name crashes Conquest load.
