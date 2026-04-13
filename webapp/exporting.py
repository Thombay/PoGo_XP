from __future__ import annotations

import io
import re
import subprocess
import sys
from html import escape
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd
import plotly.graph_objects as go


def _format_export_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    for col in out.columns:
        col_l = str(col).lower()
        if "date" in col_l:
            dt = pd.to_datetime(out[col], errors="coerce")
            out[col] = dt.dt.strftime("%Y-%m-%d").where(dt.notna(), out[col].astype(str))
            continue
        vals = pd.to_numeric(out[col], errors="coerce")
        is_pct_goal = col_l == "pct_goal"
        is_baseline_pct = "pct_vs_baseline" in col_l or col_l.startswith("% vs baseline")
        is_baseline_delta = "delta_vs_baseline" in col_l or "delta vs baseline" in col_l
        if is_pct_goal or is_baseline_pct or is_baseline_delta:
            if is_pct_goal:
                out[col] = vals.map(lambda v: "--" if pd.isna(v) else f"{float(v):.1f}")
            elif is_baseline_pct:
                out[col] = vals.map(lambda v: "--" if pd.isna(v) else f"{float(v):+,.1%}")
            else:
                out[col] = vals.map(lambda v: "--" if pd.isna(v) else f"{int(round(float(v))):+,}")
            continue

        is_numeric_col = pd.api.types.is_numeric_dtype(out[col])
        if not is_numeric_col:
            non_empty = int(out[col].notna().sum())
            numeric_like = int(vals.notna().sum())
            is_numeric_col = non_empty > 0 and (numeric_like / non_empty) >= 0.6
        if is_numeric_col:
            out[col] = vals.map(lambda v: "--" if pd.isna(v) else f"{int(round(float(v))):,}")
    return out


def _export_value_indicator_class(column_name: object, raw_value: object) -> str:
    col_l = str(column_name).strip().lower()
    num = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
    if "delta_vs_baseline" in col_l or "delta vs baseline" in col_l or "pct_vs_baseline" in col_l or "% vs baseline" in col_l:
        if pd.isna(num):
            return ""
        if float(num) > 0:
            return "cell-pos"
        if float(num) < 0:
            return "cell-neg"
        return "cell-neutral"
    return ""


def _export_delta_class(delta_text: object) -> str:
    txt = str(delta_text or "").strip()
    if not txt:
        return "delta-neutral"
    if "↑" in txt or re.search(r"(^|[^0-9])\+", txt):
        return "delta-pos"
    if "↓" in txt or re.search(r"(^|[^0-9])-", txt):
        return "delta-neg"
    return "delta-neutral"


def _df_section_html(title: str, df: pd.DataFrame) -> str:
    if df.empty:
        return f"<section><h2>{escape(title)}</h2><p>No data.</p></section>"
    raw = df.reset_index(drop=True).copy()
    out = _format_export_df(raw)
    cols = [str(c) for c in out.columns]
    header_html = "".join([f"<th>{escape(c)}</th>" for c in cols])
    row_html_parts: list[str] = []
    for i in range(len(out)):
        cells: list[str] = []
        for col in cols:
            display_val = out.iloc[i][col] if col in out.columns else "--"
            raw_val = raw.iloc[i][col] if col in raw.columns else display_val
            cell_cls = _export_value_indicator_class(col, raw_val)
            cls_attr = f" class='{cell_cls}'" if cell_cls else ""
            text = "--" if pd.isna(display_val) else str(display_val)
            cells.append(f"<td{cls_attr}>{escape(text)}</td>")
        row_html_parts.append(f"<tr>{''.join(cells)}</tr>")
    table_html = (
        "<table class='report-table report-table-enhanced'>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(row_html_parts)}</tbody>"
        "</table>"
    )
    return f"<section><h2>{escape(title)}</h2>{table_html}</section>"


def _export_theme(mode: str) -> dict[str, object]:
    m = str(mode).strip().lower()
    if m == "light":
        return {
            "name": "Light",
            "template": "plotly_white",
            "paper_bg": "#ffffff",
            "plot_bg": "#ffffff",
            "font": "#0f172a",
            "grid": "rgba(15,23,42,0.12)",
            "line": "rgba(15,23,42,0.35)",
            "body_bg": "#f8fafc",
            "muted": "#475569",
            "card_bg": "#ffffff",
            "border": "#d0d7de",
            "table_bg": "#ffffff",
            "table_head": "#eef2f7",
            "colorway": ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#17becf", "#bcbd22", "#8c564b"],
            "max_width": "1400px",
            "base_font_size": "14px",
        }
    if m == "whatsapp":
        return {
            "name": "WhatsApp",
            "template": "plotly_white",
            "paper_bg": "#ffffff",
            "plot_bg": "#ffffff",
            "font": "#0b1f16",
            "grid": "rgba(11,31,22,0.10)",
            "line": "rgba(11,31,22,0.25)",
            "body_bg": "#ecfdf5",
            "muted": "#36524a",
            "card_bg": "#ffffff",
            "border": "#a7f3d0",
            "table_bg": "#ffffff",
            "table_head": "#d1fae5",
            "colorway": ["#0ea5a4", "#1d4ed8", "#16a34a", "#f59e0b", "#e11d48", "#7c3aed", "#0f766e", "#f97316"],
            "max_width": "980px",
            "base_font_size": "15px",
        }
    if m == "smartphone":
        return {
            "name": "Smartphone",
            "template": "plotly_white",
            "paper_bg": "#ffffff",
            "plot_bg": "#ffffff",
            "font": "#0f172a",
            "grid": "rgba(15,23,42,0.12)",
            "line": "rgba(15,23,42,0.30)",
            "body_bg": "#f8fafc",
            "muted": "#475569",
            "card_bg": "#ffffff",
            "border": "#d0d7de",
            "table_bg": "#ffffff",
            "table_head": "#eef2f7",
            "colorway": ["#0ea5a4", "#1d4ed8", "#16a34a", "#f59e0b", "#e11d48", "#7c3aed", "#0f766e", "#f97316"],
            "max_width": "430px",
            "base_font_size": "16px",
        }
    return {
        "name": "Dark",
        "template": "plotly_dark",
        "paper_bg": "#0b1220",
        "plot_bg": "#0f172a",
        "font": "#e5e7eb",
        "grid": "rgba(148,163,184,0.15)",
        "line": "rgba(148,163,184,0.35)",
        "body_bg": "#0b1220",
        "muted": "#b8c0cc",
        "card_bg": "#111827",
        "border": "#1f2937",
        "table_bg": "#0f172a",
        "table_head": "#1f2937",
        "colorway": ["#4fa3ff", "#22c55e", "#f59e0b", "#ef4444", "#a78bfa", "#14b8a6", "#f97316", "#eab308"],
        "max_width": "1400px",
        "base_font_size": "14px",
    }


def _style_export_figure(fig: go.Figure, mode: str) -> None:
    theme = _export_theme(mode)
    palette = [str(c) for c in theme["colorway"]]
    fig.update_layout(
        template=str(theme["template"]),
        paper_bgcolor=str(theme["paper_bg"]),
        plot_bgcolor=str(theme["plot_bg"]),
        font=dict(color=str(theme["font"])),
        colorway=list(theme["colorway"]),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(
        gridcolor=str(theme["grid"]),
        zerolinecolor=str(theme["grid"]),
        linecolor=str(theme["line"]),
        automargin=True,
    )

    name_to_color: dict[str, str] = {}
    next_idx = 0
    for tr in fig.data:
        trace_name = str(getattr(tr, "name", "")).strip() or f"trace_{next_idx}"
        if trace_name not in name_to_color:
            name_to_color[trace_name] = palette[next_idx % len(palette)]
            next_idx += 1
        color = name_to_color[trace_name]
        trace_type = str(getattr(tr, "type", ""))
        if trace_type in {"scatter", "scattergl"}:
            tr.update(
                line=dict(color=color),
                marker=dict(color=color),
            )
        elif trace_type == "bar":
            tr.update(marker=dict(color=color))
    fig.update_yaxes(
        gridcolor=str(theme["grid"]),
        zerolinecolor=str(theme["grid"]),
        linecolor=str(theme["line"]),
        automargin=True,
    )


def _figure_to_png_via_subprocess(fig: go.Figure, width: int, height: int, scale: int = 2) -> tuple[bytes | None, str | None]:
    script = r"""
import json
import sys
import plotly.graph_objects as go

w = int(sys.argv[1])
h = int(sys.argv[2])
s = int(sys.argv[3])
raw = sys.stdin.buffer.read().decode("utf-8")
fig = go.Figure(json.loads(raw))
out = fig.to_image(format="png", width=w, height=h, scale=s)
sys.stdout.buffer.write(out)
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(int(width)), str(int(height)), str(int(scale))],
            input=fig.to_json().encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=120,
        )
    except Exception as e:
        return None, str(e)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
        return None, err or f"subprocess exited with code {proc.returncode}"
    return bytes(proc.stdout or b""), None


def build_dashboard_export_html(
    dashboard_title: str,
    selected_group: str,
    export_mode: str,
    window_days: int,
    dashboard_window_options: Sequence[int],
    build_payload_for_window: Callable[[int], dict[str, object]],
    sort_legend_by_latest_y: Callable[[go.Figure | None], None],
) -> str:
    def _render_payload_block(payload: dict[str, object], include_js: bool, mode: str) -> tuple[str, bool]:
        metric_cards = payload["metric_cards"]
        ordered_blocks = payload.get("ordered_blocks") or []
        chart_items = payload["chart_items"]
        sections_data = payload["sections"]

        def _normalize_card(card: object) -> dict[str, str]:
            if isinstance(card, dict):
                return {
                    "label": str(card.get("label", "")),
                    "value": str(card.get("value", "")),
                    "detail": str(card.get("detail", "")),
                    "winner": str(card.get("winner", "")),
                    "winner_color": str(card.get("winner_color", "")),
                }
            if isinstance(card, (tuple, list)) and len(card) >= 3:
                return {
                    "label": str(card[0]),
                    "value": str(card[1]),
                    "detail": str(card[2]),
                    "winner": "",
                    "winner_color": "",
                }
            return {"label": str(card), "value": "", "detail": "", "winner": "", "winner_color": ""}

        def _render_cards_html(cards: list[object], title: str | None = None) -> str:
            cards_html_parts: list[str] = []
            for raw_card in cards:
                card = _normalize_card(raw_card)
                detail = card["detail"]
                delta_cls = _export_delta_class(detail)
                winner_html = ""
                if card["winner"].strip():
                    style_attr = f" style='color:{escape(card['winner_color'])};'" if card["winner_color"].strip() else ""
                    winner_html = f"<div class='metric-winner'{style_attr}>{escape(card['winner'])}</div>"
                detail_html = f"<div class='metric-delta {delta_cls}'>{escape(detail)}</div>" if detail.strip() else ""
                cards_html_parts.append(
                    (
                        "<div class='metric-card'>"
                        f"<div class='metric-label'>{escape(card['label'])}</div>"
                        f"<div class='metric-value'>{escape(card['value'])}</div>"
                        f"{winner_html}"
                        f"{detail_html}"
                        "</div>"
                    )
                )
            cards_html = f"<div class='metrics metric-group-grid'>{''.join(cards_html_parts)}</div>"
            if title:
                return f"<section class='metric-group'><h2>{escape(title)}</h2>{cards_html}</section>"
            return cards_html

        content_blocks: list[str] = []
        include_plotly = include_js
        if ordered_blocks:
            for block in ordered_blocks:
                block_type = str(block.get("type", "")).strip().lower() if isinstance(block, dict) else ""
                if block_type == "card_group":
                    content_blocks.append(_render_cards_html(list(block.get("cards", [])), title=str(block.get("title", ""))))
                    continue
                if block_type == "chart":
                    chart_title = str(block.get("title", ""))
                    fig = block.get("figure")
                    if fig is None:
                        continue
                    sort_legend_by_latest_y(fig)
                    _style_export_figure(fig, mode)
                    content_blocks.append(f"<section><h2>{escape(chart_title)}</h2>")
                    content_blocks.append(
                        fig.to_html(
                            full_html=False,
                            include_plotlyjs="inline" if include_plotly else False,
                            config={"displaylogo": False},
                        )
                    )
                    content_blocks.append("</section>")
                    include_plotly = False
        else:
            for chart_title, fig in chart_items:
                if fig is None:
                    continue
                sort_legend_by_latest_y(fig)
                _style_export_figure(fig, mode)
                content_blocks.append(f"<section><h2>{escape(chart_title)}</h2>")
                content_blocks.append(
                    fig.to_html(
                        full_html=False,
                        include_plotlyjs="inline" if include_plotly else False,
                        config={"displaylogo": False},
                    )
                )
                content_blocks.append("</section>")
                include_plotly = False

        cards_html = _render_cards_html(list(metric_cards))
        sections_html = "".join([_df_section_html(str(title), df) for (title, df) in sections_data])
        block_html = f"{cards_html}{''.join(content_blocks)}{sections_html}"
        return block_html, include_plotly

    layout_theme = _export_theme(export_mode)
    dark_theme = _export_theme("dark")
    light_theme = _export_theme("light")
    default_theme_mode = "dark" if str(export_mode).strip().lower() == "dark" else "light"
    default_theme_label = "Dark" if default_theme_mode == "dark" else "Light"

    default_window = int(window_days)
    export_windows = [int(w) for w in dashboard_window_options]
    if default_window not in export_windows:
        export_windows = sorted(set(export_windows + [default_window]))

    payloads_by_window: dict[int, dict[str, object]] = {}
    for w in export_windows:
        payloads_by_window[w] = build_payload_for_window(int(w))

    base_payload = payloads_by_window.get(default_window) or payloads_by_window[export_windows[0]]
    accounts_text = str(base_payload["accounts_text"])
    generated_at = str(base_payload["generated_at"])

    include_js = True
    window_panes: list[str] = []
    for w in export_windows:
        for theme_mode in ["dark", "light"]:
            block_html, include_js = _render_payload_block(payloads_by_window[w], include_js=include_js, mode=theme_mode)
            display_mode = "block" if int(w) == int(default_window) and theme_mode == default_theme_mode else "none"
            window_panes.append(
                (
                    f"<div class='window-pane theme-pane' "
                    f"id='window-pane-{int(w)}-{theme_mode}' "
                    f"data-window='{int(w)}' data-theme='{theme_mode}' "
                    f"style='display:{display_mode};'>{block_html}</div>"
                )
            )

    window_buttons = "".join(
        [
            (
                f"<button type='button' class='window-btn' id='window-btn-{int(w)}' "
                f"onclick='setWindow({int(w)})'>{int(w)}d</button>"
            )
            for w in export_windows
        ]
    )
    theme_buttons = "".join(
        [
            "<button type='button' class='theme-btn' id='theme-btn-dark' onclick=\"setTheme('dark')\">Dark</button>",
            "<button type='button' class='theme-btn' id='theme-btn-light' onclick=\"setTheme('light')\">Light</button>",
        ]
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{escape(dashboard_title)} - {escape(selected_group)}</title>
  <style>
    :root {{
      --body-bg: {dark_theme["body_bg"]};
      --font: {dark_theme["font"]};
      --muted: {dark_theme["muted"]};
      --card-bg: {dark_theme["card_bg"]};
      --border: {dark_theme["border"]};
      --table-bg: {dark_theme["table_bg"]};
      --table-head: {dark_theme["table_head"]};
      --line: {dark_theme["line"]};
    }}
    body.theme-dark {{
      --body-bg: {dark_theme["body_bg"]};
      --font: {dark_theme["font"]};
      --muted: {dark_theme["muted"]};
      --card-bg: {dark_theme["card_bg"]};
      --border: {dark_theme["border"]};
      --table-bg: {dark_theme["table_bg"]};
      --table-head: {dark_theme["table_head"]};
      --line: {dark_theme["line"]};
    }}
    body.theme-light {{
      --body-bg: {light_theme["body_bg"]};
      --font: {light_theme["font"]};
      --muted: {light_theme["muted"]};
      --card-bg: {light_theme["card_bg"]};
      --border: {light_theme["border"]};
      --table-bg: {light_theme["table_bg"]};
      --table-head: {light_theme["table_head"]};
      --line: {light_theme["line"]};
    }}
    body {{ background:var(--body-bg); color:var(--font); font-family:Segoe UI, Arial, sans-serif; margin:20px; font-size:{layout_theme["base_font_size"]}; }}
    .container {{ max-width:{layout_theme["max_width"]}; margin:0 auto; }}
    h1, h2 {{ margin:0 0 10px 0; }}
    p {{ color:var(--muted); }}
    .meta {{ margin-bottom:12px; }}
    .switch-row {{ display:flex; align-items:center; gap:10px; margin-bottom:14px; }}
    .switch-label {{ color:var(--muted); font-size:13px; }}
    .window-switch, .theme-switch {{ display:flex; gap:8px; }}
    .window-btn, .theme-btn {{ background:var(--card-bg); color:var(--font); border:1px solid var(--border); border-radius:8px; padding:4px 10px; cursor:pointer; font-size:13px; }}
    .window-btn.active, .theme-btn.active {{ background:var(--table-head); border-color:var(--line); font-weight:600; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(180px,1fr)); gap:12px; margin:14px 0 18px 0; }}
    .metric-group {{ margin-bottom:18px; }}
    .metric-group-grid {{ margin-top:10px; }}
    .window-pane {{ width:100%; }}
    .metric-card {{ background:var(--card-bg); border:1px solid var(--border); border-radius:10px; padding:12px; }}
    .metric-label {{ color:var(--muted); font-size:12px; }}
    .metric-value {{ font-size:30px; margin:8px 0 6px 0; }}
    .metric-winner {{ font-size:13px; font-weight:700; min-height:16px; margin-bottom:4px; }}
    .metric-delta {{ color:var(--font); opacity:0.9; font-size:13px; min-height:16px; }}
    .metric-delta.delta-pos {{ color:#22c55e; font-weight:600; }}
    .metric-delta.delta-neg {{ color:#ef4444; font-weight:600; }}
    .metric-delta.delta-neutral {{ color:var(--font); opacity:0.9; }}
    section {{ margin-bottom:18px; }}
    .report-table {{ width:100%; border-collapse:collapse; background:var(--table-bg); border:1px solid var(--border); }}
    .report-table th, .report-table td {{ border:1px solid var(--border); padding:6px 8px; text-align:left; }}
    .report-table th {{ background:var(--table-head); }}
    .report-table td.cell-pos {{ background:rgba(34, 197, 94, 0.18); color:var(--font); font-weight:600; }}
    .report-table td.cell-neg {{ background:rgba(239, 68, 68, 0.18); color:var(--font); font-weight:600; }}
    .report-table td.cell-neutral {{ background:rgba(148, 163, 184, 0.10); color:var(--font); }}
    @media (max-width: 1000px) {{
      .metrics {{ grid-template-columns:repeat(2,minmax(160px,1fr)); }}
    }}
    @media (max-width: 520px) {{
      body {{ margin:10px; }}
      .metrics {{ grid-template-columns:1fr; }}
      .window-switch, .theme-switch {{ flex-wrap:wrap; }}
    }}
  </style>
</head>
<body class="theme-{default_theme_mode}">
  <div class="container">
  <h1>{escape(dashboard_title)}</h1>
  <div class="meta">
    <p><strong>Group:</strong> {escape(selected_group)}</p>
    <p><strong>Window:</strong> <span id="window-value">{int(default_window)}d</span></p>
    <p><strong>Theme:</strong> <span id="theme-value">{default_theme_label}</span></p>
    <p><strong>Accounts:</strong> {escape(accounts_text)}</p>
    <p><strong>Generated:</strong> {escape(generated_at)}</p>
  </div>
  <div class="switch-row">
    <span class="switch-label"><strong>Window:</strong></span>
    <div class="window-switch">{window_buttons}</div>
  </div>
  <div class="switch-row">
    <span class="switch-label"><strong>Theme:</strong></span>
    <div class="theme-switch">{theme_buttons}</div>
  </div>
  {''.join(window_panes)}
  </div>
  <script>
    const exportWindows = [{", ".join(str(int(w)) for w in export_windows)}];
    const exportThemes = ["dark", "light"];
    let activeWindow = {int(default_window)};
    let activeTheme = "{default_theme_mode}";
    function paneId(windowDays, themeMode) {{
      return `window-pane-${{windowDays}}-${{themeMode}}`;
    }}
    function resizePlotsInPane(windowDays, themeMode) {{
      const pane = document.getElementById(paneId(windowDays, themeMode));
      if (!pane || !window.Plotly || !window.Plotly.Plots) return;
      const plotEls = pane.querySelectorAll(".js-plotly-plot, .plotly-graph-div");
      plotEls.forEach((el) => {{
        try {{
          window.Plotly.Plots.resize(el);
        }} catch (_err) {{
        }}
      }});
    }}
    function applyThemeClass(themeMode) {{
      document.body.classList.toggle("theme-dark", themeMode === "dark");
      document.body.classList.toggle("theme-light", themeMode === "light");
    }}
    function renderState() {{
      exportWindows.forEach((w) => {{
        const winBtn = document.getElementById(`window-btn-${{w}}`);
        if (winBtn) winBtn.classList.toggle("active", Number(w) === Number(activeWindow));
        exportThemes.forEach((t) => {{
          const pane = document.getElementById(paneId(w, t));
          const active = Number(w) === Number(activeWindow) && t === activeTheme;
          if (pane) pane.style.display = active ? "block" : "none";
        }});
      }});
      exportThemes.forEach((t) => {{
        const themeBtn = document.getElementById(`theme-btn-${{t}}`);
        if (themeBtn) themeBtn.classList.toggle("active", t === activeTheme);
      }});
      const windowLabel = document.getElementById("window-value");
      if (windowLabel) windowLabel.textContent = `${{activeWindow}}d`;
      const themeLabel = document.getElementById("theme-value");
      if (themeLabel) themeLabel.textContent = activeTheme === "dark" ? "Dark" : "Light";
      if (window.requestAnimationFrame) {{
        window.requestAnimationFrame(() => resizePlotsInPane(activeWindow, activeTheme));
      }} else {{
        resizePlotsInPane(activeWindow, activeTheme);
      }}
      window.setTimeout(() => resizePlotsInPane(activeWindow, activeTheme), 60);
    }}
    function setWindow(windowDays) {{
      activeWindow = Number(windowDays);
      renderState();
    }}
    function setTheme(themeMode) {{
      activeTheme = themeMode === "dark" ? "dark" : "light";
      applyThemeClass(activeTheme);
      renderState();
    }}
    applyThemeClass(activeTheme);
    renderState();
  </script>
</body>
</html>
"""
    return html


def build_dashboard_export_png(
    dashboard_title: str,
    selected_group: str,
    export_mode: str,
    window_days: int,
    build_payload_for_window: Callable[[int], dict[str, object]],
    sort_legend_by_latest_y: Callable[[go.Figure | None], None],
) -> tuple[bytes | None, str | None]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None, "Picture export requires `Pillow`. Install dependencies and retry."

    payload = build_payload_for_window(int(window_days))
    theme = _export_theme(export_mode)
    chart_items: list[tuple[str, go.Figure | None]] = payload["chart_items"]
    sections_data: list[tuple[str, pd.DataFrame]] = payload["sections"]
    metric_cards: list[tuple[str, str, str]] = payload["metric_cards"]
    ordered_blocks = payload.get("ordered_blocks") or []
    accounts_text = str(payload["accounts_text"])
    generated_at = str(payload["generated_at"])

    width = 900 if str(export_mode).strip().lower() == "smartphone" else 1800
    pad = 20
    bg = str(theme["body_bg"])
    fg = str(theme["font"])
    card_bg = str(theme["card_bg"])
    border = str(theme["border"])
    muted = str(theme["muted"])

    def _load_font(candidates: list[str], size: int) -> "ImageFont.ImageFont":
        for fp in candidates:
            try:
                p = Path(fp)
                if p.exists():
                    return ImageFont.truetype(str(p), size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    font_title = _load_font(["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"], 36)
    font_section = _load_font(["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"], 24)
    font_body = _load_font(["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"], 18)
    font_metric_value = _load_font(["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"], 28)
    font_metric_delta = _load_font(["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"], 15)
    font_mono = _load_font(["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf"], 16)

    def _line_height(font_obj: "ImageFont.ImageFont") -> int:
        try:
            box = font_obj.getbbox("Ag")
            return max(16, (box[3] - box[1]) + 6)
        except Exception:
            return 22

    def text_block(
        title: str,
        lines: list[str],
        title_color: str | None = None,
        title_font: "ImageFont.ImageFont | None" = None,
        body_font: "ImageFont.ImageFont | None" = None,
    ) -> "Image.Image":
        tcol = title_color or fg
        tf = title_font or font_section
        bf = body_font or font_body
        title_h = _line_height(tf)
        line_h = _line_height(bf)
        body_rows = len(lines)
        block_h = pad * 2 + title_h + (body_rows * line_h if body_rows else 0)
        img = Image.new("RGB", (width, block_h), card_bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (width - 1, block_h - 1)], outline=border, width=1)
        draw.text((pad, pad), title, fill=tcol, font=tf)
        y = pad + title_h
        for ln in lines:
            draw.text((pad, y), ln, fill=fg, font=bf)
            y += line_h
        return img

    def _text_width(draw: "ImageDraw.ImageDraw", text: str, font_obj: "ImageFont.ImageFont") -> int:
        try:
            box = draw.textbbox((0, 0), text, font=font_obj)
            return max(0, int(box[2] - box[0]))
        except Exception:
            return len(text) * 8

    def _wrap_text(
        draw: "ImageDraw.ImageDraw",
        text: str,
        font_obj: "ImageFont.ImageFont",
        max_width: int,
    ) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return [""]
        words = raw.split()
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if _text_width(draw, candidate, font_obj) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _normalize_card(card: object) -> dict[str, str]:
        if isinstance(card, dict):
            return {
                "label": str(card.get("label", "")),
                "value": str(card.get("value", "")),
                "detail": str(card.get("detail", "")),
                "winner": str(card.get("winner", "")),
                "winner_color": str(card.get("winner_color", "")),
            }
        if isinstance(card, (tuple, list)) and len(card) >= 3:
            return {
                "label": str(card[0]),
                "value": str(card[1]),
                "detail": str(card[2]),
                "winner": "",
                "winner_color": "",
            }
        return {"label": str(card), "value": "", "detail": "", "winner": "", "winner_color": ""}

    def metric_cards_block(cards: list[object], title: str = "Metrics") -> "Image.Image":
        if not cards:
            return Image.new("RGB", (width, 1), bg)

        if width >= 1600:
            cols = 4
        elif width >= 1100:
            cols = 3
        elif width >= 700:
            cols = 2
        else:
            cols = 1

        title_h = _line_height(font_section)
        card_gap = 12
        card_pad = 14
        grid_top = pad + title_h + 8
        card_width = max(180, int((width - (card_gap * (cols - 1))) / cols))
        measure_img = Image.new("RGB", (10, 10), bg)
        measure_draw = ImageDraw.Draw(measure_img)
        label_h = _line_height(font_metric_delta)
        value_h = _line_height(font_metric_value)
        winner_h = _line_height(font_metric_delta)
        delta_h = _line_height(font_metric_delta)

        card_layouts: list[dict[str, object]] = []
        for raw_card in cards:
            card = _normalize_card(raw_card)
            text_width = max(60, card_width - (card_pad * 2))
            label_lines = _wrap_text(measure_draw, card["label"], font_metric_delta, text_width)
            value_lines = _wrap_text(measure_draw, card["value"], font_metric_value, text_width)
            winner_lines = _wrap_text(measure_draw, card["winner"], font_metric_delta, text_width) if card["winner"].strip() else []
            delta_lines = _wrap_text(measure_draw, card["detail"], font_metric_delta, text_width) if card["detail"].strip() else []
            card_height = (
                card_pad * 2
                + (len(label_lines) * label_h)
                + 8
                + (len(value_lines) * value_h)
                + (8 + (len(winner_lines) * winner_h) if winner_lines else 0)
                + (8 + (len(delta_lines) * delta_h) if delta_lines else 0)
            )
            card_layouts.append(
                {
                    "label_lines": label_lines,
                    "value_lines": value_lines,
                    "winner_lines": winner_lines,
                    "winner_color": card["winner_color"],
                    "delta_lines": delta_lines,
                    "delta_class": _export_delta_class(card["detail"]),
                    "height": max(120, card_height),
                }
            )

        row_heights: list[int] = []
        for start in range(0, len(card_layouts), cols):
            row_heights.append(max(int(card["height"]) for card in card_layouts[start : start + cols]))

        grid_height = sum(row_heights) + (card_gap * max(0, len(row_heights) - 1))
        block_h = grid_top + grid_height + pad
        img = Image.new("RGB", (width, block_h), bg)
        draw = ImageDraw.Draw(img)
        draw.text((0, pad), title, fill=muted, font=font_section)

        delta_colors = {
            "delta-pos": "#22c55e",
            "delta-neg": "#ef4444",
            "delta-neutral": fg,
        }
        y = grid_top
        card_idx = 0
        for row_height in row_heights:
            for col_idx in range(cols):
                if card_idx >= len(cards):
                    break
                x = col_idx * (card_width + card_gap)
                draw.rounded_rectangle(
                    [(x, y), (x + card_width - 1, y + row_height - 1)],
                    radius=10,
                    fill=card_bg,
                    outline=border,
                    width=1,
                )
                layout = card_layouts[card_idx]
                ty = y + card_pad
                for line in layout["label_lines"]:
                    draw.text((x + card_pad, ty), str(line), fill=muted, font=font_metric_delta)
                    ty += label_h
                ty += 8
                for line in layout["value_lines"]:
                    draw.text((x + card_pad, ty), str(line), fill=fg, font=font_metric_value)
                    ty += value_h
                if layout["winner_lines"]:
                    ty += 8
                    winner_color = str(layout["winner_color"]).strip() or fg
                    for line in layout["winner_lines"]:
                        draw.text((x + card_pad, ty), str(line), fill=winner_color, font=font_metric_delta)
                        ty += winner_h
                if layout["delta_lines"]:
                    ty += 8
                delta_color = delta_colors.get(str(layout["delta_class"]), fg)
                for line in layout["delta_lines"]:
                    draw.text((x + card_pad, ty), str(line), fill=delta_color, font=font_metric_delta)
                    ty += delta_h
                card_idx += 1
            y += row_height + card_gap
        return img

    blocks: list["Image.Image"] = []
    header_lines = [
        f"Group: {selected_group}",
        f"Window: {int(window_days)}d",
        f"Export Mode: {theme['name']}",
        f"Accounts: {accounts_text}",
        f"Generated: {generated_at}",
    ]
    blocks.append(text_block(dashboard_title, header_lines, title_color=fg, title_font=font_title, body_font=font_body))
    blocks.append(metric_cards_block(metric_cards, title="Metrics"))

    def _append_chart_block(fig: go.Figure | None) -> tuple[bool, str | None]:
        if fig is None:
            return True, None
        sort_legend_by_latest_y(fig)
        _style_export_figure(fig, export_mode)
        h = int(fig.layout.height) if getattr(fig.layout, "height", None) else 520
        try:
            png_bytes = fig.to_image(format="png", width=width, height=max(320, h), scale=2)
        except Exception as e:
            msg = str(e).strip()
            if "broadcast_args_to_dicts" in msg or "plotly.io._utils" in msg:
                png_bytes, sub_err = _figure_to_png_via_subprocess(fig, width=width, height=max(320, h), scale=2)
                if not png_bytes:
                    detail = f" ({sub_err})" if sub_err else ""
                    return False, (
                        "Picture export failed due to mixed Plotly/Kaleido runtime. "
                        f"Restart Streamlit after dependency updates (`python run_server.py`).{detail}"
                    )
            elif "Chrome" in msg or "chrom" in msg.lower():
                return False, "Picture export needs Chrome for Kaleido v1. Install Chrome and retry."
            elif msg:
                return False, f"Picture export failed: {msg}"
            else:
                return False, "Picture export failed while rendering Plotly images."
        chart_img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        if chart_img.width != width:
            new_h = int(chart_img.height * (width / chart_img.width))
            chart_img = chart_img.resize((width, new_h))
        blocks.append(chart_img)
        return True, None

    if ordered_blocks:
        for block in ordered_blocks:
            block_type = str(block.get("type", "")).strip().lower() if isinstance(block, dict) else ""
            if block_type == "card_group":
                blocks.append(metric_cards_block(list(block.get("cards", [])), title=str(block.get("title", ""))))
                continue
            if block_type == "chart":
                ok, err = _append_chart_block(block.get("figure"))
                if not ok:
                    return None, err
    else:
        for _, fig in chart_items:
            ok, err = _append_chart_block(fig)
            if not ok:
                return None, err

    for sec_title, sec_df in sections_data:
        if sec_df.empty:
            blocks.append(text_block(sec_title, ["No data."], title_color=muted, title_font=font_section, body_font=font_body))
            continue
        formatted = _format_export_df(sec_df)
        preview_rows = min(len(formatted), 40)
        table_text = formatted.head(preview_rows).to_string(index=False).splitlines()
        lines = table_text
        if len(formatted) > preview_rows:
            lines += [f"... ({len(formatted) - preview_rows} more rows)"]
        blocks.append(text_block(sec_title, lines, title_color=muted, title_font=font_section, body_font=font_mono))

    total_h = pad
    for b in blocks:
        total_h += b.height + pad
    canvas = Image.new("RGB", (width + (pad * 2), total_h), bg)
    y = pad
    for b in blocks:
        canvas.paste(b, (pad, y))
        y += b.height + pad

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue(), None
