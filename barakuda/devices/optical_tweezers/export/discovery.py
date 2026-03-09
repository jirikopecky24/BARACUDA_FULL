"""
Dataset artifact discovery for Export.

Inspects dataset_root/analysis/ and returns a list of present artifacts
with id, label, and relative path. Used by the Export tab to build
dynamic checkboxes and drive export execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# Canonical artifact definitions: (id, label, path under analysis/)
_ANALYSIS_ARTIFACTS = [
    ("trajectory_csv", "Trajectory CSV", "trajectory.csv"),
    ("tracking_csv", "Tracking CSV", "tracking.csv"),
    ("psd_csv", "PSD spectrum CSV", "psd.csv"),
    ("qc_report", "QC report", "qc.json"),
    ("run_json", "Run manifest", "run.json"),
]


def discover_analysis_artifacts(dataset_root: Path | str) -> list[dict[str, Any]]:
    """
    Discover analysis artifacts present under dataset_root/analysis/.

    Input:
        dataset_root: path to dataset root (e.g. runs/acquisition/test5/)

    Returns:
        List of dicts with keys: id, label, path.
        path is relative to dataset_root (e.g. "analysis/trajectory.csv").
        Only artifacts that exist on disk are included.
    """
    root = Path(dataset_root).resolve()
    analysis_dir = root / "analysis"
    if not analysis_dir.is_dir():
        return []

    result: list[dict[str, Any]] = []
    for artifact_id, label, rel_name in _ANALYSIS_ARTIFACTS:
        full_path = analysis_dir / rel_name
        if full_path.is_file():
            result.append({
                "id": artifact_id,
                "label": label,
                "path": f"analysis/{rel_name}",
            })
    return result
