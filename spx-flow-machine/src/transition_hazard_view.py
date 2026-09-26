"""Snapshot-locked reader for the transition research, never for PM decisions."""

import hashlib
import json
from pathlib import Path


def load_transition_report(root: Path, signal_id: str, input_id: str,
                           source: Path) -> tuple[dict, str]:
    directory = root / signal_id
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest.get("status") != "TRANSITION RESEARCH / SHADOW ONLY"
            or manifest.get("signal_snapshot_id") != signal_id
            or manifest.get("input_snapshot_id") != input_id):
        raise ValueError("Transition research does not match the current verified signal.")
    paths = {
        "source_signal_sha256": source / "snapshots" / signal_id / "signal_history.csv",
        "source_canonical_sha256": source / "daily_data" / "snapshots" / input_id / "canonical_daily.csv",
    }
    for name, path in paths.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[name]:
            raise ValueError(f"Transition research source checksum mismatch: {name}")
    expected = {"research_states.csv", "oos_predictions.csv", "de_risk_entry_leads.csv",
                "report.json", "report.md"}
    if set(manifest["files"]) != expected:
        raise ValueError("Transition research file list is incomplete.")
    for name, digest in manifest["files"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Transition research output checksum mismatch: {name}")
    report = json.loads((directory / "report.json").read_text())
    if report["signal_snapshot_id"] != signal_id or report["input_snapshot_id"] != input_id:
        raise ValueError("Transition research report body does not match its source.")
    return report, (directory / "report.md").read_text()