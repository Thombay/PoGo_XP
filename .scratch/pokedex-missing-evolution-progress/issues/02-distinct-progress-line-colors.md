# Distinct Progress Line Colors

Status: ready-for-agent
Type: feature

## Problem

The overall progress chart colors lines by account and uses entry type as line style. When several accounts and categories are visible, lines can be hard to distinguish.

## Scope

- Build chart series identity from account plus entry type.
- Add a readable label such as `Thombay - Shiny`.
- Generate deterministic colors for every visible series identity.
- Keep marker and line colors aligned.
- Preserve sensible legend ordering for selected accounts and entry types.

## Acceptance Criteria

- Every visible progress line has a distinct color where the palette allows it.
- The same account/category pair gets the same color across rerenders.
- The legend clearly identifies account and entry type.
- Existing account color helpers are not broken for other dashboard pages.

## Testing

- Add focused tests for any pure series-label or color-key helper.
- Manually verify the Streamlit progress chart with multiple accounts and categories.

## Comments
