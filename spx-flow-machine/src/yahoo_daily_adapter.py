"""
Deterministic Yahoo Finance adapter for SPX Daily Regime Research.

This module deliberately performs only daily market-data ingestion.  It does
not transform prices into features, fill missing observations, or attach any
research/model logic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
import yfinance as yf


SOURCE_NAME = "Yahoo Finance"
CANONICAL_COLUMNS = (
    "date",
    "spx_close",
    "vix_close",
    "vix9d_close",
    "vix3m_close",
    "vvix_close",
    "skew_close",
)


@dataclass(frozen=True)
class SeriesDefinition:
    ticker: str
    canonical_field: str
    lane: str


SERIES: tuple[SeriesDefinition, ...] = (
    SeriesDefinition("^GSPC", "spx_close", "core"),
    SeriesDefinition("^VIX", "vix_close", "core"),
    SeriesDefinition("^VIX9D", "vix9d_close", "augmented"),
    SeriesDefinition("^VIX3M", "vix3m_close", "augmented"),
    SeriesDefinition("^VVIX", "vvix_close", "augmented"),
    SeriesDefinition("^SKEW", "skew_close", "core"),
)


class YahooDownloadError(RuntimeError):
    """Raised when a required Yahoo Finance series cannot be retrieved."""


Fetcher = Callable[[str, str, str], pd.DataFrame]


def yahoo_download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download one unadjusted daily Yahoo Finance payload."""

    return yf.download(
        ticker,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Turn a Yahoo multi-index payload into a CSV-safe, deterministic frame."""

    flattened = frame.copy()
    if isinstance(flattened.columns, pd.MultiIndex):
        flattened.columns = [
            "__".join(str(part) for part in column if str(part))
            for column in flattened.columns.to_flat_index()
        ]
    else:
        flattened.columns = [str(column) for column in flattened.columns]
    return flattened


def _close_column(frame: pd.DataFrame) -> str:
    """Locate Yahoo's raw Close column without accepting adjusted close."""

    matches = [
        column
        for column in frame.columns
        if str(column).split("__", 1)[0].strip().lower() == "close"
    ]
    if len(matches) != 1:
        raise YahooDownloadError(
            "Yahoo Finance payload must contain exactly one raw Close column; "
            f"found {matches or 'none'}."
        )
    return matches[0]


def _to_date_series(values: pd.Index | pd.Series) -> pd.Series:
    dates = pd.to_datetime(values, errors="raise", utc=True)
    if isinstance(dates, pd.DatetimeIndex):
        dates = pd.Series(dates)
    return dates.dt.tz_convert(None).dt.normalize()


def _write_csv(frame: pd.DataFrame, path: Path) -> str:
    """Write a stable CSV representation and return its SHA-256 digest."""

    payload = frame.to_csv(index=False, lineterminator="\n", float_format="%.17g")
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()
    if hasattr(value, "item"):
        return value.item()  # numpy scalars
    return value


def _deduplicate_series(
    date_and_close: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Sort one series and retain the first observation per date deterministically."""

    original_dates = date_and_close["date"]
    non_monotonic_input = not original_dates.is_monotonic_increasing
    sorted_frame = date_and_close.sort_values("date", kind="mergesort").reset_index(
        drop=True
    )

    duplicate_dates: list[str] = []
    conflicting_duplicates: list[dict[str, object]] = []
    keep_indices: list[int] = []
    for date, group in sorted_frame.groupby("date", sort=False, dropna=False):
        keep_indices.append(int(group.index[0]))
        if len(group) > 1:
            duplicate_dates.append(date.date().isoformat())
            values = [_json_safe(value) for value in group["close"].tolist()]
            distinct = {json.dumps(value, sort_keys=True) for value in values}
            if len(distinct) > 1:
                conflicting_duplicates.append(
                    {"date": date.date().isoformat(), "values": values}
                )

    deduplicated = sorted_frame.loc[keep_indices].reset_index(drop=True)
    return deduplicated, {
        "input_non_monotonic": non_monotonic_input,
        "duplicate_dates_removed": duplicate_dates,
        "duplicate_date_count": len(duplicate_dates),
        "conflicting_duplicate_observations": conflicting_duplicates,
    }


def _date_ranges(dates: pd.DatetimeIndex) -> list[dict[str, object]]:
    """Compress consecutive business-date gaps into reportable intervals."""

    if dates.empty:
        return []

    ranges: list[dict[str, object]] = []
    start = previous = dates[0]
    count = 1
    business_day = pd.offsets.BDay()
    for date in dates[1:]:
        if date == previous + business_day:
            previous = date
            count += 1
            continue
        ranges.append(
            {
                "start_date": start.date().isoformat(),
                "end_date": previous.date().isoformat(),
                "weekday_count": count,
            }
        )
        start = previous = date
        count = 1
    ranges.append(
        {
            "start_date": start.date().isoformat(),
            "end_date": previous.date().isoformat(),
            "weekday_count": count,
        }
    )
    return ranges


def _unexpected_gap_report(valid_dates: pd.Series) -> dict[str, object]:
    """
    Report potential weekday gaps without pretending to know exchange holidays.

    Yahoo daily observations do not include weekends or market holidays. This
    check therefore reports missing weekdays as candidates for review rather
    than silently treating them as invalid observations.
    """

    if valid_dates.empty:
        return {
            "method": "weekday candidates between first and last valid observation",
            "potential_weekday_gap_count": 0,
            "potential_weekday_gap_intervals": [],
        }

    observed = pd.DatetimeIndex(valid_dates.to_numpy()).sort_values().unique()
    expected = pd.bdate_range(observed[0], observed[-1])
    potential_gaps = expected.difference(observed)
    return {
        "method": (
            "weekday candidates between first and last valid observation; "
            "exchange holidays remain explicit review candidates"
        ),
        "potential_weekday_gap_count": int(len(potential_gaps)),
        "potential_weekday_gap_intervals": _date_ranges(potential_gaps),
    }


def _numeric_quality(raw_close: pd.Series, parsed_close: pd.Series) -> dict[str, object]:
    """Validate numeric close values and flag large but still valid moves."""

    raw_values = pd.Series(raw_close.to_numpy())
    numeric_values = pd.Series(parsed_close.to_numpy())
    non_numeric = raw_values.notna() & numeric_values.isna()
    non_finite = numeric_values.notna() & ~np.isfinite(numeric_values)
    non_positive = numeric_values.notna() & np.isfinite(numeric_values) & (
        numeric_values <= 0
    )
    valid_positive = numeric_values[
        numeric_values.notna()
        & np.isfinite(numeric_values)
        & (numeric_values > 0)
    ]
    large_moves = valid_positive.pct_change(fill_method=None).abs() > 1.0

    return {
        "non_numeric_value_count": int(non_numeric.sum()),
        "non_finite_value_count": int(non_finite.sum()),
        "non_positive_value_count": int(non_positive.sum()),
        "daily_move_over_100pct_count": int(large_moves.sum()),
        "numeric_values_valid": not bool(
            non_numeric.any() or non_finite.any() or non_positive.any()
        ),
    }


def _coverage_for_fields(
    canonical: pd.DataFrame, fields: Sequence[str]
) -> dict[str, object]:
    if canonical.empty:
        return {
            "calendar_rows": 0,
            "complete_rows": 0,
            "missing_rows": 0,
            "complete_percentage": 0.0,
            "first_complete_date": None,
            "last_complete_date": None,
            "fields": list(fields),
        }

    complete = canonical.loc[:, list(fields)].notna().all(axis=1)
    complete_dates = canonical.loc[complete, "date"]
    return {
        "calendar_rows": int(len(canonical)),
        "complete_rows": int(complete.sum()),
        "missing_rows": int((~complete).sum()),
        "complete_percentage": round(float(complete.mean() * 100), 6),
        "first_complete_date": (
            complete_dates.iloc[0].date().isoformat()
            if not complete_dates.empty
            else None
        ),
        "last_complete_date": (
            complete_dates.iloc[-1].date().isoformat()
            if not complete_dates.empty
            else None
        ),
        "fields": list(fields),
    }


def build_coverage_report(canonical: pd.DataFrame) -> dict[str, object]:
    """Build series and lane coverage without removing any calendar rows."""

    per_series: dict[str, dict[str, object]] = {}
    for definition in SERIES:
        values = canonical[definition.canonical_field]
        valid = canonical.loc[values.notna(), "date"]
        total = len(canonical)
        missing_count = int(values.isna().sum())
        per_series[definition.canonical_field] = {
            "ticker": definition.ticker,
            "first_valid_date": (
                valid.iloc[0].date().isoformat() if not valid.empty else None
            ),
            "last_valid_date": (
                valid.iloc[-1].date().isoformat() if not valid.empty else None
            ),
            "observations": int(values.notna().sum()),
            "missing_count": missing_count,
            "missing_percentage": round(
                float((missing_count / total) * 100) if total else 0.0, 6
            ),
        }

    core_fields = [
        definition.canonical_field
        for definition in SERIES
        if definition.lane == "core"
    ]
    augmented_fields = [
        definition.canonical_field
        for definition in SERIES
        if definition.lane == "augmented"
    ]
    return {
        "per_series": per_series,
        "core_lane": _coverage_for_fields(canonical, core_fields),
        "augmented_lane": _coverage_for_fields(canonical, augmented_fields),
    }


def _canonical_checksum(canonical: pd.DataFrame) -> str:
    """Hash the exact stable CSV representation used for the canonical output."""

    payload = canonical.to_csv(index=False, lineterminator="\n", float_format="%.17g")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _snapshot_id(canonical_checksum: str, series: Mapping[str, Mapping[str, object]]) -> str:
    """Create a deterministic identity from canonical and stored raw payloads."""

    raw_checksums = {
        field: details["raw_payload_sha256"] for field, details in sorted(series.items())
    }
    payload = json.dumps(
        {"canonical_sha256": canonical_checksum, "raw_payload_sha256": raw_checksums},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_immutable_snapshot(
    output_path: Path,
    snapshot_id: str,
    canonical_path: Path,
    coverage_path: Path,
    manifest: Mapping[str, object],
) -> bool:
    """Create an append-only snapshot directory, never overwriting prior content."""

    snapshot_path = output_path / "snapshots" / snapshot_id
    expected_files = (
        snapshot_path / "canonical_daily.csv",
        snapshot_path / "coverage_report.json",
        snapshot_path / "metadata_manifest.json",
    )
    if snapshot_path.exists():
        if not all(path.exists() for path in expected_files):
            raise RuntimeError(
                f"Immutable snapshot directory is incomplete: {snapshot_path}"
            )
        return False

    snapshot_path.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(canonical_path, snapshot_path / canonical_path.name)
    shutil.copyfile(coverage_path, snapshot_path / coverage_path.name)
    shutil.copytree(output_path / "raw", snapshot_path / "raw")
    (snapshot_path / "metadata_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return True


def _write_failure_manifest(
    output_path: Path,
    retrieved_at: str,
    start: str,
    end: str,
    completed_series: Mapping[str, dict[str, object]],
    definition: SeriesDefinition,
    reason: str,
) -> None:
    """Persist explicit provenance when a required Yahoo ticker is unavailable."""

    failure_manifest = {
        "adapter": "spx_daily_regime_yahoo_adapter",
        "status": "failed",
        "source": SOURCE_NAME,
        "retrieved_at_utc": retrieved_at,
        "requested_start_date": start,
        "requested_end_date": end,
        "failure": {
            "source": SOURCE_NAME,
            "ticker": definition.ticker,
            "canonical_field": definition.canonical_field,
            "reason": reason,
        },
        "completed_series": completed_series,
        "planned_series": [
            {
                "source": SOURCE_NAME,
                "ticker": item.ticker,
                "canonical_field": item.canonical_field,
                "lane": item.lane,
            }
            for item in SERIES
        ],
        "canonical_output_written": False,
    }
    (output_path / "metadata_manifest.json").write_text(
        json.dumps(failure_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def ingest_yahoo_daily(
    start: str,
    end: str,
    output_dir: str | Path,
    fetcher: Fetcher = yahoo_download,
    allow_missing_optional: bool = False,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """
    Download, audit, align, and persist the daily canonical Yahoo Finance table.

    ``end`` follows Yahoo Finance's exclusive end-date convention. Each required
    ticker must return a raw Close column with at least one non-null observation.
    """

    output_path = Path(output_dir)
    raw_path = output_path / "raw"
    raw_path.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    canonical_parts: list[pd.DataFrame] = []
    series_manifest: dict[str, dict[str, object]] = {}
    unavailable_series: dict[str, dict[str, object]] = {}

    for definition in SERIES:
        try:
            raw = fetcher(definition.ticker, start, end)
        except Exception as error:
            reason = (
                f"Yahoo Finance download failed for {definition.ticker} "
                f"for requested range {start} to {end}: {error}"
            )
            if allow_missing_optional and definition.ticker != "^GSPC":
                unavailable_series[definition.canonical_field] = {
                    "source": SOURCE_NAME,
                    "ticker": definition.ticker,
                    "lane": definition.lane,
                    "reason": reason,
                }
                continue
            _write_failure_manifest(
                output_path,
                retrieved_at,
                start,
                end,
                series_manifest,
                definition,
                reason,
            )
            raise YahooDownloadError(reason) from error
        if not isinstance(raw, pd.DataFrame):
            reason = (
                f"Yahoo Finance download for {definition.ticker} did not return a DataFrame."
            )
            if allow_missing_optional and definition.ticker != "^GSPC":
                unavailable_series[definition.canonical_field] = {
                    "source": SOURCE_NAME,
                    "ticker": definition.ticker,
                    "lane": definition.lane,
                    "reason": reason,
                }
                continue
            _write_failure_manifest(
                output_path,
                retrieved_at,
                start,
                end,
                series_manifest,
                definition,
                reason,
            )
            raise YahooDownloadError(reason)
        if raw.empty:
            reason = (
                f"Yahoo Finance returned no rows for required ticker {definition.ticker} "
                f"for requested range {start} to {end}."
            )
            if allow_missing_optional and definition.ticker != "^GSPC":
                unavailable_series[definition.canonical_field] = {
                    "source": SOURCE_NAME,
                    "ticker": definition.ticker,
                    "lane": definition.lane,
                    "reason": reason,
                }
                continue
            _write_failure_manifest(
                output_path,
                retrieved_at,
                start,
                end,
                series_manifest,
                definition,
                reason,
            )
            raise YahooDownloadError(reason)

        raw_flat = _flatten_columns(raw)
        raw_with_date = raw_flat.copy()
        raw_with_date.insert(0, "date", _to_date_series(raw.index).dt.date.astype(str))
        raw_checksum = _write_csv(
            raw_with_date, raw_path / f"{definition.ticker.replace('^', '')}.csv"
        )

        try:
            close_column = _close_column(raw_flat)
        except YahooDownloadError as error:
            _write_failure_manifest(
                output_path,
                retrieved_at,
                start,
                end,
                series_manifest,
                definition,
                str(error),
            )
            raise
        parsed = pd.DataFrame(
            {
                # Build by position: Yahoo payload indexes can be date indexes
                # (including duplicate dates), while normalized dates use a
                # positional index.
                "date": _to_date_series(raw.index).to_numpy(),
                "close": pd.to_numeric(
                    raw_flat[close_column], errors="coerce"
                ).to_numpy(),
            }
        )
        numeric_quality = _numeric_quality(raw_flat[close_column], parsed["close"])
        if not numeric_quality["numeric_values_valid"]:
            reason = (
                f"Yahoo Finance returned invalid Close values for required ticker "
                f"{definition.ticker}: {numeric_quality}."
            )
            _write_failure_manifest(
                output_path,
                retrieved_at,
                start,
                end,
                series_manifest,
                definition,
                reason,
            )
            raise YahooDownloadError(reason)
        if parsed["close"].notna().sum() == 0:
            reason = (
                f"Yahoo Finance returned no usable Close values for required ticker "
                f"{definition.ticker} for requested range {start} to {end}."
            )
            if allow_missing_optional and definition.ticker != "^GSPC":
                unavailable_series[definition.canonical_field] = {
                    "source": SOURCE_NAME,
                    "ticker": definition.ticker,
                    "lane": definition.lane,
                    "reason": reason,
                }
                continue
            _write_failure_manifest(
                output_path,
                retrieved_at,
                start,
                end,
                series_manifest,
                definition,
                reason,
            )
            raise YahooDownloadError(reason)

        deduplicated, quality = _deduplicate_series(parsed)
        valid_dates = deduplicated.loc[deduplicated["close"].notna(), "date"]
        quality["numeric_validity"] = numeric_quality
        quality["unexpected_gaps"] = _unexpected_gap_report(valid_dates)
        canonical_parts.append(
            deduplicated.rename(columns={"close": definition.canonical_field})
        )

        series_manifest[definition.canonical_field] = {
            "source": SOURCE_NAME,
            "ticker": definition.ticker,
            "retrieved_at_utc": retrieved_at,
            "requested_start_date": start,
            "requested_end_date": end,
            "actual_first_observation_date": (
                valid_dates.iloc[0].date().isoformat() if not valid_dates.empty else None
            ),
            "actual_last_observation_date": (
                valid_dates.iloc[-1].date().isoformat() if not valid_dates.empty else None
            ),
            "raw_row_count": int(len(raw)),
            "deduplicated_row_count": int(len(deduplicated)),
            "valid_close_count": int(deduplicated["close"].notna().sum()),
            "raw_payload_file": str(
                Path("raw") / f"{definition.ticker.replace('^', '')}.csv"
            ),
            "raw_payload_sha256": raw_checksum,
            "data_quality": quality,
        }

    canonical = canonical_parts[0]
    for part in canonical_parts[1:]:
        canonical = canonical.merge(part, on="date", how="outer", sort=False)

    for column in CANONICAL_COLUMNS:
        if column not in canonical:
            canonical[column] = float("nan")
    canonical = canonical.loc[:, list(CANONICAL_COLUMNS)].sort_values(
        "date", kind="mergesort"
    ).reset_index(drop=True)
    if not canonical["date"].is_monotonic_increasing:
        raise RuntimeError("Canonical daily table is not monotonic ascending by date.")
    if canonical["date"].duplicated().any():
        raise RuntimeError("Canonical daily table contains duplicate trading dates.")

    canonical_to_write = canonical.copy()
    canonical_to_write["date"] = canonical_to_write["date"].dt.date.astype(str)
    canonical_path = output_path / "canonical_daily.csv"
    canonical_checksum = _write_csv(canonical_to_write, canonical_path)
    coverage = build_coverage_report(canonical)
    coverage_path = output_path / "coverage_report.json"
    coverage_path.write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest: dict[str, object] = {
        "adapter": "spx_daily_regime_yahoo_adapter",
        "status": "degraded" if unavailable_series else "complete",
        "source": SOURCE_NAME,
        "retrieved_at_utc": retrieved_at,
        "requested_start_date": start,
        "requested_end_date": end,
        "calendar_alignment": "outer join on observed calendar date only",
        "missing_value_policy": "Missing Yahoo observations remain explicit null/NaN; no forward fill or interpolation.",
        "canonical_file": "canonical_daily.csv",
        "canonical_schema": list(CANONICAL_COLUMNS),
        "canonical_row_count": int(len(canonical)),
        "canonical_first_date": (
            canonical_to_write["date"].iloc[0] if not canonical.empty else None
        ),
        "canonical_last_date": (
            canonical_to_write["date"].iloc[-1] if not canonical.empty else None
        ),
        "canonical_sha256": canonical_checksum,
        "coverage_report_file": coverage_path.name,
        "series": series_manifest,
        "unavailable_series": unavailable_series,
        "coverage": coverage,
        "calendar_quality": {
            "canonical_dates_monotonic_ascending": True,
            "canonical_duplicate_dates": [],
            "alignment_method": "outer join on observed calendar date only",
        },
    }
    snapshot_id = _snapshot_id(canonical_checksum, series_manifest)
    manifest["snapshot"] = {
        "snapshot_id": snapshot_id,
        "relative_path": str(Path("snapshots") / snapshot_id),
        "immutable": True,
    }
    manifest_path = output_path / "metadata_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    snapshot_manifest = dict(manifest)
    snapshot_manifest["snapshot"] = {**manifest["snapshot"], "created": True}
    snapshot_created = _write_immutable_snapshot(
        output_path,
        snapshot_id,
        canonical_path,
        coverage_path,
        snapshot_manifest,
    )
    manifest["snapshot"] = {**manifest["snapshot"], "created": snapshot_created}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return canonical, manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and audit Yahoo Finance daily data for SPX regime research."
    )
    parser.add_argument("--start", required=True, help="Requested start date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True, help="Requested end date (YYYY-MM-DD).")
    parser.add_argument(
        "--output-dir",
        default=Path(__file__).resolve().parents[1] / "data" / "daily_regime",
        type=Path,
        help="Directory for canonical_daily.csv and audit metadata.",
    )
    args = parser.parse_args(argv)
    canonical, manifest = ingest_yahoo_daily(args.start, args.end, args.output_dir)
    print(
        json.dumps(
            {
                "canonical_rows": len(canonical),
                "canonical_sha256": manifest["canonical_sha256"],
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())