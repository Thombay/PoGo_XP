# Missing Pokemon Lists

Status: ready-for-agent
Type: feature

## Problem

The dashboard needs to show which exact Pokemon are missing per account, entry type, and region. This cannot be inferred from aggregate counts, so it must use species-level state plus target availability.

## Scope

- Add editable local CSV data for category availability with columns `entry_type,dex_number,available,notes`.
- For `pokemon`, use full catalog targets.
- For non-`pokemon` categories, use the category availability reference as the target set.
- Build a pure helper that returns missing Pokemon by account, category, and region.
- Include dex number, name, German name, region, category, account, availability notes, and species notes.
- Keep source labels clear so users know this is species-level list data.

## Acceptance Criteria

- Missing list filters by account, entry type, and region.
- Registered species are excluded.
- Unavailable category targets are excluded.
- Normal `pokemon` uses full catalog targets without needing category availability rows.
- Non-normal categories only list currently available targets.

## Testing

- Add tests for normal `pokemon` missing lists.
- Add tests for non-normal category availability.
- Add tests for registered versus missing rows.
- Add tests showing aggregate counts are not required to produce exact missing lists.

## Comments
