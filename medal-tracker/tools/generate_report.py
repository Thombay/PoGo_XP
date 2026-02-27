from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import (
    medal_report_path,
    medal_snapshots_path,
    medals_config_path,
    total_xp_curve_path,
    xp_history_path,
    xp_snapshots_path,
)

ACCOUNT_ORDER = ["Thombay", "Cerius", "Thomzay"]
DERIVED_MEDAL_ID = "platinum_medals"
EXCLUDED_MANUAL_MEDAL_IDS = {"total_xp", DERIVED_MEDAL_ID}
GOAL_ALIAS_BY_MEDAL_ID = {
    "distance_walked": "jogger",
    "pokemon_caught": "collector",
    "pokestops_visited": "backpacker",
    "pokestops_vistited": "backpacker",
}


def goal_medal_id_for(medal_id: str) -> str:
    mid = str(medal_id).strip().lower()
    return GOAL_ALIAS_BY_MEDAL_ID.get(mid, mid)


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _to_int_series(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[^0-9\-]", "", regex=True)
    cleaned = cleaned.replace("", pd.NA)
    return pd.to_numeric(cleaned, errors="coerce")


def _try_load_xp_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["date", "account", "total_xp"])

    curve_path = total_xp_curve_path()
    if not curve_path.exists():
        return pd.DataFrame(columns=["date", "account", "total_xp"])

    curve = pd.read_csv(curve_path, sep=";", engine="python", encoding="utf-8-sig")
    if not {"Level", "Total XP"}.issubset(curve.columns):
        return pd.DataFrame(columns=["date", "account", "total_xp"])

    curve = curve[["Level", "Total XP"]].copy()
    curve["Level"] = _to_int_series(curve["Level"])
    curve["Total XP"] = _to_int_series(curve["Total XP"])
    curve = curve.dropna(subset=["Level", "Total XP"]).copy()
    curve["Level"] = curve["Level"].astype(int)
    curve["Total XP"] = curve["Total XP"].astype(int)
    total_xp_by_level = dict(zip(curve["Level"], curve["Total XP"]))

    hist = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    needed = {"Date", "Spieler", "Lvl", "XP Bar"}
    if not needed.issubset(hist.columns):
        return pd.DataFrame(columns=["date", "account", "total_xp"])

    hist = hist.copy()
    hist["date"] = pd.to_datetime(hist["Date"], errors="coerce")
    hist["account"] = hist["Spieler"].astype(str).str.strip()
    hist["Lvl"] = _to_int_series(hist["Lvl"])
    hist["XP Bar"] = _to_int_series(hist["XP Bar"])
    hist = hist.dropna(subset=["date", "account", "Lvl", "XP Bar"]).copy()
    hist["Lvl"] = hist["Lvl"].astype(int)
    hist["XP Bar"] = hist["XP Bar"].astype(int)
    hist["base_xp"] = hist["Lvl"].map(total_xp_by_level)
    hist = hist.dropna(subset=["base_xp"]).copy()
    hist["total_xp"] = hist["base_xp"].astype(int) + hist["XP Bar"]

    out = hist[["date", "account", "total_xp"]].copy()
    out = out.sort_values(["account", "date"]).reset_index(drop=True)
    return out


def _try_load_xp_snapshots(path: Path) -> pd.DataFrame:
    xp = _load_csv(path)
    if xp.empty:
        fallback = _try_load_xp_history(xp_history_path())
        if not fallback.empty:
            print("Info: using XP from inputs/data/xp_history.csv for total_xp injection.")
            return fallback
        curve_path = total_xp_curve_path()
        if curve_path.exists():
            print(
                "Info: found inputs/reference/total_xp_curve.csv (XP level curve). "
                "This is static reference data, not per-account snapshots."
            )
        return pd.DataFrame(columns=["date", "account", "total_xp"])

    cols = {c.lower().strip(): c for c in xp.columns}
    # Expected canonical columns (to be provided in future data migration).
    if {"date", "spieler", "total xp"}.issubset(cols):
        out = xp[[cols["date"], cols["spieler"], cols["total xp"]]].copy()
        out.columns = ["date", "account", "total_xp"]
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date", "account", "total_xp"]).sort_values(["account", "date"])
        return out

    print(
        "Warning: inputs/data/xp_snapshots.csv does not contain canonical snapshot columns "
        "('date', 'spieler', 'total xp'). Falling back to inputs/data/xp_history.csv."
    )
    fallback = _try_load_xp_history(xp_history_path())
    if not fallback.empty:
        return fallback
    return pd.DataFrame(columns=["date", "account", "total_xp"])


def inject_total_xp_rows(medal_df: pd.DataFrame, xp_df: pd.DataFrame) -> pd.DataFrame:
    if medal_df.empty or xp_df.empty:
        return medal_df

    medals = medal_df.copy()
    medals["date"] = pd.to_datetime(medals["date"], errors="coerce")
    medals = medals.dropna(subset=["date", "account"])

    requests = medals[["date", "account"]].drop_duplicates().sort_values(["account", "date"])
    xp_sorted = xp_df.sort_values(["account", "date"]).copy()

    joined = pd.merge_asof(
        requests.sort_values("date"),
        xp_sorted.sort_values("date"),
        on="date",
        by="account",
        direction="backward",
    )
    joined = joined.dropna(subset=["total_xp"]).copy()
    if joined.empty:
        return medals

    xp_rows = pd.DataFrame(
        {
            "date": joined["date"].dt.date.astype(str),
            "account": joined["account"],
            "medal_id": "total_xp",
            "value": joined["total_xp"],
        }
    )
    combined = pd.concat([medals, xp_rows], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "account", "medal_id"], keep="last")
    return combined


def inject_derived_platinum_rows(medal_df: pd.DataFrame, cfg_df: pd.DataFrame) -> pd.DataFrame:
    if medal_df.empty or cfg_df.empty:
        return medal_df

    if not {"medal_id", "goal_value"}.issubset(cfg_df.columns):
        return medal_df

    goals = cfg_df[["medal_id", "goal_value"]].copy()
    goals["medal_id"] = goals["medal_id"].astype(str).str.strip().str.lower()
    goals["goal_medal_id"] = goals["medal_id"].map(goal_medal_id_for)
    goals["goal_value"] = pd.to_numeric(goals["goal_value"], errors="coerce")
    goals = goals.dropna(subset=["goal_medal_id", "goal_value"]).copy()
    goals = goals.sort_values("goal_value", ascending=False).drop_duplicates(subset=["goal_medal_id"], keep="first")

    source = medal_df.copy()
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source["account"] = source["account"].astype(str).str.strip()
    source["medal_id"] = source["medal_id"].astype(str).str.strip().str.lower()
    source["value"] = pd.to_numeric(source["value"], errors="coerce")
    source = source.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    source = source[~source["medal_id"].isin(EXCLUDED_MANUAL_MEDAL_IDS)].copy()
    if source.empty:
        return medal_df

    source["goal_medal_id"] = source["medal_id"].map(goal_medal_id_for)
    source = source.merge(goals[["goal_medal_id", "goal_value"]], on="goal_medal_id", how="left")
    source = source.dropna(subset=["goal_value"]).copy()
    # Alias-safe de-duplication: if legacy + canonical IDs exist on the same day, count only once.
    source = (
        source.sort_values("date")
        .groupby(["date", "account", "goal_medal_id"], as_index=False)
        .agg({"value": "max", "goal_value": "max"})
    )
    platinum_frames: list[pd.DataFrame] = []
    for account, grp in source.groupby("account", sort=False):
        g = grp.sort_values("date").copy()
        if g.empty:
            continue
        value_wide = g.pivot_table(index="date", columns="goal_medal_id", values="value", aggfunc="max")
        if value_wide.empty:
            continue
        value_wide = value_wide.sort_index().ffill()
        goal_by_medal = g.groupby("goal_medal_id", as_index=True)["goal_value"].max()
        common_cols = [c for c in value_wide.columns if c in set(goal_by_medal.index)]
        if not common_cols:
            continue
        reached_wide = value_wide[common_cols].ge(goal_by_medal.loc[common_cols], axis=1).fillna(False)
        counts = reached_wide.sum(axis=1).astype(int)
        platinum_frames.append(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(counts.index, errors="coerce"),
                    "account": str(account),
                    "reached": counts.values,
                }
            )
        )
    platinum_counts = pd.concat(platinum_frames, ignore_index=True) if platinum_frames else pd.DataFrame(
        columns=["date", "account", "reached"]
    )
    if platinum_counts.empty:
        return medal_df

    platinum_rows = pd.DataFrame(
        {
            "date": platinum_counts["date"].dt.date.astype(str),
            "account": platinum_counts["account"],
            "medal_id": DERIVED_MEDAL_ID,
            "value": platinum_counts["reached"],
        }
    )
    combined = pd.concat([medal_df, platinum_rows], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "account", "medal_id"], keep="last")
    return combined


def sort_medal_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    order_map = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    d["_acc_order"] = d["account"].map(order_map).fillna(999)
    d = d.sort_values(["date", "_acc_order", "account", "medal_id"]).drop(columns=["_acc_order"])
    d["date"] = d["date"].dt.date.astype(str)
    return d.reset_index(drop=True)


def main():
    medals_cfg = medals_config_path()
    medals_snapshots = medal_snapshots_path()
    xp_snapshots = xp_snapshots_path()

    cfg_df = _load_csv(medals_cfg)
    snapshots_df = _load_csv(medals_snapshots)
    # Allow compact manual input style where date/account are written once per block.
    if not snapshots_df.empty and {"date", "account"}.issubset(snapshots_df.columns):
        snapshots_df["date"] = snapshots_df["date"].replace("", pd.NA).ffill()
        snapshots_df["account"] = snapshots_df["account"].replace("", pd.NA).ffill()
        snapshots_df = snapshots_df[snapshots_df["date"].astype(str).str.upper() != "YYYY-MM-DD"].copy()
    if not snapshots_df.empty and "medal_id" in snapshots_df.columns:
        medal_ids = snapshots_df["medal_id"].astype(str).str.strip().str.lower()
        manual_derived = medal_ids.isin(EXCLUDED_MANUAL_MEDAL_IDS)
        dropped_count = int(manual_derived.sum())
        if dropped_count:
            print(
                f"Info: removed {dropped_count} manual derived row(s) from medal snapshots "
                f"({', '.join(sorted(EXCLUDED_MANUAL_MEDAL_IDS))}); "
                "derived medals are injected by the pipeline."
            )
            snapshots_df = snapshots_df[~manual_derived].copy()
    xp_df = _try_load_xp_snapshots(xp_snapshots)
    enriched = inject_total_xp_rows(snapshots_df, xp_df)
    enriched = inject_derived_platinum_rows(enriched, cfg_df)
    enriched = sort_medal_rows(enriched)

    out_file = medal_report_path()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(out_file, index=False, encoding="utf-8-sig")

    print(f"Saved: {out_file}")
    print(f"Rows in medal config: {len(cfg_df)}")
    print(f"Rows in medal snapshots: {len(snapshots_df)}")
    print(f"Rows in report after derived injections: {len(enriched)}")


if __name__ == "__main__":
    main()
