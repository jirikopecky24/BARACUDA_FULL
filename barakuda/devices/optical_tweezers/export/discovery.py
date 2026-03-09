"""
Dataset artifact discovery for Export.

Inspects dataset_root for analysis outputs (analysis/ or module/ot/ layout)
and returns a list of present artifacts with id, label, and relative path.
Used by the Export tab to build dynamic checkboxes and drive export execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _analysis_roots(root: Path) -> list[Path]:
    """Return candidate analysis directories (same order as manifest resolution)."""
    candidates = [
        root / "analysis",
        root / "module" / "ot",
    ]
    return [p for p in candidates if p.is_dir()]


def _all_files_under(
    base: Path,
    root: Path,
    patterns: list[str],
    subdirs: list[str] | None = None,
) -> list[Path]:
    """Return all existing files matching any pattern under base (and optional subdirs). Paths relative to root, deduplicated."""
    search_dirs: list[Path] = [base]
    if subdirs:
        for sd in subdirs:
            d = base / sd
            if d.is_dir():
                search_dirs.append(d)
    seen: set[Path] = set()
    out: list[Path] = []
    for search_dir in search_dirs:
        for pattern in patterns:
            for path in sorted(search_dir.glob(pattern)):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    out.append(path)
    return out


def discover_analysis_artifacts(dataset_root: Path | str) -> list[dict[str, Any]]:
    """
    Discover analysis artifacts present under dataset_root.

    Returns one candidate per concrete exportable file. Each candidate has unique id,
    one path, and a user-readable label. Supports canonical layout (dataset_root/analysis/)
    and legacy layout (dataset_root/module/ot/), including stem-prefixed filenames and
    subdirs (tracking/, physics/, audit/, ot_v2_shadow/).

    Input:
        dataset_root: path to dataset root (item root, e.g. runs/.../item_id/).

    Returns:
        List of dicts with keys: id, label, path.
        path is relative to dataset_root. Only files that exist on disk are included.
        Canonical outputs (.json, .xlsx) are excluded.
    """
    root = Path(dataset_root).resolve()
    analysis_roots = _analysis_roots(root)
    if not analysis_roots:
        return []

    result: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    subdirs = ["tracking", "physics", "audit", "ot_v2_shadow"]

    # Type definitions: (logical_key, label_prefix, patterns). Each matching file becomes one candidate.
    type_defs = [
        ("run_json", "Run manifest", ["run.json"]),
        ("trajectory_csv", "Trajectory CSV", ["trajectory.csv", "*_trajectory.csv"]),
        ("tracking_csv", "Tracking CSV", ["tracking.csv", "*tracking*.csv", "tracking/*.csv"]),
        ("psd_csv", "PSD spectrum CSV", ["psd.csv", "*_psd_x.csv", "*_psd_y.csv", "*_psd*.csv"]),
        ("qc_report", "QC report", ["qc.json", "*_qc.json"]),
    ]

    for analysis_dir in analysis_roots:
        try:
            analysis_dir.relative_to(root)
        except ValueError:
            continue

        for logical_key, label_prefix, patterns in type_defs:
            if logical_key == "run_json":
                # run.json only at analysis root
                run_json = analysis_dir / "run.json"
                if run_json.is_file():
                    path_str = str(run_json.relative_to(root)).replace("\\", "/")
                    if path_str not in seen_paths:
                        seen_paths.add(path_str)
                        result.append({
                            "id": path_str,
                            "label": f"{label_prefix} — {run_json.name}",
                            "path": path_str,
                        })
                continue

            files = _all_files_under(analysis_dir, root, patterns, subdirs)
            for fp in files:
                path_str = str(fp.relative_to(root)).replace("\\", "/")
                if path_str in seen_paths:
                    continue
                # tracking: skip if same path as any trajectory already in result
                if logical_key == "tracking_csv" and any(
                    r.get("path") == path_str for r in result
                ):
                    continue
                seen_paths.add(path_str)
                result.append({
                    "id": path_str,
                    "label": f"{label_prefix} — {fp.name}",
                    "path": path_str,
                })

    # Policy: return only OPTIONAL EXPORT artifacts. Canonical outputs (.json, .xlsx)
    # must not be offered in the Export tab.
    _CANONICAL_SUFFIXES = (".json", ".xlsx")
    result = [
        r for r in result
        if Path(r["path"]).suffix.lower() not in _CANONICAL_SUFFIXES
    ]

    # Stable order: by type priority then by path
    order = {aid: i for i, (aid, _, _) in enumerate(type_defs)}
    result.sort(key=lambda r: (order.get(_path_to_logical_key(r["path"]), 99), r["path"]))
    return result


def _path_to_logical_key(path_str: str) -> str:
    """Map a relative path to a logical artifact key for ordering."""
    p = Path(path_str)
    name = p.name.lower()
    if name == "run.json":
        return "run_json"
    if "trajectory" in name and p.suffix.lower() == ".csv":
        return "trajectory_csv"
    if "tracking" in name and p.suffix.lower() == ".csv":
        return "tracking_csv"
    if "psd" in name and p.suffix.lower() == ".csv":
        return "psd_csv"
    if "qc" in name and p.suffix.lower() == ".json":
        return "qc_report"
    return ""
