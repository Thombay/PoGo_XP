# Pokemon GO Progress Tracking

This context describes how player progress observations are named and related across XP, medal, and Pokédex tracking.

## Language

**Medal Snapshot**:
A dated account observation of medal progress as shown by the game's medal screen.
_Avoid_: species entry

**Species Entry**:
A dated account observation that a dex number, and an optional form, is registered for one kind.
_Avoid_: medal value, regional count

**Regional Pokédex Medal**:
A medal whose value counts registered Pokémon for one region.
_Avoid_: Pokédex count

## Relationships

- A **Medal Snapshot** can contain one or more **Regional Pokédex Medals**.
- A **Species Entry** records one account, one date, one kind, and one dex number with an optional form.
- Pokédex counts and progress are derived from **Species Entries** plus the Pokemon catalog and category availability.
- A **Regional Pokédex Medal** is a medal observation. It is not a Pokédex count.
- A **Regional Pokédex Medal** and a derived Pokédex count for the same account, date, and region may differ.

## Example Dialogue

> **Dev:** "Can we save the Kanto medal value as the Kanto Pokédex count?"
> **Domain expert:** "No — a regional medal is its own observation. Pokédex counts come from checked species entries."

## Flagged Ambiguities

- "Pokédex medal" and "Pokédex count" sound alike, but a regional medal is not a count of checked species entries.
