"""Presentation regressions: no fabricated observations, returns, or regimes."""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analysis_view import (  # noqa: E402
    factor_cards, forward_returns, observed_history, plain_drivers,
    regime_figure, return_summary, returns_figure,
)


class AnalysisViewTests(unittest.TestCase):
    def setUp(self):
        self.days = pd.bdate_range("2026-08-03", periods=15)
        self.history = pd.DataFrame({
            "date": self.days[:11],
            "risk_signal": ["RISK-ON"] * 4 + ["NEUTRAL"] * 4 + ["DE-RISK"] * 3,
        })
        self.canonical = pd.DataFrame({
            "date": self.days,
            "spx_close": [100 + i for i in range(15)],
        })

    def test_history_never_invents_unpublished_regimes_or_missing_closes(self):
        self.canonical.loc[2, "spx_close"] = float("nan")
        plotted = observed_history(self.history, self.canonical)
        self.assertEqual(len(plotted), 10)
        self.assertEqual(plotted["date"].max(), self.days[10])
        self.assertNotIn(self.days[2], list(plotted["date"]))
        fig = regime_figure(plotted, "MAX")
        self.assertEqual(list(fig.data[0].y), list(plotted["spx_close"]))
        self.assertEqual(sum(len(trace.x) for trace in fig.data[1:]), len(plotted))

    def test_five_session_returns_exclude_gaps_and_provisional_outcomes(self):
        self.canonical.loc[3, "spx_close"] = float("nan")
        paired = forward_returns(self.history, self.canonical)
        # The first four signal rows depend on the missing close at row 3.
        self.assertEqual(list(paired["date"]), list(self.days[4:6]))
        self.assertAlmostEqual(
            paired.iloc[0]["forward_return"], (109 / 104 - 1) * 100
        )
        self.assertLessEqual(paired["date"].max(), self.days[10])
        summary = return_summary(paired)
        self.assertEqual(sum(item["count"] for item in summary), 2)
        self.assertEqual(len(returns_figure(paired).data), 3)

    def test_factors_and_plain_drivers_require_real_inputs_and_components(self):
        row = pd.Series({
            "spx_close": 5000.0, "vix_close": 18.0, "vix9d_close": float("nan"),
            "vix3m_close": float("nan"), "skew_close": float("nan"),
            "vvix_close": float("nan"),
        })
        components = [
            {"name": "weak_20d_trend", "effective_weight": .25, "weighted_points": 5.0},
            {"name": "vix_level", "effective_weight": .2, "weighted_points": 16.0},
        ]
        cards = factor_cards(components, row)
        self.assertEqual(len(cards), 5)
        self.assertEqual(cards[0]["status"], "Supportive")
        self.assertEqual(cards[2]["status"], "Stressed")
        self.assertEqual(cards[3]["status"], "Unavailable")
        self.assertEqual(cards[4]["status"], "Unavailable")
        self.assertEqual(
            plain_drivers(
                "vix_level=80 (raises stress); skew=90 (raises stress); "
                "weak_20d_trend=20 (reduces stress)", row,
            ),
            ["VIX level adds to market stress.", "Recent SPX trend eases market stress."],
        )


if __name__ == "__main__":
    unittest.main()