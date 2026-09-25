"""Read a research replay only if it matches the currently verified real snapshot."""

import hashlib
import json
from pathlib import Path


def load_shadow_report(root: Path, signal_id: str, input_id: str,
                       signal_root: Path) -> tuple[dict, str]:
    research = root / signal_id
    manifest_path = research / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("No shadow research report matches the current verified signal snapshot.")
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("signal_snapshot_id") != signal_id
            or manifest.get("input_snapshot_id") != input_id
            or manifest.get("status") != "RESEARCH RECONSTRUCTION / SHADOW ONLY"):
        raise ValueError("Shadow report provenance does not match the verified signal.")
    sources = {
        "source_signal_sha256": signal_root / "snapshots" / signal_id / "signal_history.csv",
        "source_canonical_sha256": signal_root / "daily_data" / "snapshots" / input_id / "canonical_daily.csv",
    }
    for key, path in sources.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[key]:
            raise ValueError(f"Shadow report source checksum differs: {key}.")
    for file, digest in manifest["files"].items():
        if file not in ("reconstructed_states.csv", "oos_predictions.csv", "report.json", "report.md"):
            raise ValueError("Unexpected shadow report output.")
        if hashlib.sha256((research / file).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Shadow report checksum differs: {file}.")
    report = json.loads((research / "report.json").read_text())
    if report["signal_snapshot_id"] != signal_id or report["input_snapshot_id"] != input_id:
        raise ValueError("Shadow report body does not match the verified signal.")
    return report, (research / "report.md").read_text()