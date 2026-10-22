from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from shared.xp_utils import total_xp_from_level_input

POKEDEX_ENTRY_SNAPSHOT_COLUMNS = ["date", "account", "entry_type", "region", "value"]
POKEDEX_ENTRY_CONFIG_COLUMNS = ["entry_type", "region", "max_value", "locked", "notes"]
DATA_INPUT_ACCOUNT_COLUMNS = ["input_type", "account", "enabled", "notes"]
DATA_INPUT_ACCOUNT_FILE_COLUMNS = ["account", "input_types", "notes"]
POKEMON_CATALOG_COLUMNS = [
    "dex_number",
    "name",
    "german_name",
    "region",
    "type_1",
    "type_2",
    "available_in_pogo",
    "location_restriction",
    "last_event",
    "last_event_date",
    "extra_info",
]
POKEMON_CATALOG_EDITABLE_COLUMNS = [
    "available_in_pogo",
    "location_restriction",
    "last_event",
    "last_event_date",
    "extra_info",
]
MANUAL_POKEMON_AVAILABILITY_COLUMNS = ["dex_number", "available", "notes"]
POKEDEX_SPECIES_ENTRY_COLUMNS = [
    "date",
    "account",
    "entry_type",
    "dex_number",
    "form",
    "registered",
    "can_evolve_now",
    "notes",
]
POKEDEX_CATEGORY_AVAILABILITY_COLUMNS = ["entry_type", "dex_number", "form", "available", "notes"]
POKEDEX_CATEGORY_AVAILABILITY_EDITABLE_COLUMNS = ["available", "notes"]
TRUE_TEXT_VALUES = {"1", "true", "yes", "y"}


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


def load_data_input_accounts(path: Path, valid_input_types: set[str] | None = None) -> pd.DataFrame:
    cols = DATA_INPUT_ACCOUNT_COLUMNS
    if not path.exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")
    if "account" not in df.columns:
        return pd.DataFrame(columns=cols)

    valid_types = {str(t).strip().lower() for t in (valid_input_types or set()) if str(t).strip()}
    df = df.copy()
    if "input_types" in df.columns:
        rows: list[dict[str, object]] = []
        for _, row in df.iterrows():
            account = str(row.get("account", "")).strip()
            notes = str(row.get("notes", "")).strip()
            raw_types = str(row.get("input_types", "")).strip().lower()
            normalized_types = raw_types.replace("|", ";").replace(",", ";")
            input_types = [t.strip() for t in normalized_types.split(";") if t.strip()]
            for input_type in input_types:
                if valid_types and input_type not in valid_types:
                    continue
                rows.append(
                    {
                        "input_type": input_type,
                        "account": account,
                        "enabled": True,
                        "notes": notes,
                    }
                )
        if not rows:
            return pd.DataFrame(columns=cols)
        out = pd.DataFrame(rows, columns=cols)
        out = out[(out["input_type"] != "") & (out["account"] != "")].copy()
        return out.drop_duplicates(subset=["input_type", "account"], keep="last").reset_index(drop=True)

    if "input_type" not in df.columns:
        return pd.DataFrame(columns=cols)

    for col in cols:
        if col not in df.columns:
            df[col] = "" if col != "enabled" else True
    df = df[cols].copy()
    df["input_type"] = df["input_type"].astype(str).str.strip().str.lower()
    df["account"] = df["account"].astype(str).str.strip()
    enabled_text = df["enabled"].fillna("").astype(str).str.strip().str.lower()
    df["enabled"] = enabled_text.isin({"1", "true", "yes", "y", "enabled"})
    df["notes"] = df["notes"].fillna("").astype(str).str.strip()
    df = df[(df["input_type"] != "") & (df["account"] != "")].copy()
    if valid_types:
        df = df[df["input_type"].isin(valid_types)].copy()
    return df.drop_duplicates(subset=["input_type", "account"], keep="last").reset_index(drop=True)


def save_data_input_account_types(
    path: Path,
    account_name: str,
    input_types: list[str],
    type_order: list[str] | None = None,
    notes: str = "",
) -> None:
    account = str(account_name).strip()
    if not account:
        return

    order = [str(t).strip().lower() for t in (type_order or []) if str(t).strip()]
    allowed = set(order)
    selected_seen: set[str] = set()
    selected: list[str] = []
    for raw_type in input_types:
        input_type = str(raw_type).strip().lower()
        if not input_type or input_type in selected_seen:
            continue
        if allowed and input_type not in allowed:
            continue
        selected_seen.add(input_type)
        selected.append(input_type)
    if order:
        selected = [t for t in order if t in set(selected)]

    if path.exists():
        try:
            raw = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            raw = pd.DataFrame(columns=DATA_INPUT_ACCOUNT_FILE_COLUMNS)
    else:
        raw = pd.DataFrame(columns=DATA_INPUT_ACCOUNT_FILE_COLUMNS)

    if "account" in raw.columns and "input_types" in raw.columns:
        out = raw.copy()
        for col in DATA_INPUT_ACCOUNT_FILE_COLUMNS:
            if col not in out.columns:
                out[col] = ""
        out = out[DATA_INPUT_ACCOUNT_FILE_COLUMNS].copy()
        out["account"] = out["account"].astype(str).str.strip()
        out["input_types"] = out["input_types"].fillna("").astype(str).str.strip()
        out["notes"] = out["notes"].fillna("").astype(str).str.strip()
    else:
        normalized = load_data_input_accounts(path, valid_input_types=set(order) if order else None)
        rows: list[dict[str, str]] = []
        if not normalized.empty:
            for existing_account, grp in normalized.groupby("account", sort=False):
                enabled_types = grp[grp["enabled"]]["input_type"].astype(str).str.strip().str.lower().tolist()
                if order:
                    enabled_types = [t for t in order if t in set(enabled_types)]
                row_notes = str(grp["notes"].dropna().astype(str).iloc[0]).strip() if "notes" in grp.columns and not grp.empty else ""
                rows.append(
                    {
                        "account": str(existing_account).strip(),
                        "input_types": ";".join(enabled_types),
                        "notes": row_notes,
                    }
                )
        out = pd.DataFrame(rows, columns=DATA_INPUT_ACCOUNT_FILE_COLUMNS)

    if out.empty:
        out = pd.DataFrame(columns=DATA_INPUT_ACCOUNT_FILE_COLUMNS)
    existing_notes = ""
    if "account" in out.columns and "notes" in out.columns:
        existing = out[out["account"].astype(str).str.strip().str.lower() == account.lower()]
        if not existing.empty:
            existing_notes = str(existing.iloc[-1].get("notes", "")).strip()
    row_notes = str(notes).strip() or existing_notes
    out = out[out["account"].astype(str).str.strip().str.lower() != account.lower()].copy()
    out = pd.concat(
        [
            out,
            pd.DataFrame(
                [
                    {
                        "account": account,
                        "input_types": ";".join(selected),
                        "notes": row_notes,
                    }
                ],
                columns=DATA_INPUT_ACCOUNT_FILE_COLUMNS,
            ),
        ],
        ignore_index=True,
    )
    out = out[DATA_INPUT_ACCOUNT_FILE_COLUMNS].copy()
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")


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


def load_xp_to_next_map(path: Path) -> dict[int, int]:
    if not path.exists():
        return {}
    curve = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    next_col = "XP to next Lvl."
    if not {"Level", next_col}.issubset(curve.columns):
        return {}
    curve["Level"] = to_int_series(curve["Level"])
    curve[next_col] = to_int_series(curve[next_col])
    curve = curve.dropna(subset=["Level", next_col]).copy()
    curve["Level"] = curve["Level"].astype(int)
    curve[next_col] = curve[next_col].astype(int)
    return dict(zip(curve["Level"], curve[next_col]))


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


def load_pokedex_entry_snapshots(
    path: Path,
    account_order: list[str] | None = None,
    valid_entry_types: set[str] | None = None,
    valid_regions: set[str] | None = None,
) -> pd.DataFrame:
    cols = POKEDEX_ENTRY_SNAPSHOT_COLUMNS
    if not path.exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")
    if not set(cols).issubset(df.columns):
        return pd.DataFrame(columns=cols)

    ordered_accounts = [str(a).strip() for a in (account_order or []) if str(a).strip()]
    allowed_types = {str(t).strip().lower() for t in (valid_entry_types or set()) if str(t).strip()}
    allowed_regions = {str(r).strip().lower() for r in (valid_regions or set()) if str(r).strip()}

    df = df[cols].copy()
    df["date"] = df["date"].replace("", pd.NA).ffill()
    df["account"] = df["account"].replace("", pd.NA).ffill()
    df = df[df["date"].astype(str).str.upper() != "YYYY-MM-DD"].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["account"] = df["account"].astype(str).str.strip()
    df["entry_type"] = df["entry_type"].astype(str).str.strip().str.lower()
    df["region"] = df["region"].astype(str).str.strip().str.lower()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "account", "entry_type", "region", "value"]).copy()
    df = df[(df["account"] != "") & (df["entry_type"] != "") & (df["region"] != "")].copy()
    if allowed_types:
        df = df[df["entry_type"].isin(allowed_types)].copy()
    if allowed_regions:
        df = df[df["region"].isin(allowed_regions)].copy()
    order_map = {name: i for i, name in enumerate(ordered_accounts)}
    df["_acc_order"] = df["account"].map(order_map).fillna(999)
    df = df.sort_values(["date", "_acc_order", "account", "entry_type", "region"]).drop(columns=["_acc_order"])
    return df.reset_index(drop=True)


def load_pokedex_entry_config(
    path: Path,
    valid_entry_types: set[str] | None = None,
    valid_regions: set[str] | None = None,
) -> pd.DataFrame:
    cols = POKEDEX_ENTRY_CONFIG_COLUMNS
    if not path.exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")
    if not {"entry_type", "region"}.issubset(df.columns):
        return pd.DataFrame(columns=cols)

    allowed_types = {str(t).strip().lower() for t in (valid_entry_types or set()) if str(t).strip()}
    allowed_regions = {str(r).strip().lower() for r in (valid_regions or set()) if str(r).strip()}

    df = df.copy()
    for col in cols:
        if col not in df.columns:
            df[col] = "" if col != "locked" else False
    df = df[cols].copy()
    df["entry_type"] = df["entry_type"].astype(str).str.strip().str.lower()
    df["region"] = df["region"].astype(str).str.strip().str.lower()
    df["max_value"] = pd.to_numeric(df["max_value"], errors="coerce")
    locked_text = df["locked"].fillna("").astype(str).str.strip().str.lower()
    df["locked"] = locked_text.isin({"1", "true", "yes", "y", "locked"})
    df["notes"] = df["notes"].fillna("").astype(str).str.strip()
    df = df[(df["entry_type"] != "") & (df["region"] != "")].copy()
    if allowed_types:
        df = df[df["entry_type"].isin(allowed_types)].copy()
    if allowed_regions:
        df = df[df["region"].isin(allowed_regions)].copy()
    return df.drop_duplicates(subset=["entry_type", "region"], keep="last").reset_index(drop=True)


def load_pokemon_catalog(path: Path) -> pd.DataFrame:
    cols = POKEMON_CATALOG_COLUMNS
    if not path.exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")
    if not {"dex_number", "name"}.issubset(df.columns):
        return pd.DataFrame(columns=cols)

    df = df.copy()
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    df = df[cols].copy()
    df["dex_number"] = pd.to_numeric(df["dex_number"], errors="coerce")
    text_cols = [c for c in cols if c != "dex_number"]
    for col in text_cols:
        df[col] = df[col].fillna("").astype(str).str.strip()
    df = df.dropna(subset=["dex_number"]).copy()
    df["dex_number"] = df["dex_number"].astype(int)
    df = df[(df["dex_number"] > 0) & (df["name"] != "")].copy()
    return df.drop_duplicates(subset=["dex_number"], keep="last").sort_values("dex_number").reset_index(drop=True)


def merge_pokemon_catalog(
    seeded_catalog: pd.DataFrame,
    existing_catalog: pd.DataFrame | None = None,
    preserve_editable: bool = True,
) -> pd.DataFrame:
    cols = POKEMON_CATALOG_COLUMNS
    seeded = seeded_catalog.copy()
    for col in cols:
        if col not in seeded.columns:
            seeded[col] = ""
    seeded = seeded[cols].copy()
    seeded["dex_number"] = pd.to_numeric(seeded["dex_number"], errors="coerce")
    seeded = seeded.dropna(subset=["dex_number"]).copy()
    seeded["dex_number"] = seeded["dex_number"].astype(int)
    seeded = seeded.drop_duplicates(subset=["dex_number"], keep="last")

    existing = existing_catalog.copy() if existing_catalog is not None else pd.DataFrame(columns=cols)
    if preserve_editable and not existing.empty and "dex_number" in existing.columns:
        existing = existing.copy()
        existing["dex_number"] = pd.to_numeric(existing["dex_number"], errors="coerce")
        existing = existing.dropna(subset=["dex_number"]).copy()
        existing["dex_number"] = existing["dex_number"].astype(int)
        existing = existing.drop_duplicates(subset=["dex_number"], keep="last").set_index("dex_number")
        for col in POKEMON_CATALOG_EDITABLE_COLUMNS:
            # Release status comes from the seed; manual overrides are applied later.
            if col == "available_in_pogo":
                continue
            if col not in existing.columns:
                continue
            preserved = existing[col].fillna("").astype(str).str.strip()
            preserved = preserved[preserved != ""]
            if preserved.empty:
                continue
            seeded[col] = seeded["dex_number"].map(preserved).fillna(seeded[col])

    for col in [c for c in cols if c != "dex_number"]:
        seeded[col] = seeded[col].fillna("").astype(str).str.strip()
    return seeded[cols].sort_values("dex_number").reset_index(drop=True)


def load_manual_pokemon_availability_frame(path: Path) -> pd.DataFrame:
    cols = MANUAL_POKEMON_AVAILABILITY_COLUMNS
    empty = pd.DataFrame(columns=cols)
    if not path.exists():
        return empty

    df = pd.read_csv(path, encoding="utf-8-sig")
    if not {"dex_number", "available"}.issubset(df.columns):
        return empty

    df = df.copy()
    if "notes" not in df.columns:
        df["notes"] = ""
    df = df[cols].copy()
    df["dex_number"] = pd.to_numeric(df["dex_number"], errors="coerce")
    df["available"] = df["available"].fillna("").astype(str).str.strip().str.casefold()
    df["notes"] = df["notes"].fillna("").astype(str).str.strip()
    df = df[df["dex_number"].notna() & (df["dex_number"] > 0) & df["available"].isin(["yes", "no"])].copy()
    df["dex_number"] = df["dex_number"].astype(int)
    return df.drop_duplicates(subset=["dex_number"], keep="last").sort_values("dex_number").reset_index(drop=True)


def load_manual_pokemon_availability(path: Path) -> dict[int, str]:
    frame = load_manual_pokemon_availability_frame(path)
    return {int(row.dex_number): str(row.available) for row in frame.itertuples(index=False)}


def _manual_availability_dex(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    numeric = float(number)
    if numeric <= 0:
        return None
    return int(numeric)


def _manual_availability_note(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def apply_manual_pokemon_availability(catalog_df: pd.DataFrame, overrides: dict[int, str]) -> pd.DataFrame:
    catalog = catalog_df.copy()
    if not overrides or "dex_number" not in catalog.columns:
        return catalog
    if "available_in_pogo" not in catalog.columns:
        catalog["available_in_pogo"] = ""

    dex = pd.to_numeric(catalog["dex_number"], errors="coerce")
    valid = dex.notna()
    dex_int = dex.where(valid, 0).astype(int)
    matched = valid & dex_int.isin(overrides)
    catalog.loc[matched, "available_in_pogo"] = dex_int.loc[matched].map(overrides)
    return catalog


def load_pokemon_catalog_with_availability(catalog_path: Path, override_path: Path) -> pd.DataFrame:
    return apply_manual_pokemon_availability(
        load_pokemon_catalog(catalog_path),
        load_manual_pokemon_availability(override_path),
    )


def save_manual_pokemon_availability(path: Path, edits: list[dict[str, object]]) -> int:
    frame = load_manual_pokemon_availability_frame(path)
    rows: dict[int, tuple[str, str]] = {
        int(row.dex_number): (str(row.available), str(row.notes)) for row in frame.itertuples(index=False)
    }
    for edit in edits:
        dex = _manual_availability_dex(edit.get("dex_number"))
        if dex is None or "available" not in edit:
            continue
        available = _manual_availability_note(edit.get("available")).casefold()
        if available in {"yes", "in go"}:
            flag = "yes"
        elif available in {"no", "not in go"}:
            flag = "no"
        elif available in {"catalog", "", "follow catalog"}:
            rows.pop(dex, None)
            continue
        else:
            continue
        if "notes" in edit:
            notes = _manual_availability_note(edit.get("notes"))
        else:
            notes = rows[dex][1] if dex in rows else ""
        rows[dex] = (flag, notes)

    out = pd.DataFrame(
        [
            {"dex_number": dex, "available": rows[dex][0], "notes": rows[dex][1]}
            for dex in sorted(rows)
        ],
        columns=MANUAL_POKEMON_AVAILABILITY_COLUMNS,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    return int(len(out))


def parse_bool_text(value: object) -> bool:
    return str(value).strip().lower() in TRUE_TEXT_VALUES


def _dedupe_availability(df: pd.DataFrame) -> pd.DataFrame:
    keyed = df.copy()
    if "form" not in keyed.columns:
        keyed["form"] = ""
    keyed["form"] = keyed["form"].fillna("").astype(str).str.strip()
    keyed["_form_key"] = keyed["form"].str.casefold()
    keyed = keyed.drop_duplicates(subset=["entry_type", "dex_number", "_form_key"], keep="last")
    return keyed.drop(columns=["_form_key"])


def _availability_match_key(df: pd.DataFrame) -> pd.Series:
    form_key = df["form"].fillna("").astype(str).str.strip().str.casefold()
    return df["entry_type"].astype(str) + "\x1f" + df["dex_number"].astype(str) + "\x1f" + form_key


def drop_superseded_blank_mega_forms(availability: pd.DataFrame) -> pd.DataFrame:
    """Drop blank mega rows when that dex also has a non-blank mega form.

    Shiny, shadow, and gmax rows are left alone, including blank forms.
    """
    if availability.empty or not {"entry_type", "dex_number"}.issubset(availability.columns):
        return availability
    rows = availability.copy()
    if "form" not in rows.columns:
        rows["form"] = ""
    form = rows["form"].fillna("").astype(str).str.strip()
    entry = rows["entry_type"].astype(str).str.strip().str.lower()
    dex = pd.to_numeric(rows["dex_number"], errors="coerce")
    formed = (entry == "mega") & (form != "") & dex.notna()
    if not bool(formed.any()):
        return rows
    formed_dexes = set(dex.loc[formed].astype(int).tolist())
    blank = (entry == "mega") & (form == "") & dex.notna()
    if not bool(blank.any()):
        return rows
    blank_dex = dex.loc[blank].astype(int)
    drop_index = blank_dex[blank_dex.isin(formed_dexes)].index
    if len(drop_index) == 0:
        return rows
    return rows.drop(index=drop_index)


def load_pokedex_species_entries(
    path: Path,
    valid_entry_types: set[str] | None = None,
) -> pd.DataFrame:
    cols = POKEDEX_SPECIES_ENTRY_COLUMNS
    if not path.exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")
    if not {"date", "account", "entry_type", "dex_number"}.issubset(df.columns):
        return pd.DataFrame(columns=cols)

    df = df.copy()
    for col in cols:
        if col not in df.columns:
            if col in {"registered", "can_evolve_now"}:
                df[col] = False
            else:
                df[col] = ""
    df = df[cols].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["account"] = df["account"].astype(str).str.strip()
    df["entry_type"] = df["entry_type"].astype(str).str.strip().str.lower()
    df["dex_number"] = pd.to_numeric(df["dex_number"], errors="coerce")
    df["registered"] = df["registered"].map(parse_bool_text)
    df["can_evolve_now"] = df["can_evolve_now"].map(parse_bool_text)
    df["form"] = df["form"].fillna("").astype(str).str.strip()
    df["notes"] = df["notes"].fillna("").astype(str).str.strip()
    df = df.dropna(subset=["date", "account", "entry_type", "dex_number"]).copy()
    df = df[(df["account"] != "") & (df["entry_type"] != "")].copy()
    df["dex_number"] = df["dex_number"].astype(int)
    df = df[df["dex_number"] > 0].copy()
    allowed_types = {str(t).strip().lower() for t in (valid_entry_types or set()) if str(t).strip()}
    if allowed_types:
        df = df[df["entry_type"].isin(allowed_types)].copy()
    return df.sort_values(["date", "account", "entry_type", "dex_number", "form"]).reset_index(drop=True)


def load_pokedex_category_availability(
    path: Path,
    valid_entry_types: set[str] | None = None,
) -> pd.DataFrame:
    cols = POKEDEX_CATEGORY_AVAILABILITY_COLUMNS
    if not path.exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")
    if not {"entry_type", "dex_number"}.issubset(df.columns):
        return pd.DataFrame(columns=cols)

    df = df.copy()
    for col in cols:
        if col not in df.columns:
            df[col] = "" if col != "available" else False
    df = df[cols].copy()
    df["entry_type"] = df["entry_type"].astype(str).str.strip().str.lower()
    df["dex_number"] = pd.to_numeric(df["dex_number"], errors="coerce")
    df["form"] = df["form"].fillna("").astype(str).str.strip()
    df["available"] = df["available"].map(parse_bool_text)
    df["notes"] = df["notes"].fillna("").astype(str).str.strip()
    df = df.dropna(subset=["entry_type", "dex_number"]).copy()
    df = df[df["entry_type"] != ""].copy()
    df["dex_number"] = df["dex_number"].astype(int)
    df = df[df["dex_number"] > 0].copy()
    allowed_types = {str(t).strip().lower() for t in (valid_entry_types or set()) if str(t).strip()}
    if allowed_types:
        df = df[df["entry_type"].isin(allowed_types)].copy()
    return _dedupe_availability(df).sort_values(["entry_type", "dex_number", "form"]).reset_index(drop=True)


def _normalize_availability_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cols = POKEDEX_CATEGORY_AVAILABILITY_COLUMNS
    prepared = frame.copy()
    for col in cols:
        if col not in prepared.columns:
            prepared[col] = "" if col != "available" else False
    prepared = prepared[cols].copy()
    prepared["entry_type"] = prepared["entry_type"].astype(str).str.strip().str.lower()
    prepared["dex_number"] = pd.to_numeric(prepared["dex_number"], errors="coerce")
    prepared = prepared.dropna(subset=["entry_type", "dex_number"]).copy()
    prepared["dex_number"] = prepared["dex_number"].astype(int)
    prepared["form"] = prepared["form"].fillna("").astype(str).str.strip()
    prepared["available"] = prepared["available"].map(lambda value: value if isinstance(value, bool) else parse_bool_text(value))
    prepared["notes"] = prepared["notes"].fillna("").astype(str).str.strip()
    return _dedupe_availability(prepared)


def merge_pokedex_category_availability(
    seeded_availability: pd.DataFrame,
    existing_availability: pd.DataFrame | None = None,
    preserve_editable: bool = True,
) -> pd.DataFrame:
    cols = POKEDEX_CATEGORY_AVAILABILITY_COLUMNS
    seeded = _normalize_availability_frame(seeded_availability)

    existing = existing_availability.copy() if existing_availability is not None else pd.DataFrame(columns=cols)
    if preserve_editable and not existing.empty and {"entry_type", "dex_number"}.issubset(existing.columns):
        existing = _normalize_availability_frame(existing)
        existing["_key"] = _availability_match_key(existing)
        seeded["_key"] = _availability_match_key(seeded)
        existing_indexed = existing.set_index("_key")
        for col in POKEDEX_CATEGORY_AVAILABILITY_EDITABLE_COLUMNS:
            if col not in existing_indexed.columns:
                continue
            if col == "available":
                preserved = existing_indexed[col]
                mapped = seeded["_key"].map(preserved)
                seeded[col] = mapped.where(mapped.notna(), seeded[col]).astype(bool)
            else:
                preserved = existing_indexed[col].fillna("").astype(str).str.strip()
                preserved = preserved[preserved != ""]
                if not preserved.empty:
                    seeded[col] = seeded["_key"].map(preserved).fillna(seeded[col])
        seeded = seeded.drop(columns=["_key"])

    seeded = drop_superseded_blank_mega_forms(seeded)
    seeded["notes"] = seeded["notes"].fillna("").astype(str).str.strip()
    seeded["available"] = seeded["available"].map(lambda value: value if isinstance(value, bool) else parse_bool_text(value))
    return seeded[cols].sort_values(["entry_type", "dex_number", "form"]).reset_index(drop=True)
