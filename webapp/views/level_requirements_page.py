from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from webapp.level_requirements import (
    REQUIREMENT_LEVELS,
    XP_REQUIREMENT_ID,
    LevelSet,
    RequirementRow,
    active_progress_timeline,
    build_level_sets,
    is_platinum_requirement,
    other_account_names,
    progression_start_date,
    upsert_level_requirement_progress,
)

_OTHER_ACCOUNT_KEY = "level_requirements_other_account"

_PROGRESSION_COLORS = (
    "#4C78A8",
    "#F58518",
    "#54A24B",
    "#E45756",
    "#72B7B2",
    "#B279A2",
    "#EECA3B",
    "#9D755D",
    "#FF9DA6",
    "#BAB0AC",
)


def _clear_other_account() -> None:
    st.session_state[_OTHER_ACCOUNT_KEY] = "None"


def render_level_requirements_page(
    *,
    xp_df: pd.DataFrame,
    curve_totals: dict[int, int],
    requirements_df: pd.DataFrame,
    progress_df: pd.DataFrame,
    progress_path: Path,
    medal_df: pd.DataFrame | None = None,
    accounts: list[str] | None = None,
) -> None:
    st.subheader("Level Requirements")
    options = _account_options(xp_df, accounts)
    if not options:
        st.info("No personal accounts with XP history.")
        return

    account_key = "level_requirements_account"
    if account_key in st.session_state and st.session_state[account_key] not in options:
        st.session_state[account_key] = options[0]
    default_index = options.index("Thombay") if "Thombay" in options else 0

    other_names = other_account_names(_account_names(xp_df), options)
    other_options = ["None", *other_names]
    if other_names and _OTHER_ACCOUNT_KEY in st.session_state and st.session_state[_OTHER_ACCOUNT_KEY] not in other_options:
        st.session_state[_OTHER_ACCOUNT_KEY] = "None"

    account_col, other_col = st.columns(2)
    account = account_col.selectbox(
        "Account",
        options=options,
        index=default_index,
        key=account_key,
        on_change=_clear_other_account,
    )
    other_account = "None"
    if other_names:
        other_account = other_col.selectbox(
            "Other account",
            options=other_options,
            index=0,
            key=_OTHER_ACCOUNT_KEY,
        )
    displayed = str(account) if other_account == "None" else str(other_account)

    window_days = st.radio(
        "Window",
        options=[7, 30],
        index=0,
        format_func=lambda days: f"{int(days)} days",
        horizontal=True,
        key="level_requirements_window",
    )
    as_of = pd.Timestamp.today().normalize()
    sets = build_level_sets(
        requirements=requirements_df,
        progress=progress_df,
        xp_history=xp_df,
        curve_totals=curve_totals,
        account=displayed,
        window_days=int(window_days),
        as_of=as_of,
        levels=REQUIREMENT_LEVELS,
        platinum=medal_df,
    )
    if not sets:
        st.info("No XP history for this account.")
        return

    reached = [level_set for level_set in sets if level_set.status == "reached"]
    active = [level_set for level_set in sets if level_set.status == "active"]
    locked = [level_set for level_set in sets if level_set.status == "locked"]

    reached_text = _reached_summary(reached)
    showed_prior = False
    if reached_text:
        st.write(reached_text)
        showed_prior = True

    for level_set in active:
        if showed_prior:
            st.divider()
        _render_active_set(
            level_set,
            account=displayed,
            progress_path=progress_path,
            as_of=as_of,
            xp_df=xp_df,
            progress_df=progress_df,
            curve_totals=curve_totals,
            medal_df=medal_df,
        )
        showed_prior = True

    if locked:
        if showed_prior:
            st.divider()
        _render_locked_section(locked)


def _account_names(xp_df: pd.DataFrame) -> list[str]:
    if xp_df.empty or "Spieler" not in xp_df.columns:
        return []
    names = xp_df["Spieler"].dropna().astype(str).str.strip()
    return sorted({name for name in names.tolist() if name})


def _account_options(xp_df: pd.DataFrame, accounts: list[str] | None) -> list[str]:
    known = set(_account_names(xp_df))
    if accounts is None:
        return sorted(known)
    options: list[str] = []
    seen: set[str] = set()
    for raw_name in accounts:
        name = str(raw_name).strip()
        if not name or name in seen or name not in known:
            continue
        seen.add(name)
        options.append(name)
    return options


def _reached_summary(reached: list[LevelSet]) -> str | None:
    if not reached:
        return None
    levels = sorted(int(level_set.target_level) for level_set in reached)
    if len(levels) == 1:
        return f"Level {levels[0]} complete"
    consecutive = all(right - left == 1 for left, right in zip(levels, levels[1:]))
    if consecutive:
        return f"Levels {levels[0]}\u2013{levels[-1]} complete"
    listed = ", ".join(str(level) for level in levels)
    return f"Levels {listed} complete"


def _render_active_set(
    level_set: LevelSet,
    *,
    account: str,
    progress_path: Path,
    as_of: pd.Timestamp,
    xp_df: pd.DataFrame,
    progress_df: pd.DataFrame,
    curve_totals: dict[int, int],
    medal_df: pd.DataFrame | None,
) -> None:
    st.markdown(f"#### Level {level_set.target_level}")
    _render_active_summary(level_set)
    st.plotly_chart(
        _finish_tracker(level_set, as_of),
        use_container_width=True,
        config={"displayModeBar": False},
    )
    _render_progression_graph(
        level_set,
        xp_df=xp_df,
        progress_df=progress_df,
        curve_totals=curve_totals,
        account=account,
        medal_df=medal_df,
    )
    for row in level_set.rows:
        _render_active_row(row)
    _render_log_form(level_set, account=account, progress_path=progress_path)


def _render_progression_graph(
    level_set: LevelSet,
    *,
    xp_df: pd.DataFrame,
    progress_df: pd.DataFrame,
    curve_totals: dict[int, int],
    account: str,
    medal_df: pd.DataFrame | None,
) -> None:
    timeline = active_progress_timeline(
        level_set,
        xp_history=xp_df,
        progress=progress_df,
        curve_totals=curve_totals,
        account=account,
        platinum=medal_df,
    )
    if not isinstance(timeline, pd.DataFrame) or timeline.empty:
        return
    start = progression_start_date(
        level_set,
        xp_history=xp_df,
        timeline=timeline,
        account=account,
    )
    if start is None:
        return
    timeline = timeline.copy()
    timeline["date"] = pd.to_datetime(timeline["date"], errors="coerce")
    timeline = timeline[timeline["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    if timeline.empty:
        return
    figure = _progression_figure(level_set, timeline, start=pd.Timestamp(start))
    if figure is None:
        return
    st.plotly_chart(
        figure,
        use_container_width=True,
        config={"displayModeBar": False},
    )


def _progression_figure(
    level_set: LevelSet,
    timeline: pd.DataFrame,
    *,
    start: pd.Timestamp,
) -> go.Figure | None:
    figure = go.Figure()
    color_index = 0
    for row in level_set.rows:
        points = _progression_points(timeline, row.requirement_id)
        if points.empty:
            continue
        color = _PROGRESSION_COLORS[color_index % len(_PROGRESSION_COLORS)]
        color_index += 1
        figure.add_trace(
            go.Scatter(
                x=points["date"],
                y=points["percent"],
                mode="lines+markers",
                name=row.label,
                line=dict(color=color, width=2),
                marker=dict(color=color, size=7),
                customdata=[[row.label] for _ in range(len(points))],
                hovertemplate="%{customdata[0]}<br>%{x|%Y-%m-%d}<br>%{y:.0f}%%<extra></extra>",
            )
        )
    if not figure.data:
        return None
    figure.add_hline(
        y=100,
        line_dash="dot",
        line_color="#9E9E9E",
        line_width=1,
    )
    xaxis: dict = dict(
        type="date",
        title=None,
        showgrid=False,
        fixedrange=True,
        range=_progression_window(start, timeline),
    )
    figure.update_layout(
        height=320,
        margin=dict(l=8, r=12, t=36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="closest",
        xaxis=xaxis,
        yaxis=dict(
            range=[0, 100],
            autorange=False,
            title="Percent of goal",
            showgrid=True,
            gridcolor="rgba(128,128,128,0.25)",
            zeroline=False,
            fixedrange=True,
        ),
    )
    return figure


def _progression_points(timeline: pd.DataFrame, requirement_id: str) -> pd.DataFrame:
    if "requirement_id" not in timeline.columns:
        return pd.DataFrame(columns=["date", "percent"])
    selected = timeline["requirement_id"].astype(str) == str(requirement_id)
    points = timeline.loc[selected, ["date", "percent"]].copy()
    points["date"] = pd.to_datetime(points["date"], errors="coerce")
    points["percent"] = pd.to_numeric(points["percent"], errors="coerce")
    points = points.dropna(subset=["date", "percent"])
    return points.sort_values("date", kind="mergesort").reset_index(drop=True)


def _progression_window(start: pd.Timestamp, timeline: pd.DataFrame) -> list[pd.Timestamp]:
    start = pd.Timestamp(start)
    end_dates = [start]
    if "date" in timeline.columns:
        parsed = pd.to_datetime(timeline["date"], errors="coerce").dropna()
        if not parsed.empty:
            end_dates.append(pd.Timestamp(parsed.max()))
    end = max(end_dates)
    if start >= end:
        start = start - pd.Timedelta(days=1)
        end = end + pd.Timedelta(days=1)
    else:
        pad = max(pd.Timedelta(days=1), (end - start) * 0.05)
        start = start - pad
        end = end + pad
    return [start, end]


def _render_locked_section(locked: list[LevelSet]) -> None:
    first, *rest = locked
    st.markdown(f"#### Level {first.target_level}")
    _render_locked_checklist(first)
    for level_set in rest:
        with st.expander(f"Level {level_set.target_level}", expanded=False):
            _render_locked_checklist(level_set)


def _render_locked_checklist(level_set: LevelSet) -> None:
    st.caption(f"Unlocks at level {level_set.unlock_level}")
    for row in level_set.rows:
        st.write(_locked_requirement_line(row))


def _locked_requirement_line(row: RequirementRow) -> str:
    goal = f"{int(row.goal):,}"
    if is_platinum_requirement(row.requirement_id) and row.value is not None:
        return f"{row.label} \u2014 {int(row.value):,} / {goal}"
    return f"{row.label} \u2014 {goal}"


def _render_active_summary(level_set: LevelSet) -> None:
    finish_day = _format_day(level_set.finish_date)
    if finish_day is not None:
        st.write(
            f"Level {level_set.target_level} on {finish_day} "
            f"({level_set.finish_days} days), set by {level_set.binding_label}."
        )
        return
    st.write(level_set.finish_note)


def _render_active_row(row: RequirementRow) -> None:
    label_col, bar_col, detail_col = st.columns([2.0, 1.3, 4.8], gap="small")
    label_col.write(row.label)
    percent = f"{_progress_percent(row):.0f}%"
    if row.done:
        bar_col.progress(1.0, text=percent)
        detail_col.write("Done")
        return
    bar_col.progress(_progress_fraction(row), text=percent)
    detail_col.write(_active_detail(row))


def _active_detail(row: RequirementRow) -> str:
    value = int(row.value) if row.value is not None else 0
    remaining = int(row.remaining) if row.remaining is not None else 0
    parts = [f"{value:,} / {int(row.goal):,}", f"Remaining {remaining:,}"]
    if row.pace_per_day is not None and not pd.isna(row.pace_per_day):
        parts.append(f"{float(row.pace_per_day):,.0f} / day")
    eta_day = _format_day(row.eta)
    if eta_day is not None:
        parts.append(eta_day)
    elif row.note:
        parts.append(row.note)
    return " · ".join(parts)


def _progress_fraction(row: RequirementRow) -> float:
    if row.goal <= 0 or row.value is None:
        return 0.0
    return min(1.0, max(0.0, float(row.value) / float(row.goal)))


def _progress_percent(row: RequirementRow) -> float:
    if row.done:
        return 100.0
    return 100.0 * _progress_fraction(row)


_TRACK_OPEN = "#4C78A8"
_TRACK_BINDING = "#F58518"
_TRACK_DONE = "#54A24B"
_TRACK_WAITING = "#9E9E9E"


def _has_eta(row: RequirementRow) -> bool:
    return row.eta is not None and not pd.isna(row.eta)


def _short_day(value: pd.Timestamp) -> str:
    day = pd.Timestamp(value)
    return f"{day.strftime('%b')} {int(day.day)}"


def _tracker_hover(row: RequirementRow, today: pd.Timestamp) -> str:
    value = 0 if row.value is None else int(row.value)
    amounts = f"{value:,} / {int(row.goal):,}"
    if row.done:
        return f"Done<br>{amounts}"
    if not _has_eta(row):
        return f"{row.note or 'No date'}<br>{amounts}"
    eta = pd.Timestamp(row.eta)
    days = int(round((eta.normalize() - today).total_seconds() / 86400.0))
    pace = ""
    if row.pace_per_day is not None and not pd.isna(row.pace_per_day):
        pace = f"<br>{float(row.pace_per_day):,.0f} / day"
    return f"{_format_day(eta)} · {days} days{pace}<br>{amounts}"


def _days_after(today: pd.Timestamp, when: pd.Timestamp) -> float:
    return (pd.Timestamp(when) - today).total_seconds() / 86400.0


def _finish_tracker(level_set: LevelSet, as_of: pd.Timestamp) -> go.Figure:
    today = pd.Timestamp(as_of).normalize()
    labels = [row.label for row in level_set.rows]
    widths: list[float] = []
    texts: list[str] = []
    colors: list[str] = []
    hovers: list[str] = []
    for row in level_set.rows:
        if row.done:
            width, text, color = 0.0, "Done", _TRACK_DONE
        elif not _has_eta(row):
            width, text, color = 0.0, "No date", _TRACK_WAITING
        else:
            eta = pd.Timestamp(row.eta)
            binding = row.label == level_set.binding_label
            color = _TRACK_BINDING if binding else _TRACK_OPEN
            days = _days_after(today, eta)
            width = max(0.0, days)
            text = _short_day(eta)
        widths.append(width)
        texts.append(text)
        colors.append(color)
        hovers.append(_tracker_hover(row, today))

    latest_day = max(widths) if widths else 0.0
    finish_day = None
    finish = level_set.finish_date
    if finish is not None and not pd.isna(finish):
        finish_day = _days_after(today, pd.Timestamp(finish))
        latest_day = max(latest_day, finish_day)
    pad = max(12.0, latest_day * 0.18)
    tick_days, tick_labels = _tracker_ticks(today, latest_day)

    figure = go.Figure(
        data=[
            go.Bar(
                orientation="h",
                y=labels,
                x=widths,
                text=texts,
                textposition="outside",
                textfont=dict(color=colors, size=12),
                cliponaxis=False,
                marker=dict(color=colors),
                customdata=hovers,
                hovertemplate="%{y}<br>%{customdata}<extra></extra>",
                showlegend=False,
            )
        ]
    )
    figure.update_layout(
        height=56 + 36 * max(1, len(labels)),
        margin=dict(l=4, r=12, t=28, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.28,
        xaxis=dict(
            range=[-1, latest_day + pad],
            tickmode="array",
            tickvals=tick_days,
            ticktext=tick_labels,
            showgrid=True,
            gridcolor="rgba(128,128,128,0.25)",
            fixedrange=True,
            title=None,
            zeroline=False,
        ),
        yaxis=dict(autorange="reversed", automargin=True, title=None, fixedrange=True),
    )
    if finish_day is not None:
        figure.add_vline(
            x=float(finish_day),
            line_dash="dot",
            line_color=_TRACK_BINDING,
            line_width=1,
            annotation_text="Level date",
            annotation_position="top",
            annotation_font_size=11,
            annotation_font_color=_TRACK_BINDING,
        )
    return figure


def _tracker_ticks(today: pd.Timestamp, latest_day: float) -> tuple[list[float], list[str]]:
    step = 14
    ticks: list[float] = []
    labels: list[str] = []
    day = 0
    last = int(max(0, round(latest_day)))
    while day <= last:
        tick_day = today + pd.Timedelta(days=day)
        ticks.append(float(day))
        labels.append(_short_day(tick_day))
        day += step
    if not ticks:
        ticks = [0.0]
        labels = [_short_day(today)]
    return ticks, labels


def _format_day(value: pd.Timestamp | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _render_log_form(level_set: LevelSet, *, account: str, progress_path: Path) -> None:
    task_rows = [
        row
        for row in level_set.rows
        if row.requirement_id != XP_REQUIREMENT_ID and not is_platinum_requirement(row.requirement_id)
    ]
    if not task_rows:
        return
    with st.form(f"level_requirements_log_{level_set.target_level}"):
        logged_on = st.date_input(
            "Date",
            value=date.today(),
            key=f"level_requirements_log_date_{level_set.target_level}",
        )
        entered: dict[str, int] = {}
        for row in task_rows:
            entered[row.requirement_id] = int(
                st.number_input(
                    row.label,
                    min_value=0,
                    step=1,
                    value=int(row.value or 0),
                    key=f"level_requirements_log_{account}_{level_set.target_level}_{row.requirement_id}",
                )
            )
        submitted = st.form_submit_button("Save progress")

    if not submitted:
        return

    rows = [
        {
            "date": logged_on,
            "account": account,
            "requirement_id": requirement_id,
            "value": int(value),
        }
        for requirement_id, value in entered.items()
    ]
    try:
        upsert_level_requirement_progress(progress_path, rows)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.success("Saved level progress.")
    st.rerun()
