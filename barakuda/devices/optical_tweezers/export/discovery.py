"""
Dataset artifact discovery for Export.

Inspects dataset_root for analysis outputs (analysis/ or module/ot/ layout)
and returns a list of present artifacts with id, label, and relative path.
Used by the Export tab to build dynamic checkboxes and drive export execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# (id, label) — path is discovered by pattern
_ARTIFACT_DEFS = [
    ("trajectory_csv", "Trajectory CSV"),
    ("tracking_csv", "Tracking CSV"),
    ("psd_csv", "PSD spectrum CSV"),
    ("qc_report", "QC report"),
    ("run_json", "Run manifest"),
]


def _analysis_roots(root: Path) -> list[Path]:
    """Return candidate analysis directories (same order as manifest resolution)."""
    candidates = [
        root / "analysis",
        root / "module" / "ot",
    ]
    return [p for p in candidates if p.is_dir()]


def _first_file_under(
    base: Path,
    root: Path,
    patterns: list[str],
    subdirs: list[str] | None = None,
) -> Path | None:
    """Return first existing file matching any pattern under base (and optional subdirs). Path relative to root."""
    search_dirs: list[Path] = [base]
    if subdirs:
        for sd in subdirs:
            d = base / sd
            if d.is_dir():
                search_dirs.append(d)
    for search_dir in search_dirs:
        for pattern in patterns:
            for path in sorted(search_dir.glob(pattern)):
                if path.is_file():
                    return path
    return None


def discover_analysis_artifacts(dataset_root: Path | str) -> list[dict[str, Any]]:
    """
    Discover analysis artifacts present under dataset_root.

    Supports canonical layout (dataset_root/analysis/) and legacy layout
    (dataset_root/module/ot/), including stem-prefixed filenames and
    subdirs (tracking/, physics/, audit/, ot_v2_shadow/).

    Input:
        dataset_root: path to dataset root (item root, e.g. runs/.../item_id/).

    Returns:
        List of dicts with keys: id, label, path.
        path is relative to dataset_root. Only artifacts that exist on disk are included.
    """
    root = Path(dataset_root).resolve()
    analysis_roots = _analysis_roots(root)
    if not analysis_roots:
        return []

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    subdirs = ["tracking", "physics", "audit", "ot_v2_shadow"]

    for analysis_dir in analysis_roots:
        try:
            rel_prefix = analysis_dir.relative_to(root)
        except ValueError:
            continue

        # run.json — root of analysis dir only
        run_json = analysis_dir / "run.json"
        if run_json.is_file() and "run_json" not in seen_ids:
            seen_ids.add("run_json")
            result.append({
                "id": "run_json",
                "label": "Run manifest",
                "path": str(rel_prefix / "run.json").replace("\\", "/"),
            })

        # trajectory_csv: fixed name or *_trajectory.csv
        if "trajectory_csv" not in seen_ids:
            found = _first_file_under(
                analysis_dir, root,
                ["trajectory.csv", "*_trajectory.csv"],
                subdirs,
            )
            if found is not None:
                seen_ids.add("trajectory_csv")
                result.append({
                    "id": "trajectory_csv",
                    "label": "Trajectory CSV",
                    "path": str(found.relative_to(root)).replace("\\", "/"),
                })

        # tracking_csv: fixed name or *tracking*.csv (skip if same as trajectory)
        if "tracking_csv" not in seen_ids:
            found = _first_file_under(
                analysis_dir, root,
                ["tracking.csv", "*tracking*.csv", "tracking/*.csv"],
                subdirs,
            )
            if found is not None:
                rel = found.relative_to(root)
                path_str = str(rel).replace("\\", "/")
                # avoid duplicate with trajectory
                if not any(r.get("path") == path_str for r in result):
                    seen_ids.add("tracking_csv")
                    result.append({
                        "id": "tracking_csv",
                        "label": "Tracking CSV",
                        "path": path_str,
                    })

        # psd_csv: fixed name or *_psd*.csv (not calibration.csv)
        if "psd_csv" not in seen_ids:
            found = _first_file_under(
                analysis_dir, root,
                ["psd.csv", "*_psd_x.csv", "*_psd_y.csv", "*_psd*.csv"],
                subdirs,
            )
            if found is not None:
                seen_ids.add("psd_csv")
                result.append({
                    "id": "psd_csv",
                    "label": "PSD spectrum CSV",
                    "path": str(found.relative_to(root)).replace("\\", "/"),
                })

        # qc_report: qc.json or *_qc.json
        if "qc_report" not in seen_ids:
            found = _first_file_under(
                analysis_dir, root,
                ["qc.json", "*_qc.json"],
                subdirs,
            )
            if found is not None:
                seen_ids.add("qc_report")
                result.append({
                    "id": "qc_report",
                    "label": "QC report",
                    "path": str(found.relative_to(root)).replace("\\", "/"),
                })

        # run_json already handled above
        if len(seen_ids) >= 5:
            break

    # Policy: return only OPTIONAL EXPORT artifacts. Canonical outputs (.json, .xlsx)
    # must not be offered in the Export tab.
    _CANONICAL_SUFFIXES = (".json", ".xlsx")
    result = [
        r for r in result
        if Path(r["path"]).suffix.lower() not in _CANONICAL_SUFFIXES
    ]

    # Return in stable order matching original artifact order
    order = {aid: i for i, (aid, _) in enumerate(_ARTIFACT_DEFS)}
    result.sort(key=lambda r: order.get(r["id"], 99))
    return result
