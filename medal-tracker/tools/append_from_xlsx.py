from __future__ import annotations

from pathlib import Path
import re
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import inputs_dir, medal_snapshots_path, medals_config_path

ACCOUNT_ORDER = ["Thombay", "Cerius", "Thomzay"]
MEDAL_DISPLAY_ORDER = [
    "Kanto",
    "Collector",
    "Sightseer",
    "Johto",
    "Berry Master",
    "Hoenn",
    "Idol",
    "Master League Veteran",
    "Unova",
    "Triathlete",
    "Rising Star",
    "Life of a Party",
    "Jogger",
    "Scientist",
    "Breeder",
    "Backpacker",
    "Battle Girl",
    "Pikachu Fan",
    "Gym Leader",
    "Pokemon Ranger",
    "Sinnoh",
    "Great League Veteran",
    "Ultra League Veteran",
    "Purifier",
    "Hero",
    "Kalos",
    "Alola",
    "Galar",
    "Picnicker",
    "Successor",
    "Raid Expert",
    "Hisui",
    "Tiny Pokemon Collector",
    "Jumbo Pokemon Collector",
    "Fisher",
    "Ace Trainer",
    "Youngster",
    "Unown",
    "Champion",
    "Battle Legend",
    "Gentleman",
    "Pilot",
    "Cameraman",
    "Ultra Hero",
    "Rising Star Duo",
    "Mega Evolution Guru",
    "Expert Navigator",
    "Paldea",
    "Showcase Star",
    "Best Buddy",
    "Community Member",
    "Wayfarer",
    "Normal",
    "Fighting",
    "Flying",
    "Poison",
    "Ground",
    "Rock",
    "Bug",
    "Ghost",
    "Fire",
    "Water",
    "Grass",
    "Electric",
    "Psychic",
    "Ice",
    "Dark",
    "Fairy",
    "Steel",
    "Dragon",
    "Distance walked",
    "Pokemon Caught",
    "PokeStops Visited",
    "Total XP",
    "Platinum Medals",
]


def _medal_id(name: str) -> str:
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _as_number(v):
    try:
        if pd.isna(v):
            return None
        n = float(v)
        if n.is_integer():
            return int(n)
        return n
    except Exception:
        return None


def _extract_data_sheet(xlsx: Path, sheet: str, account: str) -> pd.DataFrame:
    df = pd.read_excel(xlsx, sheet_name=sheet)
    date_cols = [c for c in df.columns if str(c).startswith("Date")]
    if not date_cols:
        return pd.DataFrame(columns=["date", "account", "medal_id", "value"])

    rows = []
    for dcol in date_cols:
        snap_date = pd.to_datetime(df[dcol].iloc[0], errors="coerce")
        if pd.isna(snap_date):
            continue
        body = df.iloc[1:].copy()
        body = body[body["Medal"].notna()]
        for _, r in body.iterrows():
            medal = str(r["Medal"]).strip()
            medal_id = _medal_id(medal)
            if medal_id == "total_xp":
                # Total XP is imported from canonical XP snapshots, never from medal sheet.
                continue
            val = _as_number(r[dcol])
            if not medal or val is None:
                continue
            rows.append(
                {
                    "date": snap_date.date().isoformat(),
                    "account": account,
                    "medal_id": medal_id,
                    "value": val,
                }
            )
    return pd.DataFrame(rows)


def _extract_single_snapshot_sheet(xlsx: Path, sheet: str, account: str) -> pd.DataFrame:
    df = pd.read_excel(xlsx, sheet_name=sheet)
    if "Date Start" not in df.columns or "Medal" not in df.columns:
        return pd.DataFrame(columns=["date", "account", "medal_id", "value"])

    snap_date = pd.to_datetime(df["Date Start"].iloc[0], errors="coerce")
    if pd.isna(snap_date):
        return pd.DataFrame(columns=["date", "account", "medal_id", "value"])

    body = df.iloc[1:].copy()
    body = body[body["Medal"].notna()]
    rows = []
    for _, r in body.iterrows():
        medal = str(r["Medal"]).strip()
        medal_id = _medal_id(medal)
        if medal_id == "total_xp":
            # Total XP is imported from canonical XP snapshots, never from medal sheet.
            continue
        val = _as_number(r["Date Start"])
        if not medal or val is None:
            continue
        rows.append(
            {
                "date": snap_date.date().isoformat(),
                "account": account,
                "medal_id": medal_id,
                "value": val,
            }
        )
    return pd.DataFrame(rows)


def _extract_goals_from_sheet(xlsx: Path, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(xlsx, sheet_name=sheet)
    if "Medal" not in df.columns or "Goal" not in df.columns:
        return pd.DataFrame(columns=["medal_id", "display_name", "goal_value", "sheet"])

    body = df[df["Medal"].notna()].copy()
    body = body[body["Goal"].notna()].copy()
    rows = []
    for _, r in body.iterrows():
        medal = str(r["Medal"]).strip()
        goal = _as_number(r["Goal"])
        if not medal or goal is None:
            continue
        rows.append(
            {
                "medal_id": _medal_id(medal),
                "display_name": medal,
                "goal_value": goal,
                "sheet": sheet,
            }
        )
    return pd.DataFrame(rows)


def _sort_snapshot_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    order_map = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    d["_acc_order"] = d["account"].map(order_map).fillna(999)
    d = d.sort_values(["date", "_acc_order", "account", "medal_id"]).drop(columns=["_acc_order"])
    d["date"] = d["date"].dt.date.astype(str)
    return d.reset_index(drop=True)


def _ordered_medal_ids_for_template(goals: pd.DataFrame) -> list[str]:
    order_map = {name.lower(): i for i, name in enumerate(MEDAL_DISPLAY_ORDER)}
    g = goals.copy()
    g["_order"] = g["display_name"].astype(str).str.lower().map(order_map).fillna(9_999)
    g = g.sort_values(["_order", "display_name"]).reset_index(drop=True)
    ordered_ids = g["medal_id"].astype(str).tolist()
    # Total XP is derived from XP history; keep it out of manual snapshot template.
    return [mid for mid in ordered_ids if mid != "total_xp"]


def main():
    workbook = inputs_dir() / "templates" / "Pogo Medals.xlsx"
    out_csv = medal_snapshots_path()
    goals_csv = medals_config_path()
    template_csv = inputs_dir() / "templates" / "medal_snapshots_template.csv"

    if not workbook.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook}")

    frames = [
        _extract_data_sheet(workbook, "Data", "Thombay"),
        _extract_single_snapshot_sheet(workbook, "Data Cerius", "Cerius"),
        _extract_single_snapshot_sheet(workbook, "Data Thomzay", "Thomzay"),
    ]
    all_rows = pd.concat(frames, ignore_index=True)
    if all_rows.empty:
        print("No medal rows extracted.")
        return

    all_rows = all_rows.drop_duplicates(subset=["date", "account", "medal_id"], keep="last")
    all_rows = _sort_snapshot_rows(all_rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    all_rows.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # Goals are shared config, same across accounts: write once to medal_goals.csv
    goal_frames = [
        _extract_goals_from_sheet(workbook, "Data"),
        _extract_goals_from_sheet(workbook, "Data Cerius"),
        _extract_goals_from_sheet(workbook, "Data Thomzay"),
    ]
    goals = pd.concat(goal_frames, ignore_index=True)
    if not goals.empty:
        inconsistent = goals.groupby("medal_id")["goal_value"].nunique()
        inconsistent = inconsistent[inconsistent > 1]
        if not inconsistent.empty:
            print("Warning: inconsistent goal values found across sheets for medal_id(s):")
            for mid in inconsistent.index.tolist():
                vals = sorted(set(goals[goals["medal_id"] == mid]["goal_value"].tolist()))
                print(f"  - {mid}: {vals}")

        goals = goals.sort_values(["medal_id", "sheet"]).drop_duplicates(subset=["medal_id"], keep="first")
        goals = goals[["medal_id", "display_name", "goal_value"]].reset_index(drop=True)
        goals.to_csv(goals_csv, index=False, encoding="utf-8-sig")
        print(f"Saved: {goals_csv}")
        print(f"Extracted goals: {len(goals)}")

        ordered_medal_ids = _ordered_medal_ids_for_template(goals)
        template_rows = []
        for account in ACCOUNT_ORDER:
            first_row_for_account = True
            for medal_id in ordered_medal_ids:
                template_rows.append(
                    {
                        "date": "YYYY-MM-DD" if first_row_for_account else "",
                        "account": account,
                        "medal_id": medal_id,
                        "value": "",
                    }
                )
                first_row_for_account = False
        pd.DataFrame(template_rows, columns=["date", "account", "medal_id", "value"]).to_csv(
            template_csv, index=False, encoding="utf-8-sig"
        )
        print(f"Saved: {template_csv}")

    print(f"Saved: {out_csv}")
    print(f"Extracted rows: {len(all_rows)}")


if __name__ == "__main__":
    main()
