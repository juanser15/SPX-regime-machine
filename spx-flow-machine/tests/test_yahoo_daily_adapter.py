import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
adapter = importlib.import_module("src.yahoo_daily_adapter")


def make_payload(index, closes):
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [100] * len(closes),
        },
        index=pd.to_datetime(index),
    )


class YahooDailyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.payloads = {
            "^GSPC": make_payload(
                ["2024-01-02", "2024-01-03", "2024-01-04"], [4700.0, 4710.0, 4720.0]
            ),
            "^VIX": make_payload(
                ["2024-01-02", "2024-01-03", "2024-01-04"], [15.0, np.nan, 16.0]
            ),
            "^VIX9D": make_payload(["2024-01-03", "2024-01-04"], [14.0, 15.0]),
            "^VIX3M": make_payload(["2024-01-03", "2024-01-04"], [18.0, 19.0]),
            "^VVIX": make_payload(["2024-01-03", "2024-01-04"], [90.0, 91.0]),
            "^SKEW": make_payload(
                ["2024-01-02", "2024-01-03", "2024-01-04"], [140.0, 141.0, 142.0]
            ),
        }

    def fetcher(self, ticker, _start, _end):
        return self.payloads[ticker].copy()

    def ingest(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        canonical, manifest = adapter.ingest_yahoo_daily(
            "2024-01-02", "2024-01-05", temp_dir.name, fetcher=self.fetcher
        )
        return Path(temp_dir.name), canonical, manifest

    def test_canonical_schema_and_date_ordering(self):
        _, canonical, _ = self.ingest()
        self.assertEqual(list(canonical.columns), list(adapter.CANONICAL_COLUMNS))
        self.assertTrue(canonical["date"].is_monotonic_increasing)
        self.assertFalse(canonical["date"].duplicated().any())

    def test_missing_values_are_not_forward_filled_or_interpolated(self):
        _, canonical, _ = self.ingest()
        row = canonical.loc[canonical["date"] == pd.Timestamp("2024-01-03")].iloc[0]
        self.assertTrue(pd.isna(row["vix_close"]))

    def test_outer_calendar_alignment_does_not_globally_drop_na(self):
        _, canonical, _ = self.ingest()
        self.assertEqual(len(canonical), 3)
        first_row = canonical.loc[canonical["date"] == pd.Timestamp("2024-01-02")].iloc[0]
        self.assertTrue(pd.isna(first_row["vix9d_close"]))
        self.assertTrue(pd.isna(first_row["vvix_close"]))

    def test_duplicate_dates_are_deduplicated_and_conflicts_reported(self):
        self.payloads["^VIX"] = make_payload(
            ["2024-01-03", "2024-01-02", "2024-01-02", "2024-01-04"],
            [15.0, 14.0, 99.0, 16.0],
        )
        _, canonical, manifest = self.ingest()
        self.assertEqual(len(canonical), 3)
        quality = manifest["series"]["vix_close"]["data_quality"]
        self.assertTrue(quality["input_non_monotonic"])
        self.assertEqual(quality["duplicate_date_count"], 1)
        self.assertEqual(quality["conflicting_duplicate_observations"][0]["date"], "2024-01-02")
        self.assertEqual(
            canonical.loc[canonical["date"] == pd.Timestamp("2024-01-02"), "vix_close"].iloc[0],
            14.0,
        )

    def test_manifest_and_raw_payloads_are_written(self):
        output_dir, _, manifest = self.ingest()
        manifest_path = output_dir / "metadata_manifest.json"
        self.assertTrue(manifest_path.exists())
        self.assertTrue((output_dir / "canonical_daily.csv").exists())
        self.assertTrue((output_dir / "coverage_report.json").exists())
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(written["canonical_sha256"], manifest["canonical_sha256"])
        for series in written["series"].values():
            self.assertEqual(series["source"], "Yahoo Finance")
            self.assertTrue((output_dir / series["raw_payload_file"]).exists())
            self.assertTrue(series["data_quality"]["numeric_validity"]["numeric_values_valid"])

        snapshot_dir = output_dir / written["snapshot"]["relative_path"]
        self.assertTrue(written["snapshot"]["immutable"])
        self.assertTrue(written["snapshot"]["created"])
        self.assertTrue((snapshot_dir / "canonical_daily.csv").exists())
        self.assertTrue((snapshot_dir / "coverage_report.json").exists())
        self.assertTrue((snapshot_dir / "metadata_manifest.json").exists())

    def test_snapshot_is_content_addressed_and_not_overwritten(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        output_dir = Path(temp_dir.name)
        _, first_manifest = adapter.ingest_yahoo_daily(
            "2024-01-02", "2024-01-05", output_dir, fetcher=self.fetcher
        )
        snapshot_file = (
            output_dir
            / first_manifest["snapshot"]["relative_path"]
            / "metadata_manifest.json"
        )
        original_snapshot = snapshot_file.read_text(encoding="utf-8")

        _, second_manifest = adapter.ingest_yahoo_daily(
            "2024-01-02", "2024-01-05", output_dir, fetcher=self.fetcher
        )
        self.assertEqual(
            first_manifest["snapshot"]["snapshot_id"],
            second_manifest["snapshot"]["snapshot_id"],
        )
        self.assertFalse(second_manifest["snapshot"]["created"])
        self.assertEqual(snapshot_file.read_text(encoding="utf-8"), original_snapshot)

    def test_core_and_augmented_coverage_are_calculated_separately(self):
        _, _, manifest = self.ingest()
        coverage = manifest["coverage"]
        self.assertEqual(coverage["core_lane"]["complete_rows"], 2)
        self.assertEqual(coverage["augmented_lane"]["complete_rows"], 2)
        self.assertEqual(coverage["per_series"]["vix9d_close"]["first_valid_date"], "2024-01-03")

    def test_required_ticker_download_failure_is_loud(self):
        def failing_fetcher(ticker, start, end):
            if ticker == "^VVIX":
                return pd.DataFrame()
            return self.fetcher(ticker, start, end)

        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaisesRegex(adapter.YahooDownloadError, r"\^VVIX"):
                adapter.ingest_yahoo_daily(
                    "2024-01-02", "2024-01-05", output_dir, fetcher=failing_fetcher
                )
            failure_manifest = json.loads(
                (Path(output_dir) / "metadata_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failure_manifest["status"], "failed")
            self.assertEqual(failure_manifest["failure"]["ticker"], "^VVIX")
            self.assertFalse(failure_manifest["canonical_output_written"])

    def test_free_mode_degrades_when_optional_series_is_unavailable(self):
        def partial_fetcher(ticker, start, end):
            if ticker in {"^VIX9D", "^VVIX"}:
                return pd.DataFrame()
            return self.fetcher(ticker, start, end)

        with tempfile.TemporaryDirectory() as output_dir:
            canonical, manifest = adapter.ingest_yahoo_daily(
                "2024-01-02",
                "2024-01-05",
                output_dir,
                fetcher=partial_fetcher,
                allow_missing_optional=True,
            )
            self.assertEqual(manifest["status"], "degraded")
            self.assertIn("vix9d_close", manifest["unavailable_series"])
            self.assertIn("vvix_close", manifest["unavailable_series"])
            self.assertTrue(canonical["vix9d_close"].isna().all())
            self.assertTrue(canonical["vvix_close"].isna().all())

    def test_invalid_numeric_close_fails_loudly(self):
        self.payloads["^VIX"] = make_payload(
            ["2024-01-02", "2024-01-03", "2024-01-04"], [15.0, "invalid", 16.0]
        )
        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaisesRegex(adapter.YahooDownloadError, r"invalid Close"):
                adapter.ingest_yahoo_daily(
                    "2024-01-02", "2024-01-05", output_dir, fetcher=self.fetcher
                )

    def test_unexpected_weekday_gaps_are_reported(self):
        self.payloads["^VIX9D"] = make_payload(
            ["2024-01-02", "2024-01-08"], [14.0, 15.0]
        )
        _, _, manifest = self.ingest()
        gaps = manifest["series"]["vix9d_close"]["data_quality"]["unexpected_gaps"]
        self.assertEqual(gaps["potential_weekday_gap_count"], 3)
        self.assertEqual(gaps["potential_weekday_gap_intervals"][0]["start_date"], "2024-01-03")
        self.assertEqual(gaps["potential_weekday_gap_intervals"][0]["end_date"], "2024-01-05")


if __name__ == "__main__":
    unittest.main()