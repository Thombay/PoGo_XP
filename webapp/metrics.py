from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd

WINDOW_DAYS_DEFAULT = 30
BASELINE_MIN_WINDOWS_DEFAULT = 5


@dataclass(frozen=True)
class XPAtResult:
    value: float | None
    method: str | None


def metric_suffix(window_days: int) -> str:
    return f"{int(window_days)}d"


def metric_col(base: str, window_days: int) -> str:
    return f"{base}_{metric_suffix(window_days)}"


def _window_col_map(window_days: int) -> dict[str, str]:
    return {
        "window_start": metric_col("window_start", window_days),
        "window_end": metric_col("window_end", window_days),
        "xp_start": metric_col("xp_start", window_days),
        "xp_end": metric_col("xp_end", window_days),
        "xp_gain": metric_col("xp_gain", window_days),
        "xp_per_day": metric_col("xp_per_day", window_days),
        "eligible": metric_col("eligible", window_days),
        "baseline_window_count": metric_col("baseline_window_count", window_days),
        "eligible_baseline": metric_col("eligible_baseline", window_days),
        "baseline_xp_per_day": metric_col("baseline_xp_per_day", window_days),
        "delta_vs_baseline": metric_col("delta_vs_baseline", window_days),
        "pct_vs_baseline": metric_col("pct_vs_baseline", window_days),
    }


def _prep_xp_df(xp_df: pd.DataFrame) -> pd.DataFrame:
    if xp_df.empty:
        return pd.DataFrame(columns=["Date", "Spieler", "Total XP"])
    d = xp_df.copy()
    if not {"Date", "Spieler", "Total XP"}.issubset(d.columns):
        return pd.DataFrame(columns=["Date", "Spieler", "Total XP"])
    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")
    d["Spieler"] = d["Spieler"].astype(str).str.strip()
    d["Total XP"] = pd.to_numeric(d["Total XP"], errors="coerce")
    d = d.dropna(subset=["Date", "Spieler", "Total XP"]).copy()
    d = d.sort_values(["Spieler", "Date"]).reset_index(drop=True)
    return d[["Date", "Spieler", "Total XP"]]


def xp_at(player_df: pd.DataFrame, target_date: pd.Timestamp) -> XPAtResult:
    if player_df.empty:
        return XPAtResult(value=None, method=None)

    d = player_df.sort_values("Date").copy()
    t = pd.to_datetime(target_date)

    exact = d[d["Date"] == t]
    if not exact.empty:
        return XPAtResult(value=float(exact.iloc[-1]["Total XP"]), method="exact")

    prev_rows = d[d["Date"] <= t]
    next_rows = d[d["Date"] >= t]
    if prev_rows.empty:
        return XPAtResult(value=None, method=None)

    prev_row = prev_rows.iloc[-1]
    prev_date = pd.to_datetime(prev_row["Date"])
    prev_xp = float(prev_row["Total XP"])

    if next_rows.empty:
        return XPAtResult(value=prev_xp, method="step")

    next_row = next_rows.iloc[0]
    next_date = pd.to_datetime(next_row["Date"])
    next_xp = float(next_row["Total XP"])

    if next_date == prev_date:
        return XPAtResult(value=prev_xp, method="step")
    if prev_date < t < next_date:
        span = (next_date - prev_date).total_seconds()
        if span <= 0:
            return XPAtResult(value=prev_xp, method="step")
        frac = (t - prev_date).total_seconds() / span
        return XPAtResult(value=prev_xp + frac * (next_xp - prev_xp), method="interpolated")
    return XPAtResult(value=prev_xp, method="step")


def compute_player_windows(
    player_df: pd.DataFrame,
    window_days: int = WINDOW_DAYS_DEFAULT,
) -> pd.DataFrame:
    c = _window_col_map(window_days)
    cols = [
        "Spieler",
        c["window_start"],
        c["window_end"],
        c["xp_start"],
        c["xp_end"],
        c["xp_gain"],
        c["xp_per_day"],
        "start_method",
        "end_method",
        "window_days",
        c["eligible"],
    ]
    if player_df.empty:
        return pd.DataFrame(columns=cols)

    d = player_df.sort_values("Date").copy()
    player = str(d["Spieler"].iloc[0])
    end_dates = sorted(pd.to_datetime(d["Date"]).dropna().unique().tolist())
    rows: list[dict[str, object]] = []
    for end_date in end_dates:
        end_ts = pd.to_datetime(end_date)
        start_ts = end_ts - pd.Timedelta(days=window_days)
        start_res = xp_at(d, start_ts)
        end_res = xp_at(d, end_ts)
        has_before_start = bool((d["Date"] <= start_ts).any())
        has_on_after_end = bool((d["Date"] >= end_ts).any())
        eligible = bool(has_before_start and has_on_after_end)
        if not eligible or start_res.value is None or end_res.value is None:
            continue
        gain = float(end_res.value - start_res.value)
        pace = gain / float(window_days)
        rows.append(
            {
                "Spieler": player,
                c["window_start"]: start_ts,
                c["window_end"]: end_ts,
                c["xp_start"]: float(start_res.value),
                c["xp_end"]: float(end_res.value),
                c["xp_gain"]: gain,
                c["xp_per_day"]: pace,
                "start_method": start_res.method,
                "end_method": end_res.method,
                "window_days": int(window_days),
                c["eligible"]: True,
            }
        )
    return pd.DataFrame(rows, columns=cols)


def compute_player_kpis_window(
    xp_df: pd.DataFrame,
    window_days: int = WINDOW_DAYS_DEFAULT,
    baseline_min_windows: int = BASELINE_MIN_WINDOWS_DEFAULT,
) -> pd.DataFrame:
    c = _window_col_map(window_days)
    cols = [
        "Spieler",
        "last_snapshot_date",
        c["window_start"],
        c["window_end"],
        c["xp_start"],
        c["xp_end"],
        c["xp_gain"],
        c["xp_per_day"],
        "start_method",
        "end_method",
        c["eligible"],
        c["baseline_window_count"],
        c["eligible_baseline"],
        c["baseline_xp_per_day"],
        c["delta_vs_baseline"],
        c["pct_vs_baseline"],
    ]
    d = _prep_xp_df(xp_df)
    if d.empty:
        return pd.DataFrame(columns=cols)

    rows: list[dict[str, object]] = []
    for player, grp in d.groupby("Spieler", sort=True):
        g = grp.sort_values("Date").copy()
        last_snapshot = pd.to_datetime(g["Date"].max(), errors="coerce")

        windows = compute_player_windows(g, window_days=window_days)
        if windows.empty:
            rows.append(
                {
                    "Spieler": str(player),
                    "last_snapshot_date": last_snapshot,
                    c["window_start"]: pd.NaT,
                    c["window_end"]: pd.NaT,
                    c["xp_start"]: pd.NA,
                    c["xp_end"]: pd.NA,
                    c["xp_gain"]: pd.NA,
                    c["xp_per_day"]: pd.NA,
                    "start_method": pd.NA,
                    "end_method": pd.NA,
                    c["eligible"]: False,
                    c["baseline_window_count"]: 0,
                    c["eligible_baseline"]: False,
                    c["baseline_xp_per_day"]: pd.NA,
                    c["delta_vs_baseline"]: pd.NA,
                    c["pct_vs_baseline"]: pd.NA,
                }
            )
            continue

        windows = windows.sort_values(c["window_end"]).reset_index(drop=True)
        current = windows.iloc[-1]
        baseline_windows = windows.iloc[:-1].copy()
        baseline_count = int(len(baseline_windows))
        baseline_pace = (
            float(pd.to_numeric(baseline_windows[c["xp_per_day"]], errors="coerce").median())
            if baseline_count > 0
            else pd.NA
        )
        eligible_baseline = bool(
            bool(current.get(c["eligible"], False))
            and baseline_count >= int(baseline_min_windows)
            and pd.notna(baseline_pace)
        )

        delta_vs_baseline = (
            float(current[c["xp_per_day"]]) - float(baseline_pace)
            if eligible_baseline
            else pd.NA
        )
        if eligible_baseline and float(baseline_pace) != 0.0:
            pct_vs_baseline = float(delta_vs_baseline) / float(baseline_pace)
        else:
            pct_vs_baseline = pd.NA

        rows.append(
            {
                "Spieler": str(player),
                "last_snapshot_date": last_snapshot,
                c["window_start"]: pd.to_datetime(current[c["window_start"]], errors="coerce"),
                c["window_end"]: pd.to_datetime(current[c["window_end"]], errors="coerce"),
                c["xp_start"]: float(current[c["xp_start"]]),
                c["xp_end"]: float(current[c["xp_end"]]),
                c["xp_gain"]: float(current[c["xp_gain"]]),
                c["xp_per_day"]: float(current[c["xp_per_day"]]),
                "start_method": current.get("start_method"),
                "end_method": current.get("end_method"),
                c["eligible"]: bool(current.get(c["eligible"], False)),
                c["baseline_window_count"]: baseline_count,
                c["eligible_baseline"]: eligible_baseline,
                c["baseline_xp_per_day"]: float(baseline_pace) if pd.notna(baseline_pace) else pd.NA,
                c["delta_vs_baseline"]: float(delta_vs_baseline) if pd.notna(delta_vs_baseline) else pd.NA,
                c["pct_vs_baseline"]: float(pct_vs_baseline) if pd.notna(pct_vs_baseline) else pd.NA,
            }
        )

    out = pd.DataFrame(rows, columns=cols)
    out = out.sort_values("Spieler").reset_index(drop=True)
    return out


def _rename_window_suffix(df: pd.DataFrame, from_suffix: str, to_suffix: str) -> pd.DataFrame:
    if from_suffix == to_suffix or df.empty:
        return df
    rename_map: dict[str, str] = {}
    needle = f"_{from_suffix}"
    repl = f"_{to_suffix}"
    for col in df.columns:
        if col.endswith(needle):
            rename_map[col] = f"{col[:-len(needle)]}{repl}"
    if not rename_map:
        return df
    return df.rename(columns=rename_map)


def compute_player_kpis_30d(
    xp_df: pd.DataFrame,
    window_days: int = WINDOW_DAYS_DEFAULT,
    baseline_min_windows: int = BASELINE_MIN_WINDOWS_DEFAULT,
) -> pd.DataFrame:
    out = compute_player_kpis_window(
        xp_df=xp_df,
        window_days=window_days,
        baseline_min_windows=baseline_min_windows,
    )
    from_suffix = metric_suffix(window_days)
    return _rename_window_suffix(out, from_suffix=from_suffix, to_suffix="30d")


def _infer_suffix_from_metrics(metrics_df: pd.DataFrame) -> str | None:
    candidates: list[str] = []
    pattern = re.compile(r"^xp_gain_(\d+d)$")
    for col in metrics_df.columns:
        m = pattern.match(str(col))
        if m:
            candidates.append(m.group(1))
    if not candidates:
        return None
    unique = sorted(set(candidates), key=lambda x: int(str(x).rstrip("d")))
    return unique[0]


def recent_gain_table_from_metrics(metrics_df: pd.DataFrame, window_days: int = WINDOW_DAYS_DEFAULT) -> pd.DataFrame:
    cols = ["Spieler", "from_date", "to_date", "xp_gain", "xp_per_day"]
    if metrics_df.empty:
        return pd.DataFrame(columns=cols)
    d = metrics_df.copy()
    suffix = metric_suffix(window_days)
    gain_col = f"xp_gain_{suffix}"
    pace_col = f"xp_per_day_{suffix}"
    start_col = f"window_start_{suffix}"
    end_col = f"window_end_{suffix}"
    eligible_col = f"eligible_{suffix}"

    if gain_col not in d.columns:
        inferred = _infer_suffix_from_metrics(d)
        if inferred is None:
            return pd.DataFrame(columns=cols)
        gain_col = f"xp_gain_{inferred}"
        pace_col = f"xp_per_day_{inferred}"
        start_col = f"window_start_{inferred}"
        end_col = f"window_end_{inferred}"
        eligible_col = f"eligible_{inferred}"

    if eligible_col in d.columns:
        d = d[d[eligible_col] == True].copy()  # noqa: E712
    if d.empty:
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame(
        {
            "Spieler": d["Spieler"],
            "from_date": pd.to_datetime(d[start_col], errors="coerce"),
            "to_date": pd.to_datetime(d[end_col], errors="coerce"),
            "xp_gain": pd.to_numeric(d[gain_col], errors="coerce"),
            "xp_per_day": pd.to_numeric(d[pace_col], errors="coerce"),
        }
    )
    out = out.dropna(subset=["Spieler", "from_date", "to_date", "xp_gain", "xp_per_day"]).copy()
    out = out.sort_values("xp_gain", ascending=False).reset_index(drop=True)
    return out[cols]
