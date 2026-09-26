"""Real Yahoo fixture, fixed target definitions, and no synthetic production data."""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.free_signal_view import load_verified_real_signal  # noqa: E402
from src.regime_outlook_lab import rebuild_states  # noqa: E402
from src.transition_hazard_lab import (  # noqa: E402
    HORIZONS, MODELS, TARGETS, fit, folds, make_risk_set, state_frame,
)
from src.transition_hazard_view import load_transition_report  # noqa: E402


class TransitionHazardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROOT / "data" / "free_signal"
        cls.bundle = load_verified_real_signal(cls.source)
        cls.reconstructed, canonical = rebuild_states(
            cls.bundle, cls.source / "snapshots" / cls.bundle.signal_snapshot_id
        )
        cls.states = state_frame(cls.reconstructed, canonical)

    def test_first_entry_exit_and_endpoint_are_separate_risk_sets(self):
        for h in HORIZONS:
            for target in TARGETS:
                frame = make_risk_set(self.states, target, h)
                self.assertTrue((frame.target_idx - frame.origin_idx == h).all())
                for row in frame.itertuples(index=False):
                    window = self.states.iloc[row.origin_idx:row.target_idx + 1]
                    future = window["risk_signal"].iloc[1:].tolist()
                    self.assertTrue(window["spx_close"].notna().all())
                    if target == "de_risk_entry":
                        self.assertNotEqual(row.origin_state, "DE-RISK")
                        offsets = [k for k, value in enumerate(future, 1) if value == "DE-RISK"]
                    elif target == "de_risk_exit":
                        self.assertEqual(row.origin_state, "DE-RISK")
                        offsets = [k for k, value in enumerate(future, 1) if value != "DE-RISK"]
                    else:
                        offsets = [h] if future[-1] != row.origin_state else []
                    self.assertEqual(row.event, int(bool(offsets)))
                    self.assertEqual(row.first_event_date if pd.notna(row.first_event_date) else None,
                                     window.iloc[offsets[0]]["date"] if offsets else None)

    def test_duration_is_past_only_and_resets_on_observation_gap(self):
        states = self.states
        for i in range(1, len(states)):
            current, prior = states.iloc[i], states.iloc[i - 1]
            expected = (prior["duration"] + 1 if pd.notna(current["spx_close"])
                        and pd.notna(prior["spx_close"])
                        and current["risk_signal"] == prior["risk_signal"]
                        else 1 if pd.notna(current["spx_close"]) else 0)
            self.assertEqual(current["duration"], expected)

    def test_prefix_risk_set_and_feature_access(self):
        prefix = self.states.iloc[:1600].copy()
        full = make_risk_set(self.states, "de_risk_entry", 5)
        short = make_risk_set(prefix, "de_risk_entry", 5)
        comparable = full.loc[full["target_idx"] < 1600].reset_index(drop=True)
        pd.testing.assert_frame_equal(short, comparable)
        self.assertTrue((short["first_event_date"].dropna() <= short["target_date"].max()).all())

    def test_embargo_common_rows_and_deterministic_fit(self):
        sample = make_risk_set(self.states, "de_risk_entry", 3)
        start, train, test = next(folds(sample, 3, len(self.states)))
        self.assertTrue((train.target_idx < start - 3).all())
        self.assertGreater(test.origin_idx.min(), train.target_idx.max() + 3)
        scored = {}
        for model in MODELS:
            scores, _ = fit(train, test.head(20), model)
            repeated, _ = fit(train, test.head(20), model)
            np.testing.assert_array_equal(scores, repeated)
            self.assertTrue(np.isfinite(scores).all())
            scored[model] = len(scores)
        self.assertEqual(len(set(scored.values())), 1)
        changed = test.head(20).copy()
        changed.iloc[-1, changed.columns.get_loc("body_stress_score")] += 10
        unchanged, _ = fit(train, changed, "market")
        original, _ = fit(train, test.head(20), "market")
        np.testing.assert_array_equal(original[:-1], unchanged[:-1])

    def test_persisted_report_is_locked_to_current_real_snapshot(self):
        report, text = load_transition_report(
            ROOT / "research" / "transition_hazard",
            self.bundle.signal_snapshot_id, self.bundle.latest["data_snapshot_id"], self.source,
        )
        self.assertIn("NOT FOR PORTFOLIO ACTION", text)
        self.assertFalse(report["source_vintage_gate_pass"])
        for target in TARGETS:
            for h in HORIZONS:
                item = report["targets"][target][str(h)]
                self.assertEqual(
                    item["event_labels"] + item["non_events"], item["origins"]
                )
                self.assertIn(item["recommendation"], ("FAIL", "INSUFFICIENT EVIDENCE"))
        with self.assertRaises((FileNotFoundError, ValueError)):
            load_transition_report(
                ROOT / "research" / "transition_hazard", "wrong-snapshot",
                self.bundle.latest["data_snapshot_id"], self.source,
            )