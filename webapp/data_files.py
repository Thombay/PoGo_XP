from __future__ import annotations

from pathlib import Path

import pandas as pd

from shared.xp_utils import total_xp_from_level_input


def to_int_series(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[^0-9\-]", "", regex=True)
    cleaned = cleaned.replace("", pd.NA)
    return pd.to_numeric(cleaned, errors="coerce")


def parse_groups(path: Path) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    if not path.exists():
        return groups

    current: str | None = None
    with open(path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.endswith(":"):
                current = line[:-1].strip()
                groups.setdefault(current, [])
                continue
            if current is None:
                continue
            names = [x.strip() for x in line.split(",")]
            for name in names:
                if name and name != "...":
                    groups[current].append(name)

    for group, names in list(groups.items()):
        groups[group] = list(dict.fromkeys(names))
        if not groups[group]:
            groups.pop(group, None)
    return groups


def save_groups(path: Path, groups: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for group, names in groups.items():
        group_name = str(group).strip()
        if not group_name:
            continue
        unique_names: list[str] = []
        seen: set[str] = set()
        for raw_name in names:
            name = str(raw_name).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            unique_names.append(name)
        lines.append(f"{group_name}:")
        lines.append(",".join(unique_names))
        lines.append("")
    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8-sig")


def add_account_to_groups(path: Path, account_name: str, target_groups: list[str] | None = None) -> list[str]:
    account = str(account_name).strip()
    if not account:
        return []

    groups = parse_groups(path)
    group_order = list(groups.keys())
    if "All" not in groups:
        groups["All"] = []
        group_order.append("All")

    requested = ["All"] + [str(g).strip() for g in (target_groups or []) if str(g).strip()]
    selected_groups: list[str] = []
    for group_name in requested:
        if group_name not in selected_groups:
            selected_groups.append(group_name)
        if group_name not in groups:
            groups[group_name] = []
            group_order.append(group_name)
        if account not in groups[group_name]:
            groups[group_name].append(account)

    ordered_groups = {group_name: groups.get(group_name, []) for group_name in group_order}
    save_groups(path, ordered_groups)
    return selected_groups


def accounts_for_selected_group(
    selected_group: str,
    groups: dict[str, list[str]],
    all_accounts: list[str],
) -> list[str]:
    available = set(all_accounts)
    if selected_group == "All" and "All" not in groups:
        return list(all_accounts)
    group_accounts = [str(a).strip() for a in groups.get(selected_group, []) if str(a).strip()]
    return [a for a in group_accounts if a in available]


def load_curve_map(path: Path) -> dict[int, int]:
    if not path.exists():
        return {}
    curve = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    if not {"Level", "Total XP"}.issubset(curve.columns):
        return {}
    curve["Level"] = to_int_series(curve["Level"])
    curve["Total XP"] = to_int_series(curve["Total XP"])
    curve = curve.dropna(subset=["Level", "Total XP"]).copy()
    curve["Level"] = curve["Level"].astype(int)
    curve["Total XP"] = curve["Total XP"].astype(int)
    return dict(zip(curve["Level"], curve["Total XP"]))


def load_xp_history(path: Path, curve_map: dict[int, int]) -> pd.DataFrame:
    cols = ["Date", "Spieler", "Lvl", "XP Bar", "Total XP"]
    if not path.exists():
        return pd.DataFrame(columns=cols)

    hist = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    if not {"Date", "Spieler", "Lvl", "XP Bar"}.issubset(hist.columns):
        return pd.DataFrame(columns=cols)

    hist = hist.copy()
    hist["Date"] = pd.to_datetime(hist["Date"], errors="coerce")
    hist["Spieler"] = hist["Spieler"].astype(str).str.strip()
    hist["Lvl"] = to_int_series(hist["Lvl"])
    hist["XP Bar"] = to_int_series(hist["XP Bar"])
    hist = hist.dropna(subset=["Date", "Spieler", "Lvl", "XP Bar"]).copy()
    hist["Lvl"] = hist["Lvl"].astype(int)
    hist["XP Bar"] = hist["XP Bar"].astype(int)
    hist = hist[hist["Lvl"].isin(set(curve_map.keys()))].copy()
    hist["Total XP"] = hist.apply(
        lambda row: total_xp_from_level_input(int(row["Lvl"]), int(row["XP Bar"]), curve_map),
        axis=1,
    )
    return hist[cols].sort_values(["Date", "Spieler"]).reset_index(drop=True)


def load_medal_snapshots(
    path: Path,
    account_order: list[str] | None = None,
    excluded_manual_medal_ids: set[str] | None = None,
) -> pd.DataFrame:
    cols = ["date", "account", "medal_id", "value"]
    if not path.exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")
    if not set(cols).issubset(df.columns):
        return pd.DataFrame(columns=cols)

    excluded = set(excluded_manual_medal_ids or set())
    ordered_accounts = [str(a).strip() for a in (account_order or []) if str(a).strip()]

    df = df.copy()
    df["date"] = df["date"].replace("", pd.NA).ffill()
    df["account"] = df["account"].replace("", pd.NA).ffill()
    df = df[df["date"].astype(str).str.upper() != "YYYY-MM-DD"].copy()
    df["medal_id"] = df["medal_id"].astype(str).str.strip().str.lower()
    if excluded:
        df = df[~df["medal_id"].isin(excluded)].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["account"] = df["account"].astype(str).str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    order_map = {name: i for i, name in enumerate(ordered_accounts)}
    df["_acc_order"] = df["account"].map(order_map).fillna(999)
    df = df.sort_values(["date", "_acc_order", "account", "medal_id"]).drop(columns=["_acc_order"])
    return df.reset_index(drop=True)


def load_medal_goals(path: Path) -> pd.DataFrame:
    base_cols = ["medal_id", "display_name", "goal_value"]
    cols = [*base_cols, "explanation"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, encoding="utf-8-sig")
    if not set(base_cols).issubset(df.columns):
        return pd.DataFrame(columns=cols)
    df = df.copy()
    if "explanation" not in df.columns:
        df["explanation"] = ""
    df["medal_id"] = df["medal_id"].astype(str).str.strip().str.lower()
    df["display_name"] = df["display_name"].fillna("").astype(str).str.strip()
    df["goal_value"] = pd.to_numeric(df["goal_value"], errors="coerce")
    df["explanation"] = df["explanation"].fillna("").astype(str).str.strip()
    df = df.dropna(subset=["medal_id", "display_name", "goal_value"]).copy()
    df = df[(df["medal_id"] != "") & (df["display_name"] != "")].copy()
    return df[cols].drop_duplicates(subset=["medal_id"]).sort_values(["display_name", "medal_id"]).reset_index(
        drop=True
    )
