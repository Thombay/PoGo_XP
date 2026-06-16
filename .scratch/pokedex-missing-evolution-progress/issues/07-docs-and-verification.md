# Docs And Verification

Status: ready-for-agent
Type: task

## Problem

The Pokedex dashboard will use several related but distinct data sources. Future maintainers need clear docs so aggregate counts, species-level lists, category availability, and evolution unlocks are not confused.

## Scope

- Update project docs for aggregate Pokedex Entry Snapshots.
- Document release-aware target semantics for normal Pokemon versus non-normal categories.
- Document species-level completion CSV rows.
- Document category availability CSV rows.
- Document evolution reference CSV rows.
- Explain why aggregate count stats and exact missing lists can disagree.
- Run relevant tests and record manual Streamlit verification notes.

## Acceptance Criteria

- Docs explain where to edit current Pokemon GO availability targets.
- Docs explain where to edit species-level ownership and `can_evolve_now`.
- Docs explain where to edit Pokemon GO evolution edges.
- Verification commands are recorded in the implementation notes or PR.
- The local issue tracker remains the documented issue workflow.

## Testing

- Run the existing Pokedex tests.
- Run any new tests added by the implementation issues.
- Manually verify the Pokedex dashboard in Streamlit.

## Comments
