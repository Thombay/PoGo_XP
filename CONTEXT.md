# Pokemon GO Progress Tracking

This context describes how player progress observations are named and related across XP, medal, and Pokédex tracking.

## Language

**Medal Snapshot**:
A dated account observation of medal progress as shown by the game's medal screen.
_Avoid_: Pokédex entry save

**Pokédex Entry Snapshot**:
A dated account observation of Pokédex counts by entry type and region.
_Avoid_: medal save

**Regional Pokédex Medal**:
A medal whose value counts registered Pokémon for one region.
_Avoid_: Pokédex entry count

**Pokédex Entry Count**:
A count from the Pokédex entry view for one entry type and region.
_Avoid_: medal value

## Relationships

- A **Medal Snapshot** can contain one or more **Regional Pokédex Medals**.
- A **Pokédex Entry Snapshot** contains one or more **Pokédex Entry Counts**.
- A **Regional Pokédex Medal** and a **Pokédex Entry Count** for the same account, date, and region may differ.
- A **Regional Pokédex Medal** can be used as a reference observation for a **Pokédex Entry Count**, but it does not define it.
- Regional `pokemon` counts are **Pokédex Entry Counts**, not derived **Regional Pokédex Medals**.
- Historical regional `pokemon` counts may be initialized from **Regional Pokédex Medals** when no direct **Pokédex Entry Snapshot** exists; new observations are captured separately.
- Regional `pokemon` counts are saved as a complete **Pokédex Entry Snapshot** category for the selected account and date.
- `pokemon/unidentified` is a Pokédex-only count with no matching **Regional Pokédex Medal**.
- Pokédex input main values come from **Pokédex Entry Snapshots**; **Regional Pokédex Medals** are shown separately as reference values.
- Historical seeding copies all available **Regional Pokédex Medal** history into missing regional `pokemon` **Pokédex Entry Counts**.
- Historical seeding never overwrites existing **Pokédex Entry Counts**, but intentional Pokédex entry saves may later replace seeded approximations for the same date.

## Example Dialogue

> **Dev:** "Can we save the Kanto medal value as the Kanto Pokédex entry count?"
> **Domain expert:** "No — those values can differ, so medal progress and Pokédex entries must be captured separately."

## Flagged Ambiguities

- "Pokédex medal save" and "Pokédex entry save" sounded like the same save flow, but they are distinct observations and may produce different values.
- Historical regional `pokemon` counts seeded from medals are approximate; newly saved regional `pokemon` counts are direct Pokédex observations.
