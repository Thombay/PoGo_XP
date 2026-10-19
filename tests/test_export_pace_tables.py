from __future__ import annotations

import unittest

import pandas as pd
import plotly.graph_objects as go

from webapp.exporting import build_dashboard_export_html


class ExportPaceTablesTest(unittest.TestCase):
    def test_dark_pane_places_pace_table_between_summary_and_chart(self):
        fig = go.Figure(data=[go.Scatter(x=[1], y=[1], mode="markers")])

        def build_payload(_window_days: int) -> dict[str, object]:
            return {
                "metric_cards": [],
                "chart_items": [],
                "sections": [],
                "accounts_text": "A",
                "generated_at": "2026-01-01",
                "ordered_blocks": [
                    {
                        "type": "card_group",
                        "title": "Activity Summary: Pokemon (7d)",
                        "cards": [
                            {
                                "label": "Leader",
                                "value": "1",
                                "detail": "steady",
                                "winner": "Ace",
                                "winner_color": "#ffffff",
                            }
                        ],
                    },
                    {
                        "type": "table",
                        "title": "Pokemon Pace (7d)",
                        "dataframe": pd.DataFrame([{"Account": "Fast", "Pokemon/day": "10.00"}]),
                    },
                    {
                        "type": "chart",
                        "title": "Activity: Pokemon Gained Over Time",
                        "figure": fig,
                    },
                ],
            }

        html = build_dashboard_export_html(
            dashboard_title="Dashboard",
            selected_group="Global",
            export_mode="dark",
            window_days=7,
            dashboard_window_options=[7],
            build_payload_for_window=build_payload,
            sort_legend_by_latest_y=lambda figure: None,
        )
        start = html.index("id='window-pane-7-dark'")
        end = html.index("id='window-pane-7-light'")
        pane = html[start:end]
        summary_at = pane.index("Activity Summary: Pokemon (7d)")
        pace_at = pane.index("Pokemon Pace (7d)")
        chart_at = pane.index("Activity: Pokemon Gained Over Time")
        self.assertLess(summary_at, pace_at)
        self.assertLess(pace_at, chart_at)
        self.assertIn("Fast", pane)
        self.assertIn("10.00", pane)


if __name__ == "__main__":
    unittest.main()
