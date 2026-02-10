import argparse
import os
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

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


def build_output_name(order: int, date_str: str, group_name: str, stem: str) -> str:
    return f"{order}_{normalize_date(date_str)}_{sanitize_name(group_name)}_{stem}.png"


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


def plot_curve_with_players(
    curve: pd.DataFrame,
    players: pd.DataFrame,
    group_name: str,
    output_png: str,
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

    colors = plt.cm.tab10(np.linspace(0, 1, max(10, n)))
    for i, r in players_plot.iterrows():
        ax.scatter(
            [r["x_plot"]],
            [r["y_plot"]],
            color=colors[i % len(colors)],
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

    plt.tight_layout()
    plt.savefig(output_png, dpi=200)
    print(f"Saved: {output_png}")
    return fig


def plot_history_progress(
    history: pd.DataFrame,
    group_name: str,
    progress_png: str,
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
            ax.plot(x, y_plot, marker="o", linewidth=1.8, markersize=4, label=player)
        else:
            ax.plot(x, y, marker="o", linewidth=1.8, markersize=4, label=player)

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
    ax.set_title(f"{group_name}: Player XP Progress (Gain Since First Snapshot){title_suffix}")
    ax.set_xlabel("Date")
    ax.set_ylabel("XP Gain")
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


def parse_args():
    parser = argparse.ArgumentParser(description="Pogo XP plots by named player groups.")
    parser.add_argument("--groups-file", default=GROUPS_FILE, help="Group definition file.")
    parser.add_argument(
        "--output-date",
        default=pd.Timestamp.today().date().isoformat(),
        help="Date used in output filenames (YYYY-MM-DD).",
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

    figures = []
    for group_name, players_in_group in groups.items():
        group_hist = history[history["Spieler"].isin(players_in_group)].copy()
        if group_hist.empty:
            print(f"{group_name}: no matching players in history, skipped.")
            continue

        latest = latest_players(group_hist)
        latest = latest[latest["Spieler"].isin(players_in_group)].copy()
        if latest.empty:
            print(f"{group_name}: no latest player data, skipped.")
            continue

        out_dir = group_output_dir(group_name)
        os.makedirs(out_dir, exist_ok=True)

        out1 = os.path.join(out_dir, build_output_name(1, output_date, group_name, "xp_growth_with_players_pogo"))
        out2 = os.path.join(out_dir, build_output_name(2, output_date, group_name, "xp_progress_player_pogo"))
        out3 = os.path.join(out_dir, build_output_name(3, output_date, group_name, "log_xp_growth_with_players_pogo"))
        out4 = os.path.join(out_dir, build_output_name(4, output_date, group_name, "log_xp_progress_player_pogo"))

        figures.append(plot_curve_with_players(curve, latest, group_name, out1))
        figures.append(plot_history_progress(group_hist, group_name, out2))
        figures.append(
            plot_curve_with_players(
                curve,
                latest,
                group_name,
                out3,
                y_scale="log",
                title_suffix=" (Log Y)",
            )
        )
        figures.append(
            plot_history_progress(
                group_hist,
                group_name,
                out4,
                y_scale="log",
                title_suffix=" (Log Y)",
            )
        )

    for fig in figures:
        if fig is not None:
            plt.close(fig)


if __name__ == "__main__":
    main()
