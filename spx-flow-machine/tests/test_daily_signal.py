import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
signal = importlib.import_module("src.daily_signal")


def canonical_frame(periods=420):
    dates = pd.bdate_range("2023-01-02", periods=periods)
    step = np.arange(periods, dtype=float)
    spx = 3800.0 * np.exp(0.0003 * step + 0.01 * np.sin(step / 18.0))
    return pd.DataFrame(
        {
            "date": dates,
            "spx_close": spx,
            "vix_close": 19.0 - 0.01 * step + 2.0 * np.cos(step / 21.0),
            "vix9d_close": 18.0 - 0.008 * step + np.cos(step / 17.0),
            "vix3m_close": 21.0 - 0.006 * step + np.cos(step / 23.0),
            "vvix_close": 95.0 + 5.0 * np.sin(step / 15.0),
            "skew_close": 135.0 + 4.0 * np.cos(step / 25.0),
        }
    )


class DailySignalTests(unittest.TestCase):
    def test_future_rows_do_not_change_past_features_or_scores(self):
        full = canonical_frame()
        cutoff = 350
        prefix_scores = signal.score_daily_regimes(full.iloc[:cutoff])
        full_scores = signal.score_daily_regimes(full)
        columns = [
            "body_stress_score",
            "tail_risk_hazard_score",
            "overall_stress_score",
            "risk_signal",
        ]
        pd.testing.assert_frame_equal(
            prefix_scores[columns],
            full_scores.iloc[:cutoff][columns],
            check_dtype=False,
        )

    def test_missing_augmented_inputs_produce_real_core_signal_without_imputation(self):
        data = canonical_frame()
        data[["vix9d_close", "vix3m_close", "vvix_close"]] = np.nan
        scored = signal.score_daily_regimes(data)
        latest = scored.iloc[-1]
        self.assertNotEqual(latest["risk_signal"], "INSUFFICIENT_DATA")
        self.assertTrue(pd.notna(latest["body_stress_score"]))
        self.assertTrue(pd.notna(latest["tail_risk_hazard_score"]))
        self.assertTrue(data["vix9d_close"].isna().all())

    def test_scores_are_not_labeled_as_probabilities(self):
        latest = signal.score_daily_regimes(canonical_frame()).iloc[-1]
        self.assertEqual(latest["probability_status"], "NOT_CALIBRATED")
        self.assertIn("not_probability", latest["score_type"])
        self.assertGreaterEqual(latest["overall_stress_score"], 0.0)
        self.assertLessEqual(latest["overall_stress_score"], 100.0)

    def test_score_is_deterministic_for_free_daily_regime_v1(self):
        data = canonical_frame()
        first = signal.score_daily_regimes(data)
        second = signal.score_daily_regimes(data.copy())
        pd.testing.assert_series_equal(
            first["overall_stress_score"], second["overall_stress_score"]
        )
        self.assertEqual(signal.MODEL_VERSION, "free_daily_regime_v1")

    def test_refresh_quality_is_per_date_and_degraded_is_not_deployable(self):
        data = canonical_frame()
        data.loc[data.index[-2], "vvix_close"] = np.nan
        data_manifest = {
            "retrieved_at_utc": "2026-09-18T12:00:00+00:00",
            "snapshot": {"snapshot_id": "input-snapshot"},
            "series": {"spx_close": {}, "vix_close": {}, "skew_close": {}},
            "unavailable_series": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                signal, "ingest_yahoo_daily",
                return_value=(data, data_manifest),
            ):
                history, manifest = signal.refresh_free_signal(
                    "2023-01-01", "2026-01-01", directory
                )
        degraded = next(
            row for row in manifest["per_date_quality"]
            if row["date"] == data.iloc[-2]["date"].date().isoformat()
        )
        complete = next(
            row for row in manifest["per_date_quality"]
            if row["date"] == data.iloc[-1]["date"].date().isoformat()
        )
        self.assertEqual(degraded["data_quality"], "DEGRADED_MISSING_INPUTS")
        self.assertIn("vvix_close", degraded["missing_inputs"])
        self.assertFalse(degraded["deployable"])
        self.assertEqual(complete["data_quality"], "COMPLETE")
        self.assertEqual(complete["component_quality"], "COMPLETE")
        self.assertFalse(complete["deployable"])
        self.assertFalse(manifest["deployable"])
        self.assertEqual(manifest["research_status"], "RESEARCH_ONLY")

    def test_refresh_persists_provenance_and_signal_snapshot(self):
        data = canonical_frame()
        data[["vix9d_close", "vix3m_close", "vvix_close"]] = np.nan
        data_manifest = {
            "retrieved_at_utc": "2026-09-18T12:00:00+00:00",
            "snapshot": {"snapshot_id": "input-snapshot"},
            "series": {
                "spx_close": {},
                "vix_close": {},
                "skew_close": {},
            },
            "unavailable_series": {
                "vix9d_close": {"ticker": "^VIX9D", "reason": "unavailable"},
                "vix3m_close": {"ticker": "^VIX3M", "reason": "unavailable"},
                "vvix_close": {"ticker": "^VVIX", "reason": "unavailable"},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                signal,
                "ingest_yahoo_daily",
                return_value=(data, data_manifest),
            ):
                history, manifest = signal.refresh_free_signal(
                    "2023-01-01", "2026-01-01", directory
                )
            self.assertEqual(manifest["data_lane"], "CORE_FREE_DEGRADED")
            self.assertTrue((Path(directory) / "latest_signal.json").exists())
            self.assertTrue((Path(directory) / "signal_manifest.json").exists())
            snapshot = Path(directory) / "snapshots" / manifest["signal_snapshot_id"]
            self.assertTrue((snapshot / "signal_history.csv").exists())
            self.assertEqual(history.iloc[-1]["probability_status"], "NOT_CALIBRATED")


if __name__ == "__main__":
    unittest.main()