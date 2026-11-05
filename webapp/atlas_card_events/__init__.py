from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_atlas_card_events = None


def _component():
    global _atlas_card_events
    if _atlas_card_events is None:
        _atlas_card_events = components.declare_component(
            "atlas_card_events",
            path=Path(__file__).resolve().parent,
        )
    return _atlas_card_events


def atlas_card_event_dex(event: object) -> int | None:
    if not isinstance(event, dict):
        return None
    raw = event.get("dex")
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        dex = raw
    elif isinstance(raw, float) and raw.is_integer():
        dex = int(raw)
    elif isinstance(raw, str) and raw.strip().isdigit():
        dex = int(raw.strip())
    else:
        return None
    if dex <= 0:
        return None
    return dex


def atlas_card_event() -> object:
    # A normal link reloads the app, which drops the Pokédex page and session.
    # This iframe listens for card clicks and dialog dismissals and reports them
    # back without leaving the page.
    return _component()(default=None, key="atlas_card_event")
