import importlib
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime
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


def staged_ingest(frame, manifest):
    """Mock Yahoo I/O while preserving the real staged-snapshot contract."""
    def ingest(start, end, output_dir, *, allow_missing_optional):
        assert allow_missing_optional
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        data = frame.copy()
        csv_payload = data.to_csv(index=False, lineterminator="\n", float_format="%.17g")
        source = copy.deepcopy(manifest)
        source["source"] = "Yahoo Finance"
        source["canonical_sha256"] = hashlib.sha256(csv_payload.encode()).hexdigest()
        snapshot = output / "snapshots" / source["snapshot"]["snapshot_id"]
        snapshot.mkdir(parents=True)
        (snapshot / "canonical_daily.csv").write_text(csv_payload)
        (snapshot / "metadata_manifest.json").write_text(json.dumps(source))
        (snapshot / "coverage_report.json").write_text("{}")
        (snapshot / "raw").mkdir()
        return data, source
    return ingest


class DailySignalTests(unittest.TestCase):
    def test_preopen_provisional_row_is_preserved_but_not_published_or_frozen(self):
        from src.free_signal_view import (
            decision_for_display, load_verified_real_signal,
        )

        base = canonical_frame(periods=420)
        base.loc[418, "date"] = pd.Timestamp("2026-09-24")
        base.loc[419, "date"] = pd.Timestamp("2026-09-25")
        preopen = base.copy()
        preopen.loc[419, ["spx_close", "vix9d_close", "vix3m_close",
                          "vvix_close", "skew_close"]] = np.nan
        during = base.copy()
        during.loc[419, "skew_close"] = np.nan
        preopen_at = datetime.fromisoformat("2026-09-25T13:29:46+00:00")
        during_at = datetime.fromisoformat("2026-09-25T14:00:00+00:00")
        completed_at = datetime.fromisoformat("2026-09-26T03:00:00+00:00")

        def meta(snapshot_id, retrieved):
            return {
                "retrieved_at_utc": retrieved.isoformat(),
                "snapshot": {"snapshot_id": snapshot_id},
                "series": {"spx_close": {}, "vix_close": {}, "skew_close": {}},
                "unavailable_series": {},
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(signal, "ingest_yahoo_daily",
                              side_effect=staged_ingest(
                                  preopen, meta("preopen-snapshot", preopen_at))):
                initial, initial_manifest = signal.refresh_free_signal(
                    "2023-01-01", "2026-09-26", root,
                    now=preopen_at.replace(minute=30),
                )
            self.assertEqual(initial.iloc[-1]["date"].date().isoformat(), "2026-09-24")
            old_id = initial_manifest["signal_snapshot_id"]
            audit_path = root / "audits" / f"{old_id}.jsonl"
            original_audit = audit_path.read_bytes()
            provisional = pd.read_csv(
                root / "daily_data" / "snapshots" / "preopen-snapshot" / "canonical_daily.csv"
            ).iloc[-1]
            self.assertTrue(pd.isna(provisional["spx_close"]))
            self.assertTrue(pd.notna(provisional["vix_close"]))

            with patch.object(signal, "ingest_yahoo_daily",
                              side_effect=staged_ingest(
                                  during, meta("intraday-snapshot", during_at))):
                intraday, _ = signal.refresh_free_signal(
                    "2023-01-01", "2026-09-26", root,
                    now=during_at.replace(minute=5),
                )
            self.assertEqual(intraday.iloc[-1]["date"].date().isoformat(), "2026-09-24")
            self.assertTrue((root / "snapshots" / old_id).exists())
            self.assertEqual(audit_path.read_bytes(), original_audit)
            protected_history = (root / "signal_history.csv").read_bytes()
            bundle = load_verified_real_signal(root)
            self.assertEqual(bundle.latest["date"], "2026-09-24")
            self.assertEqual(
                decision_for_display(bundle.latest, bundle.input_row,
                                     now=during_at.replace(minute=5))[0],
                "HOLD / NO ACTION",
            )

            with patch.object(signal, "ingest_yahoo_daily",
                              side_effect=staged_ingest(
                                  base, meta("completed-snapshot", completed_at))):
                finished, finished_manifest = signal.refresh_free_signal(
                    "2023-01-01", "2026-09-27", root,
                    now=completed_at.replace(minute=5),
                )
            self.assertEqual(finished.iloc[-1]["date"].date().isoformat(), "2026-09-25")
            self.assertTrue((root / "signal_history.csv").read_bytes().startswith(protected_history))
            self.assertNotEqual(old_id, finished_manifest["signal_snapshot_id"])
            self.assertEqual(audit_path.read_bytes(), original_audit)

            revised = base.copy()
            revised.loc[418, "spx_close"] *= 0.5  # September 24 was finalized.
            prior_pointer = (root / "signal_manifest.json").read_bytes()
            with patch.object(signal, "ingest_yahoo_daily",
                              side_effect=staged_ingest(
                                  revised, meta("vendor-revision", completed_at))):
                with self.assertLogs(level="WARNING"):
                    with self.assertRaisesRegex(RuntimeError, "2026-09-24"):
                        signal.refresh_free_signal(
                            "2023-01-01", "2026-09-27", root,
                            now=completed_at.replace(minute=10),
                        )
            self.assertEqual((root / "signal_manifest.json").read_bytes(), prior_pointer)
            review = json.loads(
                (root / "revision_reviews" / "vendor-revision" / "review.json").read_text()
            )
            self.assertIn("2026-09-24", [item["date"] for item in review["changes"]])

            invalid = base.copy()
            invalid.loc[419, "spx_close"] = np.nan
            with patch.object(signal, "ingest_yahoo_daily",
                              side_effect=staged_ingest(
                                  invalid, meta("insufficient-snapshot", completed_at))):
                with self.assertLogs(level="WARNING"):
                    with self.assertRaises(signal.SignalValidityError):
                        signal.refresh_free_signal(
                            "2023-01-01", "2026-09-27", root,
                            now=completed_at.replace(minute=15),
                        )
            self.assertEqual((root / "signal_manifest.json").read_bytes(), prior_pointer)
            failure_bundle = load_verified_real_signal(root)
            self.assertIsNotNone(failure_bundle.current_failure)
            action, eligible, _ = decision_for_display(
                failure_bundle.latest, failure_bundle.input_row,
                now=completed_at.replace(minute=15),
                current_failure=failure_bundle.current_failure,
            )
            self.assertFalse(eligible)
            self.assertEqual(action, "SIGNAL UNAVAILABLE — DATA FAILURE / INSUFFICIENT REAL DATA")

    def test_legacy_provisional_row_is_not_a_finalized_vendor_revision(self):
        preopen_at = datetime.fromisoformat("2026-09-25T13:29:46+00:00")
        completed_at = datetime.fromisoformat("2026-09-26T03:00:00+00:00")
        previous = "date,risk_signal\n2026-09-24,NEUTRAL\n2026-09-25,RISK-ON\n"
        corrected = "date,risk_signal\n2026-09-24,NEUTRAL\n2026-09-25,NEUTRAL\n"
        self.assertEqual(
            signal._finalized_history_changes(previous, corrected, preopen_at), []
        )
        self.assertEqual(
            signal._finalized_history_changes(previous, corrected, completed_at),
            [{"date": "2026-09-25", "fields": ["risk_signal"]}],
        )
        revised_yesterday = corrected.replace("2026-09-24,NEUTRAL", "2026-09-24,DE-RISK")
        self.assertEqual(
            signal._finalized_history_changes(previous, revised_yesterday, preopen_at),
            [{"date": "2026-09-24", "fields": ["risk_signal"]}],
        )

    def test_frozen_threshold_boundaries_and_pm_labels(self):
        from src.free_signal_view import pm_action

        for score, research, displayed in (
            (34.999999, "RISK-ON", "RISK-ON"),
            (35.0, "RISK-ON", "RISK-ON"),
            (35.000001, "NEUTRAL", "HOLD / NO ACTION"),
            (64.999999, "NEUTRAL", "HOLD / NO ACTION"),
            (65.0, "DE-RISK", "DE-RISK"),
            (65.000001, "DE-RISK", "DE-RISK"),
            (np.nan, "INSUFFICIENT_DATA", "HOLD / NO ACTION"),
        ):
            with self.subTest(score=score):
                self.assertEqual(signal.risk_signal_for_score(score), research)
                self.assertEqual(pm_action(research), displayed)

    def test_percentile_uses_only_trailing_finite_values_and_includes_ties(self):
        values = pd.Series([5.0] * 59 + [8.0, 5.0, np.nan, 1.0])
        ranks = signal._rolling_percentile(values, window=60, min_periods=60)
        self.assertEqual(float(ranks.iloc[59]), 100.0)
        self.assertEqual(float(ranks.iloc[60]), 100.0 * 59 / 60)
        self.assertTrue(pd.isna(ranks.iloc[61]))
        self.assertTrue(pd.isna(ranks.iloc[62]))  # only 59 finite trailing values
        extended = signal._rolling_percentile(
            pd.concat([values, pd.Series([10000.0])], ignore_index=True),
            window=60, min_periods=60,
        )
        pd.testing.assert_series_equal(ranks, extended.iloc[:-1], check_names=False)

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

    def test_all_components_reconstruct_frozen_score_from_available_inputs(self):
        data = canonical_frame()
        data.loc[data.index[-1], ["vix9d_close", "vix3m_close", "vvix_close"]] = np.nan
        row = signal.score_daily_regimes(data).iloc[-1]
        details = signal.component_details(row)
        self.assertTrue(details)
        self.assertNotIn("vvix", {part["name"] for part in details})
        self.assertAlmostEqual(sum(part["effective_weight"] for part in details), 1.0)
        self.assertAlmostEqual(
            sum(part["weighted_points"] for part in details), row["overall_stress_score"]
        )

    def test_append_only_audit_is_deterministic_and_persists_every_row(self):
        base = canonical_frame(periods=420)
        extended = canonical_frame(periods=425)
        def manifest(snapshot_id):
            return {
                "retrieved_at_utc": "2026-09-18T12:00:00+00:00",
                "snapshot": {"snapshot_id": snapshot_id},
                "series": {"spx_close": {}, "vix_close": {}, "skew_close": {}},
                "unavailable_series": {},
            }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(signal, "ingest_yahoo_daily") as ingest:
                ingest.side_effect = staged_ingest(base, manifest("snapshot-A"))
                first, first_manifest = signal.refresh_free_signal(
                    "2023-01-01", "2026-01-01", output
                )
                original_csv = (output / "signal_history.csv").read_bytes()
                first_audit = (output / "audits" / f"{first_manifest['signal_snapshot_id']}.jsonl")
                original_audit = first_audit.read_bytes()
                records = [json.loads(line) for line in original_audit.splitlines()]
                schema = json.loads(
                    (PROJECT_ROOT / "docs" / "free_daily_regime_v1.schema.json").read_text()
                )
                self.assertEqual(len(records), len(first))
                for record, (_, row) in zip(records, first.iterrows()):
                    self.assertEqual(set(record), set(schema["required"]))
                    self.assertEqual(record["date"], row["date"].date().isoformat())
                    self.assertEqual(record["model_version"], signal.MODEL_VERSION)
                    self.assertEqual(record["source"], "Yahoo Finance historical daily (not live)")
                    self.assertTrue(record["research_only"])
                    self.assertEqual(record["risk_signal"], row["risk_signal"])
                    self.assertEqual(record["probability_status"], "NOT_CALIBRATED")
                    self.assertEqual(record["confidence"], row["confidence"])
                    self.assertEqual(record["data_quality"], row["data_quality"])
                    self.assertEqual(record["primary_drivers"], row["primary_drivers"].split("; "))
                    self.assertEqual(record["input_data_snapshot_id"], "snapshot-A")
                    self.assertAlmostEqual(
                        sum(component["weighted_points"] for component in record["components"]),
                        record["overall_stress_score"],
                    )
                    for component in record["components"]:
                        self.assertEqual(
                            set(component), set(schema["properties"]["components"]["items"]["required"])
                        )
                    available = datetime.fromisoformat(record["available_at_utc"])
                    self.assertGreaterEqual(available, datetime.fromisoformat(record["calculated_at_utc"]))
                    self.assertGreaterEqual(available, datetime.fromisoformat(record["source_retrieved_at_utc"]))
                # Re-run identical input: immutable audit and old CSV bytes stay identical.
                signal.refresh_free_signal("2023-01-01", "2026-01-01", output)
                self.assertEqual(first_audit.read_bytes(), original_audit)
                self.assertEqual((output / "signal_history.csv").read_bytes(), original_csv)

                ingest.side_effect = staged_ingest(extended, manifest("snapshot-B"))
                appended, new_manifest = signal.refresh_free_signal(
                    "2023-01-01", "2026-01-01", output
                )
                self.assertEqual(len(appended), len(first) + 5)
                self.assertTrue((output / "signal_history.csv").read_bytes().startswith(original_csv))
                self.assertEqual(first_audit.read_bytes(), original_audit)
                self.assertNotEqual(first_manifest["signal_snapshot_id"], new_manifest["signal_snapshot_id"])

                revised = extended.copy()
                revised.loc[revised.index[300], "spx_close"] *= 0.5
                ingest.side_effect = staged_ingest(revised, manifest("snapshot-C"))
                before_pointer = (output / "signal_manifest.json").read_bytes()
                with self.assertLogs(level="WARNING") as captured:
                    with self.assertRaisesRegex(RuntimeError, "refusing to silently revise"):
                        signal.refresh_free_signal("2023-01-01", "2026-01-01", output)
                self.assertIn("requires explicit review", "\n".join(captured.output))
                self.assertEqual((output / "signal_manifest.json").read_bytes(), before_pointer)
                self.assertTrue((output / "revision_reviews" / "snapshot-C" / "review.json").exists())
                self.assertEqual(first_audit.read_bytes(), original_audit)

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
            with patch.object(signal, "ingest_yahoo_daily",
                              side_effect=staged_ingest(data, data_manifest)):
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
            with patch.object(signal, "ingest_yahoo_daily",
                              side_effect=staged_ingest(data, data_manifest)):
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