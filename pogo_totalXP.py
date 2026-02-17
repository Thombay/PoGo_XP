import argparse
import difflib
import os
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

CURVE_FILE = "pogo_totalXP.csv"
HISTORY_FILE = "pogo_totalXP_history.csv"
GROUPS_FILE = "pogo_player_groups.csv"


def to_int_series(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
        .str.strip()
        .str.replace(" ", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace({"nan": np.nan, "None": np.nan, "": np.nan})
        .astype("float")
        .astype("Int64")
    )


def normalize_date(date_str: str) -> str:
    return pd.to_datetime(date_str, errors="raise").date().isoformat()


def sanitize_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
    return cleaned.strip("_") or "Group"


def build_output_name(order: str | int, date_str: str, group_name: str, stem: str) -> str:
    return f"{normalize_date(date_str)}_{order}_{sanitize_name(group_name)}_{stem}.png"


def group_output_dir(group_name: str) -> str:
    return sanitize_name(group_name)


def xp_axis_fmt(x: float, _pos: float) -> str:
    ax = abs(x)
    if ax >= 1_000_000:
        return f"{x/1_000_000:.1f}M"
    if ax >= 1_000:
        return f"{x/1_000:.0f}k"
    return f"{x:.0f}"


def xp_axis_fmt_log_progress(x: float, _pos: float) -> str:
    if x <= 1:
        return "0"
    return xp_axis_fmt(x, _pos)


def place_growth_labels(ax, points: list[dict], close_dist_px: float = 28.0, min_sep_px: float = 14.0):
    if not points:
        return

    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    # Convert point coordinates to display pixels for distance checks.
    disp = []
    for p in points:
        xd, yd = ax.transData.transform((p["x"], p["y"]))
        disp.append((xd, yd))

    # Build connected clusters of close points.
    n = len(points)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        xi, yi = disp[i]
        for j in range(i + 1, n):
            xj, yj = disp[j]
            d = ((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5
            if d <= close_dist_px:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    colliding = set()
    for idxs in clusters.values():
        if len(idxs) >= 2:
            colliding.update(idxs)

    # Default style for non-colliding labels (upper-left, 45deg clockwise).
    for i, p in enumerate(points):
        if i in colliding:
            continue
        ax.annotate(
            p["text"],
            xy=(p["x"], p["y"]),
            xytext=(-6, 6),
            textcoords="offset points",
            rotation=-45,
            rotation_mode="anchor",
            ha="right",
            va="bottom",
            fontsize=8,
            alpha=0.9,
        )

    # Stacked right-side labels for colliding clusters, with connector lines.
    inv = ax.transData.inverted()
    ax_bbox = ax.get_window_extent(renderer=renderer)

    for idxs in clusters.values():
        if len(idxs) < 2:
            continue
        idxs = sorted(idxs, key=lambda i: disp[i][1])
        rail_x_data = max(points[i]["x"] for i in idxs) + 1.0
        rail_x_disp = ax.transData.transform((rail_x_data, 0))[0]

        y_targets = []
        for i in idxs:
            y_targets.append(disp[i][1])
        y_targets.sort()

        placed = []
        for yd in y_targets:
            y_new = yd if not placed else max(yd, placed[-1] + min_sep_px)
            placed.append(y_new)
        if placed:
            overflow = placed[-1] - (ax_bbox.y1 - 10)
            if overflow > 0:
                placed = [y - overflow for y in placed]

        # Map back by index order (already y-sorted).
        for i, ylab_disp in zip(idxs, placed):
            _, ylab_data = inv.transform((rail_x_disp, ylab_disp))
            p = points[i]
            ax.annotate(
                p["text"],
                xy=(p["x"], p["y"]),
                xytext=(rail_x_data, ylab_data),
                textcoords="data",
                ha="left",
                va="center",
                fontsize=8,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.85),
                arrowprops=dict(arrowstyle="-", linewidth=0.8, alpha=0.7),
                clip_on=False,
                zorder=10,
            )


def read_curve(path: str) -> pd.DataFrame:
    curve = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    curve = curve.rename(columns={"XP to next Lvl.": "XP"})
    needed = {"Level", "XP", "Total XP"}
    if not needed.issubset(set(curve.columns)):
        raise ValueError(f"{path} must contain columns: Level, XP, Total XP")

    curve["Level"] = to_int_series(curve["Level"])
    curve["XP"] = to_int_series(curve["XP"])
    curve["Total XP"] = to_int_series(curve["Total XP"])
    curve = curve.dropna(subset=["Level", "XP", "Total XP"]).sort_values("Level")
    curve["Level"] = curve["Level"].astype(int)
    curve["XP"] = curve["XP"].astype(int)
    curve["Total XP"] = curve["Total XP"].astype(int)
    return curve


def load_history(path: str, total_xp_by_level: dict[int, int]) -> pd.DataFrame:
    if not pd.io.common.file_exists(path):
        return pd.DataFrame(columns=["Date", "Spieler", "Lvl", "XP Bar", "Total XP"])

    hist = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    needed = {"Date", "Spieler", "Lvl", "XP Bar"}
    if not needed.issubset(hist.columns):
        raise ValueError(f"{path} must contain columns: Date, Spieler, Lvl, XP Bar")

    hist = hist.copy()
    hist["Date"] = hist["Date"].astype(str).map(normalize_date)
    hist["Lvl"] = to_int_series(hist["Lvl"])
    hist["XP Bar"] = to_int_series(hist["XP Bar"])
    hist = hist.dropna(subset=["Date", "Spieler", "Lvl", "XP Bar"]).copy()
    hist["Lvl"] = hist["Lvl"].astype(int)
    hist["XP Bar"] = hist["XP Bar"].astype(int)

    def calc_total(row: pd.Series) -> int:
        lvl = row["Lvl"]
        if lvl not in total_xp_by_level:
            raise ValueError(f"Level {lvl} from history file not found in curve file.")
        return int(total_xp_by_level[lvl] + row["XP Bar"])

    hist["Total XP"] = hist.apply(calc_total, axis=1)
    hist = hist.sort_values(["Date", "Spieler"]).reset_index(drop=True)
    return hist


def parse_groups(path: str) -> dict[str, list[str]]:
    if not pd.io.common.file_exists(path):
        raise ValueError(
            f"{path} not found. Create it like:\nFamily:\nBabsi,Thombay\n\nWork:\nPlayer1,Player2"
        )

    groups: dict[str, list[str]] = {}
    current_group: str | None = None

    with open(path, "r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith(":"):
                current_group = line[:-1].strip()
                groups.setdefault(current_group, [])
                continue
            if current_group is None:
                continue
            names = [n.strip() for n in line.split(",")]
            for name in names:
                if not name or name == "...":
                    continue
                groups[current_group].append(name)

    for group, names in groups.items():
        groups[group] = list(dict.fromkeys(names))

    groups = {k: v for k, v in groups.items() if v}
    if not groups:
        raise ValueError(f"{path} contains no valid groups.")
    return groups


def latest_players(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return history.copy()
    hist = history.copy()
    hist["Date"] = pd.to_datetime(hist["Date"])
    latest = hist.sort_values(["Spieler", "Date"]).groupby("Spieler", as_index=False).tail(1)
    latest["Date"] = latest["Date"].dt.date.astype(str)
    return latest[["Date", "Spieler", "Lvl", "XP Bar", "Total XP"]].reset_index(drop=True)


def add_interval_columns(history: pd.DataFrame) -> pd.DataFrame:
    hist = history.copy()
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist = hist.sort_values(["Spieler", "Date"])
    hist["Days Delta"] = hist.groupby("Spieler")["Date"].diff().dt.total_seconds() / 86_400
    hist["XP Delta"] = hist.groupby("Spieler")["Total XP"].diff()
    hist["XP/day"] = np.where(hist["Days Delta"] > 0, hist["XP Delta"] / hist["Days Delta"], np.nan)
    return hist


def warn_large_intervals(hist_with_intervals: pd.DataFrame, group_name: str, threshold_days: float = 10.0):
    large = hist_with_intervals[hist_with_intervals["Days Delta"] > threshold_days].copy()
    if large.empty:
        return
    for _, row in large.sort_values(["Spieler", "Date"]).iterrows():
        d = float(row["Days Delta"])
        print(
            f"Warning [{group_name}]: large interval for {row['Spieler']} on {row['Date'].date()} "
            f"(delta_days={d:.1f})"
        )


def normalize_player_key(name: str) -> str:
    # Allow common leetspeak variants and trailing season/year suffixes.
    trans = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t"})
    s = str(name).strip().lower().translate(trans)
    s = re.sub(r"[^a-z0-9]+", "", s)
    s = re.sub(r"\d+$", "", s)
    return s


def resolve_group_players(players_in_group: list[str], history_names: set[str], group_name: str) -> list[str]:
    key_to_hist: dict[str, set[str]] = {}
    for hn in history_names:
        key = normalize_player_key(hn)
        key_to_hist.setdefault(key, set()).add(hn)

    resolved: list[str] = []
    for p in players_in_group:
        if p in history_names:
            resolved.append(p)
            continue

        key = normalize_player_key(p)
        candidates = sorted(key_to_hist.get(key, set()))
        if candidates:
            resolved.extend(candidates)
            print(f"Info [{group_name}]: mapped '{p}' to history name(s): {', '.join(candidates)}")
            continue

        close = difflib.get_close_matches(p, sorted(history_names), n=3, cutoff=0.6)
        if close:
            print(f"Warning [{group_name}]: no exact history rows for '{p}'. Close matches: {', '.join(close)}")
        else:
            print(f"Warning [{group_name}]: no history rows found for '{p}'")

    # Deduplicate while keeping order.
    out: list[str] = []
    seen: set[str] = set()
    for p in resolved:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def build_player_colors(players: list[str]) -> dict[str, tuple[float, float, float, float]]:
    unique = sorted(set(players))
    cmap = plt.get_cmap("tab20", max(1, len(unique)))
    return {p: cmap(i) for i, p in enumerate(unique)}


def place_end_labels(
    ax,
    end_points: list[dict[str, float | str]],
    x_offset_points: int = 5,
    y_min_sep_data: float = 0.2,
):
    if not end_points:
        return
    ordered = sorted(end_points, key=lambda p: float(p["y"]))
    placed: list[float] = []
    for p in ordered:
        y = float(p["y"])
        if placed and y - placed[-1] < y_min_sep_data:
            y = placed[-1] + y_min_sep_data
        placed.append(y)
        ax.annotate(
            str(p["text"]),
            xy=(p["x"], p["y"]),
            xytext=(x_offset_points, 0),
            textcoords="offset points",
            fontsize=8,
            alpha=0.9,
            va="center",
        )


def plot_curve_with_players(
    curve: pd.DataFrame,
    players: pd.DataFrame,
    group_name: str,
    output_png: str,
    player_colors: dict[str, tuple[float, float, float, float]],
    y_scale: str = "linear",
    title_suffix: str = "",
):
    fig, ax = plt.subplots(figsize=(14, 6.5))
    xp_to_next_by_level = dict(zip(curve["Level"], curve["XP"]))
    ax.plot(curve["Level"], curve["Total XP"], linewidth=2, label="Total XP (curve)")

    ax2 = ax.twinx()
    ax2.bar(curve["Level"], curve["XP"], alpha=0.15, width=0.9, label="XP per level")
    ax2.set_ylabel("XP per level")
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{x/1_000_000:.0f}"))

    players_plot = players.copy().reset_index(drop=True)
    players_plot["x_plot"] = players_plot["Lvl"].astype(float)
    players_plot["y_plot"] = players_plot["Total XP"].astype(float)

    # If points are close, spread them slightly in X so each marker stays visible.
    n = len(players_plot)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        xi = float(players_plot.loc[i, "Lvl"])
        yi = float(players_plot.loc[i, "Total XP"])
        for j in range(i + 1, n):
            xj = float(players_plot.loc[j, "Lvl"])
            yj = float(players_plot.loc[j, "Total XP"])
            # Nearby in both level and total XP => treat as overlapping cluster.
            if abs(xi - xj) <= 1.0 and abs(yi - yj) <= 2_500_000:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    for idxs in clusters.values():
        if len(idxs) < 2:
            continue
        idxs = sorted(idxs, key=lambda k: float(players_plot.loc[k, "Total XP"]))
        offsets = np.linspace(-0.28, 0.28, len(idxs))
        for k, off in zip(idxs, offsets):
            players_plot.loc[k, "x_plot"] = float(players_plot.loc[k, "Lvl"]) + float(off)

    for i, r in players_plot.iterrows():
        player = str(r["Spieler"])
        ax.scatter(
            [r["x_plot"]],
            [r["y_plot"]],
            color=player_colors.get(player, "C0"),
            s=74,
            edgecolors="white",
            linewidths=1.4,
            zorder=7,
            label="Players" if i == 0 else "_nolegend_",
        )

    label_points = []
    for _, r in players_plot.iterrows():
        lvl = int(r["Lvl"])
        xp_needed = int(xp_to_next_by_level.get(lvl, 0))
        xp_bar = int(r["XP Bar"])
        if xp_needed <= 0:
            pct = 100
        else:
            pct = int(round((xp_bar / xp_needed) * 100))
            pct = max(0, min(100, pct))
        label_points.append(
            {"x": float(r["x_plot"]), "y": int(r["Total XP"]), "text": f'{r["Spieler"]}({pct}%)'}
        )

    ax.set_title(f"{group_name}: Pogo XP Growth{title_suffix}")
    ax.set_xlabel("Level")
    ax.set_ylabel("Total XP")
    ax.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt))
    # Keep x-range tight around actual levels and avoid large empty margins.
    min_level = int(curve["Level"].min())
    max_level = int(curve["Level"].max())
    ax.set_xlim(min_level - 1, max_level + 0.6)
    if y_scale == "log":
        ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    place_growth_labels(ax, label_points)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left")

    fig.subplots_adjust(left=0.08, right=0.96, top=0.92, bottom=0.11)
    plt.savefig(output_png, dpi=200)
    print(f"Saved: {output_png}")
    return fig


def plot_history_progress(
    history: pd.DataFrame,
    group_name: str,
    progress_png: str,
    player_colors: dict[str, tuple[float, float, float, float]],
    y_scale: str = "linear",
    title_suffix: str = "",
):
    if history.empty:
        print(f"{group_name}: no matching history rows; skipped progress plot.")
        return None

    hist = history.copy()
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist = hist.sort_values(["Spieler", "Date"])
    min_date = hist["Date"].min()
    max_date = hist["Date"].max()

    hist["XP Gain"] = hist["Total XP"] - hist.groupby("Spieler")["Total XP"].transform("first")

    fig, ax = plt.subplots(figsize=(14, 6.5))
    for player, grp in hist.groupby("Spieler", sort=True):
        grp = grp.sort_values("Date")
        x = grp["Date"]
        y = grp["XP Gain"]
        if y_scale == "log":
            y_plot = y.where(y > 0, 1)
            ax.plot(
                x,
                y_plot,
                marker="o",
                linewidth=1.8,
                markersize=4,
                label=player,
                color=player_colors.get(player, "C0"),
            )
        else:
            ax.plot(x, y, marker="o", linewidth=1.8, markersize=4, label=player, color=player_colors.get(player, "C0"))

        # Label the latest point directly in the plot.
        x_last = x.iloc[-1]
        y_last = (y.where(y > 0, 1) if y_scale == "log" else y).iloc[-1]
        ax.annotate(
            player,
            xy=(x_last, y_last),
            xytext=(5, 3),
            textcoords="offset points",
            fontsize=8,
            alpha=0.9,
        )

    if y_scale != "log":
        ax.axhline(0, color="black", linewidth=0.8, alpha=0.5)
    ax.set_title(f"{group_name}: XP Gain Since First Snapshot{title_suffix}")
    ax.set_xlabel("Date")
    ax.set_ylabel("XP Gain Since First Snapshot")
    if y_scale == "log":
        ax.set_yscale("log")
        ax.set_ylim(bottom=1)
        ax.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt_log_progress))
    else:
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt))
    if min_date == max_date:
        ax.set_xlim(min_date - pd.Timedelta(days=1), max_date + pd.Timedelta(days=1))
    else:
        ax.set_xlim(min_date - pd.Timedelta(hours=12), max_date + pd.Timedelta(hours=12))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", ncol=2, fontsize=8)

    plt.tight_layout()
    plt.savefig(progress_png, dpi=200)
    print(f"Saved: {progress_png}")
    return fig


def plot_history_progress_per_day(
    history: pd.DataFrame,
    group_name: str,
    progress_png: str,
    player_colors: dict[str, tuple[float, float, float, float]],
    title_suffix: str = "",
    annotate_days: bool = True,
):
    if history.empty:
        print(f"{group_name}: no matching history rows; skipped per-day progress plot.")
        return None

    hist = add_interval_columns(history)
    min_date = hist["Date"].min()
    max_date = hist["Date"].max()

    fig, ax = plt.subplots(figsize=(14, 6.5))
    for player, grp in hist.groupby("Spieler", sort=True):
        grp = grp.sort_values("Date")
        y = grp["XP/day"].fillna(0.0).astype(float)
        ax.plot(
            grp["Date"],
            y,
            marker="o",
            linewidth=1.8,
            markersize=4,
            label=player,
            color=player_colors.get(player, "C0"),
        )

        x_last = grp["Date"].iloc[-1]
        y_last = y.iloc[-1]
        ax.annotate(
            player,
            xy=(x_last, y_last),
            xytext=(5, 3),
            textcoords="offset points",
            fontsize=8,
            alpha=0.9,
        )
        if annotate_days:
            interval_rows = grp[grp["Days Delta"] > 0]
            for _, r in interval_rows.iterrows():
                ax.annotate(
                    f"\N{GREEK CAPITAL LETTER DELTA}d={int(round(float(r['Days Delta'])))}",
                    xy=(r["Date"], float(r["XP/day"])),
                    xytext=(2, -10),
                    textcoords="offset points",
                    fontsize=7,
                    alpha=0.7,
                )

    ax.axhline(0, color="black", linewidth=0.8, alpha=0.5)
    ax.set_title(f"{group_name}: Average Pace Over Interval (\N{GREEK CAPITAL LETTER DELTA}XP/\N{GREEK CAPITAL LETTER DELTA}days){title_suffix}")
    ax.set_xlabel("Date")
    ax.set_ylabel("Average XP/day over interval")
    ax.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt))
    if min_date == max_date:
        ax.set_xlim(min_date - pd.Timedelta(days=1), max_date + pd.Timedelta(days=1))
    else:
        ax.set_xlim(min_date - pd.Timedelta(hours=12), max_date + pd.Timedelta(hours=12))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", ncol=2, fontsize=8)

    plt.tight_layout()
    plt.savefig(progress_png, dpi=200)
    print(f"Saved: {progress_png}")
    return fig


def plot_monthly_gain(
    history: pd.DataFrame,
    group_name: str,
    output_png: str,
    player_colors: dict[str, tuple[float, float, float, float]],
):
    if history.empty:
        print(f"{group_name}: no matching history rows; skipped monthly gain plot.")
        return None

    hist = history.copy()
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist = hist.sort_values(["Spieler", "Date"])
    hist["Month"] = hist["Date"].dt.to_period("M")

    monthly = hist.groupby(["Spieler", "Month"], as_index=False).tail(1).copy()
    monthly = monthly.sort_values(["Spieler", "Month"])
    monthly["Monthly Gain"] = monthly.groupby("Spieler")["Total XP"].diff()
    plot_df = monthly.dropna(subset=["Monthly Gain"]).copy()
    if plot_df.empty:
        print(f"{group_name}: not enough monthly history for gains; skipped monthly gain plot.")
        return None

    months = sorted(plot_df["Month"].unique())
    players = sorted(plot_df["Spieler"].unique())

    x = np.arange(len(months), dtype=float)
    width = max(0.12, 0.82 / max(1, len(players)))
    fig, ax = plt.subplots(figsize=(14, 6.5))

    for i, player in enumerate(players):
        s = plot_df[plot_df["Spieler"] == player].set_index("Month")["Monthly Gain"]
        vals = [float(s.get(m, np.nan)) for m in months]
        offset = (i - (len(players) - 1) / 2.0) * width
        ax.bar(x + offset, vals, width=width * 0.95, label=player, alpha=0.9, color=player_colors.get(player, "C0"))

    ax.set_title(f"{group_name}: XP Gain per Month (Month-End Snapshot Method)")
    ax.set_xlabel("Month")
    ax.set_ylabel("Monthly XP Gain")
    ax.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt))
    ax.set_xticks(x)
    ax.set_xticklabels([str(m) for m in months], rotation=35, ha="right")
    ax.axhline(0, color="black", linewidth=0.8, alpha=0.5)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", ncol=2, fontsize=8)

    fig.subplots_adjust(left=0.08, right=0.96, top=0.92, bottom=0.11)
    plt.savefig(output_png, dpi=200)
    print(f"Saved: {output_png}")
    return fig


def plot_rank_over_time(
    history: pd.DataFrame,
    group_name: str,
    output_png: str,
    player_colors: dict[str, tuple[float, float, float, float]],
):
    if history.empty:
        print(f"{group_name}: no matching history rows; skipped rank plot.")
        return None

    hist = history.copy()
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist = hist.sort_values(["Date", "Spieler"])
    # Stable tie order keeps display deterministic when players have equal Total XP.
    tie_order = {p: i for i, p in enumerate(sorted(hist["Spieler"].unique()))}
    hist["TieOrder"] = hist["Spieler"].map(tie_order)
    hist = hist.sort_values(["Date", "Total XP", "TieOrder"], ascending=[True, False, True])
    hist["Rank"] = hist.groupby("Date")["Total XP"].rank(method="min", ascending=False).astype(int)
    max_rank = int(hist["Rank"].max())
    min_date = hist["Date"].min()
    max_date = hist["Date"].max()
    no_rank_changes = all(grp["Rank"].nunique() <= 1 for _, grp in hist.groupby("Spieler"))

    fig, ax = plt.subplots(figsize=(14, 6.5))
    end_points: list[dict[str, float | str]] = []
    for player, grp in hist.groupby("Spieler", sort=True):
        grp = grp.sort_values("Date")
        color = player_colors.get(player, "C0")
        ax.step(grp["Date"], grp["Rank"], where="post", linewidth=2.0, label=player, color=color)
        ax.plot(grp["Date"], grp["Rank"], linestyle="None", marker="o", markersize=3.5, color=color, alpha=0.9)
        end_points.append({"x": grp["Date"].iloc[-1], "y": float(grp["Rank"].iloc[-1]), "text": player})

    ax.set_title(f"{group_name}: Rank Over Time (by Total XP)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Rank (1 = highest XP)")
    ax.set_yticks(np.arange(1, max_rank + 1))
    ax.set_ylim(max_rank + 0.3, 0.7)
    if min_date == max_date:
        ax.set_xlim(min_date - pd.Timedelta(days=1), max_date + pd.Timedelta(days=1))
    else:
        ax.set_xlim(min_date - pd.Timedelta(hours=12), max_date + pd.Timedelta(hours=12))
    ax.grid(True, alpha=0.3)
    if no_rank_changes:
        ax.text(
            0.5,
            0.94,
            "No rank changes in this time window",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=11,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.9, edgecolor="0.8"),
        )
    place_end_labels(ax, end_points, x_offset_points=6, y_min_sep_data=0.25)

    plt.tight_layout()
    plt.savefig(output_png, dpi=200)
    print(f"Saved: {output_png}")
    return fig


def plot_gap_to_leader(
    history: pd.DataFrame,
    group_name: str,
    output_png: str,
    player_colors: dict[str, tuple[float, float, float, float]],
):
    if history.empty:
        print(f"{group_name}: no matching history rows; skipped gap-to-leader plot.")
        return None

    hist = history.copy()
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist = hist.sort_values(["Date", "Spieler"])
    hist["Leader XP"] = hist.groupby("Date")["Total XP"].transform("max")
    hist["Gap to Leader"] = hist["Leader XP"] - hist["Total XP"]
    hist["Gap Change"] = hist["Gap to Leader"] - hist.groupby("Spieler")["Gap to Leader"].transform("first")
    min_date = hist["Date"].min()
    max_date = hist["Date"].max()

    fig, ax = plt.subplots(figsize=(14, 6.5))
    inset = inset_axes(ax, width="42%", height="42%", loc="upper right", borderpad=1.2)
    end_points: list[dict[str, float | str]] = []
    for player, grp in hist.groupby("Spieler", sort=True):
        grp = grp.sort_values("Date")
        color = player_colors.get(player, "C0")
        ax.plot(grp["Date"], grp["Gap to Leader"], marker="o", linewidth=1.8, markersize=4, label=player, color=color)
        inset.plot(grp["Date"], grp["Gap Change"], linewidth=1.4, alpha=0.9, color=color)
        end_points.append(
            {
                "x": grp["Date"].iloc[-1],
                "y": float(grp["Gap to Leader"].iloc[-1]),
                "text": f"{player} ({xp_axis_fmt(float(grp['Gap to Leader'].iloc[-1]), 0)})",
            }
        )

    ax.set_title(f"{group_name}: Gap to Leader Over Time")
    ax.set_xlabel("Date")
    ax.set_ylabel("XP Gap to Leader")
    ax.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt))
    ax.set_ylim(bottom=0)
    if min_date == max_date:
        ax.set_xlim(min_date - pd.Timedelta(days=1), max_date + pd.Timedelta(days=1))
    else:
        ax.set_xlim(min_date - pd.Timedelta(hours=12), max_date + pd.Timedelta(hours=12))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", ncol=2, fontsize=8)
    inset.axhline(0, color="black", linewidth=0.8, alpha=0.6)
    inset.set_title("Gap change since first snapshot", fontsize=8)
    inset.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt))
    inset.tick_params(axis="both", labelsize=7)
    if min_date == max_date:
        inset.set_xlim(min_date - pd.Timedelta(days=1), max_date + pd.Timedelta(days=1))
    else:
        inset.set_xlim(min_date - pd.Timedelta(hours=12), max_date + pd.Timedelta(hours=12))
    inset.grid(True, alpha=0.25)
    place_end_labels(ax, end_points, x_offset_points=5, y_min_sep_data=5_000.0)

    fig.subplots_adjust(left=0.08, right=0.96, top=0.92, bottom=0.11)
    plt.savefig(output_png, dpi=200)
    print(f"Saved: {output_png}")
    return fig


def plot_gap_delta_per_interval(
    history: pd.DataFrame,
    group_name: str,
    output_png: str,
    player_colors: dict[str, tuple[float, float, float, float]],
):
    if history.empty:
        print(f"{group_name}: no matching history rows; skipped gap-delta plot.")
        return None

    hist = history.copy()
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist = hist.sort_values(["Date", "Spieler"])
    hist["Leader XP"] = hist.groupby("Date")["Total XP"].transform("max")
    hist["Gap to Leader"] = hist["Leader XP"] - hist["Total XP"]
    hist = hist.sort_values(["Spieler", "Date"])
    hist["Delta Gap"] = hist.groupby("Spieler")["Gap to Leader"].diff()
    min_date = hist["Date"].min()
    max_date = hist["Date"].max()

    fig, ax = plt.subplots(figsize=(14, 6.5))
    for player, grp in hist.groupby("Spieler", sort=True):
        grp = grp.sort_values("Date")
        ax.plot(
            grp["Date"],
            grp["Delta Gap"],
            marker="o",
            linewidth=1.8,
            markersize=4,
            label=player,
            color=player_colors.get(player, "C0"),
        )

    ax.axhline(0, color="black", linewidth=0.8, alpha=0.6)
    ax.set_title(f"{group_name}: Gap Change per Interval (Delta gap)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Delta gap (negative = catching up)")
    ax.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt))
    if min_date == max_date:
        ax.set_xlim(min_date - pd.Timedelta(days=1), max_date + pd.Timedelta(days=1))
    else:
        ax.set_xlim(min_date - pd.Timedelta(hours=12), max_date + pd.Timedelta(hours=12))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", ncol=2, fontsize=8)

    plt.tight_layout()
    plt.savefig(output_png, dpi=200)
    print(f"Saved: {output_png}")
    return fig


def plot_interval_pace(
    history: pd.DataFrame,
    group_name: str,
    output_png: str,
    player_colors: dict[str, tuple[float, float, float, float]],
    trend_window: int = 3,
):
    if history.empty:
        print(f"{group_name}: no matching history rows; skipped interval pace plot.")
        return None

    hist = add_interval_columns(history)
    hist = hist[hist["Days Delta"] > 0].copy()
    if hist.empty:
        print(f"{group_name}: no valid intervals for pace; skipped interval pace plot.")
        return None
    min_date = hist["Date"].min()
    max_date = hist["Date"].max()

    fig, ax = plt.subplots(figsize=(14, 6.5))
    end_points: list[dict[str, float | str]] = []
    for player, grp in hist.groupby("Spieler", sort=True):
        grp = grp.sort_values("Date")
        y = grp["XP/day"].astype(float)
        trend = y.rolling(window=trend_window, min_periods=1).mean()
        color = player_colors.get(player, "C0")
        ax.plot(grp["Date"], y, linestyle="None", marker="o", markersize=3.5, alpha=0.28, color=color)
        ax.plot(grp["Date"], trend, linewidth=2.2, color=color)
        end_points.append({"x": grp["Date"].iloc[-1], "y": float(trend.iloc[-1]), "text": player})

    ax.axhline(0, color="black", linewidth=0.8, alpha=0.5)
    ax.set_title(
        f"{group_name}: Interval Pace (\N{GREEK CAPITAL LETTER DELTA}XP/\N{GREEK CAPITAL LETTER DELTA}days) + Trend (rolling {trend_window})"
    )
    ax.set_xlabel("Date")
    ax.set_ylabel("Average XP/day over interval")
    ax.yaxis.set_major_formatter(FuncFormatter(xp_axis_fmt))
    if min_date == max_date:
        ax.set_xlim(min_date - pd.Timedelta(days=1), max_date + pd.Timedelta(days=1))
    else:
        ax.set_xlim(min_date - pd.Timedelta(hours=12), max_date + pd.Timedelta(hours=12))
    ax.grid(True, alpha=0.3)
    place_end_labels(ax, end_points, x_offset_points=6, y_min_sep_data=2_000.0)

    plt.tight_layout()
    plt.savefig(output_png, dpi=200)
    print(f"Saved: {output_png}")
    return fig


def parse_args():
    parser = argparse.ArgumentParser(description="Pogo XP plots by named player groups.")
    parser.add_argument("--groups-file", default=GROUPS_FILE, help="Group definition file.")
    parser.add_argument(
        "--output-date",
        default=pd.Timestamp.today().date().isoformat(),
        help="Date used in output filenames (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--include-optional-8",
        action="store_true",
        help="Also generate optional plot 8 (interval pace with trend).",
    )
    parser.add_argument("--no-show", action="store_true", help="Do not open matplotlib windows.")
    return parser.parse_args()


def main():
    args = parse_args()
    output_date = normalize_date(args.output_date)

    curve = read_curve(CURVE_FILE)
    total_xp_by_level = dict(zip(curve["Level"], curve["Total XP"]))
    history = load_history(HISTORY_FILE, total_xp_by_level)
    groups = parse_groups(args.groups_file)
    history_names = set(history["Spieler"].astype(str).unique())

    for group_name, players_in_group in groups.items():
        resolved_players = resolve_group_players(players_in_group, history_names, group_name)
        group_hist = history[history["Spieler"].isin(resolved_players)].copy()
        if group_hist.empty:
            print(f"{group_name}: no matching players in history, skipped.")
            continue

        interval_hist = add_interval_columns(group_hist)
        warn_large_intervals(interval_hist, group_name, threshold_days=10.0)

        latest = latest_players(group_hist)
        latest = latest[latest["Spieler"].isin(resolved_players)].copy()
        if latest.empty:
            print(f"{group_name}: no latest player data, skipped.")
            continue
        player_colors = build_player_colors(list(group_hist["Spieler"].unique()))

        out_dir = group_output_dir(group_name)
        os.makedirs(out_dir, exist_ok=True)

        out1 = os.path.join(out_dir, build_output_name(1, output_date, group_name, "xp_growth_with_players_pogo"))
        out2 = os.path.join(out_dir, build_output_name(2, output_date, group_name, "xp_progress_player_pogo"))
        out3 = os.path.join(out_dir, build_output_name(3, output_date, group_name, "xp_progress_per_day_player_pogo"))
        out4 = os.path.join(out_dir, build_output_name(4, output_date, group_name, "xp_gain_per_month_player_pogo"))
        out5 = os.path.join(out_dir, build_output_name(5, output_date, group_name, "rank_over_time_pogo"))
        out6 = os.path.join(out_dir, build_output_name(6, output_date, group_name, "gap_to_leader_pogo"))
        out6d = os.path.join(out_dir, build_output_name("6d", output_date, group_name, "gap_delta_per_interval_pogo"))
        out8 = os.path.join(out_dir, build_output_name(8, output_date, group_name, "interval_pace_pogo"))
        out_log1 = os.path.join(
            out_dir, build_output_name("log1", output_date, group_name, "log_xp_growth_with_players_pogo")
        )
        out_log2 = os.path.join(
            out_dir, build_output_name("log2", output_date, group_name, "log_xp_progress_player_pogo")
        )

        fig = plot_curve_with_players(curve, latest, group_name, out1, player_colors)
        if fig is not None:
            plt.close(fig)
        fig = plot_history_progress(group_hist, group_name, out2, player_colors)
        if fig is not None:
            plt.close(fig)
        fig = plot_curve_with_players(
            curve,
            latest,
            group_name,
            out_log1,
            player_colors,
            y_scale="log",
            title_suffix=" (Log Y)",
        )
        if fig is not None:
            plt.close(fig)
        fig = plot_history_progress(
            group_hist,
            group_name,
            out_log2,
            player_colors,
            y_scale="log",
            title_suffix=" (Log Y)",
        )
        if fig is not None:
            plt.close(fig)
        fig = plot_history_progress_per_day(group_hist, group_name, out3, player_colors, annotate_days=True)
        if fig is not None:
            plt.close(fig)
        fig = plot_monthly_gain(group_hist, group_name, out4, player_colors)
        if fig is not None:
            plt.close(fig)
        fig = plot_rank_over_time(group_hist, group_name, out5, player_colors)
        if fig is not None:
            plt.close(fig)
        fig = plot_gap_to_leader(group_hist, group_name, out6, player_colors)
        if fig is not None:
            plt.close(fig)
        fig = plot_gap_delta_per_interval(group_hist, group_name, out6d, player_colors)
        if fig is not None:
            plt.close(fig)
        if args.include_optional_8:
            fig = plot_interval_pace(group_hist, group_name, out8, player_colors, trend_window=3)
            if fig is not None:
                plt.close(fig)


if __name__ == "__main__":
    main()
