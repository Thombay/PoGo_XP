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
    xp_snapshots_path,
)

ACCOUNT_ORDER = ["Thombay", "Cerius", "Thomzay"]


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _try_load_xp_snapshots(path: Path) -> pd.DataFrame:
    xp = _load_csv(path)
    if xp.empty:
        curve_path = total_xp_curve_path()
        if curve_path.exists():
            print(
                "Info: found inputs/reference/total_xp_curve.csv (XP level curve). "
                "This is static reference data, not per-account snapshots."
            )
        return xp

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
        "('date', 'spieler', 'total xp'). XP import skipped."
    )
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
    xp_df = _try_load_xp_snapshots(xp_snapshots)
    enriched = inject_total_xp_rows(snapshots_df, xp_df)
    enriched = sort_medal_rows(enriched)

    out_file = medal_report_path()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(out_file, index=False, encoding="utf-8-sig")

    print(f"Saved: {out_file}")
    print(f"Rows in medal config: {len(cfg_df)}")
    print(f"Rows in medal snapshots: {len(snapshots_df)}")
    print(f"Rows in report after XP injection: {len(enriched)}")


if __name__ == "__main__":
    main()
