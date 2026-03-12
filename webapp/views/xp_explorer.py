from __future__ import annotations

from typing import Any, Callable


def render_xp_explorer_section_view(
    *,
    render_impl: Callable[..., Any],
    xp_subset_df: Any,
    key_prefix: str,
    medal_subset_df: Any = None,
    show_personal_activity: bool = False,
    additional_subset_df: Any = None,
    show_global_activity_trends: bool = False,
    activity_window_days: int = 7,
) -> None:
    render_impl(
        xp_subset_df=xp_subset_df,
        key_prefix=key_prefix,
        medal_subset_df=medal_subset_df,
        show_personal_activity=show_personal_activity,
        additional_subset_df=additional_subset_df,
        show_global_activity_trends=show_global_activity_trends,
        activity_window_days=activity_window_days,
    )
