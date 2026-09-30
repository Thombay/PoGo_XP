from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from webapp.level_requirements import (
    XP_REQUIREMENT_ID,
    LevelSet,
    RequirementRow,
    build_level_sets,
    upsert_level_requirement_progress,
)


def render_level_requirements_page(
    *,
    xp_df: pd.DataFrame,
    curve_totals: dict[int, int],
    requirements_df: pd.DataFrame,
    progress_df: pd.DataFrame,
    progress_path: Path,
) -> None:
    st.subheader("Level Requirements")
    accounts = _account_names(xp_df)
    if not accounts:
        st.info("No XP history yet.")
        return

    default_index = accounts.index("Thombay") if "Thombay" in accounts else 0
    account = st.selectbox(
        "Account",
        options=accounts,
        index=default_index,
        key="level_requirements_account",
    )
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
        account=str(account),
        window_days=int(window_days),
        as_of=as_of,
    )
    if not sets:
        st.info("No XP history for this account.")
        return

    for index, level_set in enumerate(sets):
        if index:
            st.divider()
        _render_level_set(
            level_set,
            account=str(account),
            progress_path=progress_path,
            as_of=as_of,
        )


def _account_names(xp_df: pd.DataFrame) -> list[str]:
    if xp_df.empty or "Spieler" not in xp_df.columns:
        return []
    names = xp_df["Spieler"].dropna().astype(str).str.strip()
    return sorted({name for name in names.tolist() if name})


def _render_level_set(
    level_set: LevelSet,
    *,
    account: str,
    progress_path: Path,
    as_of: pd.Timestamp,
) -> None:
    st.markdown(f"#### Level {level_set.target_level}")
    if level_set.status == "reached":
        st.caption("Complete")
        for row in level_set.rows:
            st.write(f"{row.label} — Done")
        return

    if level_set.status == "locked":
        st.caption(f"Unlocks at level {level_set.unlock_level}")
        for row in level_set.rows:
            st.write(f"{row.label} — {int(row.goal):,}")
        return

    if level_set.status != "active":
        return

    _render_active_summary(level_set)
    st.plotly_chart(
        _finish_tracker(level_set, as_of),
        use_container_width=True,
        config={"displayModeBar": False},
    )
    for row in level_set.rows:
        _render_active_row(row)
    _render_log_form(level_set, account=account, progress_path=progress_path)


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
    task_rows = [row for row in level_set.rows if row.requirement_id != XP_REQUIREMENT_ID]
    with st.form("level_requirements_log"):
        logged_on = st.date_input(
            "Date",
            value=date.today(),
            key="level_requirements_log_date",
        )
        entered: dict[str, int] = {}
        for row in task_rows:
            entered[row.requirement_id] = int(
                st.number_input(
                    row.label,
                    min_value=0,
                    step=1,
                    value=int(row.value or 0),
                    key=f"level_requirements_log_{account}_{row.requirement_id}",
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
