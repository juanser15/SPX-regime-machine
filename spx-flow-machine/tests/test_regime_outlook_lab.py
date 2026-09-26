"""Deterministic desk-gate checks using the verified real Yahoo snapshot only."""

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.daily_signal import score_daily_regimes  # noqa: E402
from src.free_signal_view import load_verified_real_signal  # noqa: E402
from src.regime_outlook_lab import (  # noqa: E402
    HORIZONS, MODELS, build_samples, empirical_models, fit_logistic,
    rebuild_states, walk_forward_folds,
)
from src.regime_outlook_report import loss_vectors, paired_comparison  # noqa: E402
from src.regime_outlook_view import load_shadow_report  # noqa: E402


class RegimeOutlookLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROOT / "data" / "free_signal"
        cls.bundle = load_verified_real_signal(cls.source)
        cls.reconstructed, cls.canonical = rebuild_states(
            cls.bundle, cls.source / "snapshots" / cls.bundle.signal_snapshot_id
        )

    def test_reconstruction_is_separate_and_has_real_availability(self):
        reconstructed = self.reconstructed
        self.assertEqual(list(reconstructed["risk_signal"]),
                         list(self.bundle.history["risk_signal"]))
        self.assertEqual(set(reconstructed["research_status"]), {"RESEARCH RECONSTRUCTION"})
        self.assertEqual(reconstructed.iloc[-1]["date"], self.bundle.latest["date"])
        retrieved = pd.Timestamp(self.bundle.latest["retrieved_at_utc"])
        self.assertTrue(all(pd.Timestamp(value) >= retrieved
                            for value in reconstructed["available_at_utc"]))

    def test_real_prefix_invariance_and_no_future_feature_access(self):
        full = score_daily_regimes(self.canonical)
        for size in (800, 1600):
            prefix = score_daily_regimes(self.canonical.iloc[:size].copy())
            self.assertEqual(list(prefix["risk_signal"]), list(full.iloc[:size]["risk_signal"]))
            for name in ("body_stress_score", "overall_stress_score"):
                np.testing.assert_allclose(prefix[name], full.iloc[:size][name],
                                           atol=1e-10, rtol=0, equal_nan=True)

    def test_horizon_alignment_and_missing_closes_are_never_skipped(self):
        canonical = self.canonical.loc[
            self.canonical["date"] <= pd.Timestamp(self.reconstructed.iloc[-1]["date"])
        ].reset_index(drop=True)
        missing = set(canonical.index[canonical["spx_close"].isna()])
        self.assertTrue(missing, "This real snapshot has observed Yahoo gaps to test.")
        for horizon in HORIZONS:
            sample = build_samples(self.reconstructed, self.canonical, horizon)
            self.assertTrue((sample["target_idx"] - sample["origin_idx"] == horizon).all())
            self.assertTrue(all(
                row.date == canonical.iloc[row.origin_idx]["date"].strftime("%Y-%m-%d")
                and row.target_date == canonical.iloc[row.target_idx]["date"].strftime("%Y-%m-%d")
                and not any(row.origin_idx <= gap <= row.target_idx for gap in missing)
                for row in sample.itertuples(index=False)
            ))
            self.assertLessEqual(sample["target_date"].max(), self.reconstructed.iloc[-1]["date"])

    def test_folds_are_expanding_chronological_and_embargo_labels(self):
        for horizon in HORIZONS:
            samples = build_samples(self.reconstructed, self.canonical, horizon)
            folds = list(walk_forward_folds(samples, horizon, len(self.canonical) - 1))
            self.assertGreaterEqual(len(folds), 6)
            for start, train, test in folds:
                self.assertTrue((train["target_idx"] < start - horizon).all())
                self.assertGreater(test["origin_idx"].min(),
                                   train["target_idx"].max() + horizon)
                self.assertLess(train["date"].max(), test["date"].min())
            self.assertLess(folds[0][1]["origin_idx"].max(),
                            folds[-1][1]["origin_idx"].max())

    def test_train_only_features_normalization_and_reproducibility(self):
        samples = build_samples(self.reconstructed, self.canonical, 3)
        _, train, test = next(walk_forward_folds(samples, 3, len(self.canonical) - 1))
        test = test.head(20).copy()
        first, coefficients = fit_logistic(train, test)
        repeated, same = fit_logistic(train, test)
        np.testing.assert_array_equal(first, repeated)
        self.assertEqual(coefficients, same)
        changed_future_test = test.copy()
        changed_future_test.loc[changed_future_test.index[-1], "body_stress_score"] += 10
        modified, modified_coefficients = fit_logistic(train, changed_future_test)
        np.testing.assert_array_equal(first[:-1], modified[:-1])
        self.assertEqual(coefficients, modified_coefficients)
        self.assertTrue(np.allclose(first.sum(axis=1), 1))
        self.assertTrue((first >= 0).all())
        for matrix in empirical_models(train, test).values():
            self.assertTrue(np.allclose(matrix.sum(axis=1), 1))

    def test_common_oos_and_calibration_report_are_snapshot_locked(self):
        archived = next((ROOT / "research" / "regime_outlook").glob("*/manifest.json"))
        archive_manifest = json.loads(archived.read_text())
        archive_id = archive_manifest["signal_snapshot_id"]
        report, markdown = load_shadow_report(
            ROOT / "research" / "regime_outlook",
            archive_id, archive_manifest["input_snapshot_id"], self.source,
        )
        self.assertIn("NOT VALIDATED / NOT FOR PORTFOLIO ACTION", markdown)
        self.assertFalse(report["reconstruction"]["source_vintage_gate_pass"])
        prediction_path = (ROOT / "research" / "regime_outlook"
                           / archive_id / "oos_predictions.csv")
        predictions = pd.read_csv(prediction_path)
        for horizon in HORIZONS:
            subset = predictions.loc[predictions["horizon"] == horizon]
            frames = {
                model: subset.loc[subset["model"] == model].reset_index(drop=True)
                for model in MODELS
            }
            common = frames["markov"]
            self.assertTrue(all(list(f["date"]) == list(common["date"])
                                and list(f["target_date"]) == list(common["target_date"])
                                for f in frames.values()))
            for frame in frames.values():
                self.assertTrue(np.allclose(
                    frame[["score_risk_on", "score_neutral", "score_de_risk"]].sum(axis=1), 1
                ))
                self.assertEqual(len(loss_vectors(frame)[0]), len(common))
            paired_comparison(frames["logistic"], common)
            self.assertEqual(report["horizons"][str(horizon)]["recommendation"],
                             "INSUFFICIENT EVIDENCE")
        with self.assertRaises((FileNotFoundError, ValueError)):
            load_shadow_report(
                ROOT / "research" / "regime_outlook", self.bundle.signal_snapshot_id,
                self.bundle.latest["data_snapshot_id"], self.source,
            )


if __name__ == "__main__":
    unittest.main()