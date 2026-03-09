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


def discover_analysis_artifacts(dataset_root: Path | str) -> list[dict[str, Any]]:
    """
    Discover all analysis files under dataset_root for Export.

    Returns one candidate per concrete file under the analysis directory(ies).
    Each candidate has unique path-based id, label, and path. Includes .json,
    .xlsx, .csv, .png, and all other real files; directories are not returned.

    Input:
        dataset_root: path to dataset root (item root, e.g. runs/.../item_id/).

    Returns:
        List of dicts with keys: id, label, path.
        path is relative to dataset_root. Only existing files are included.
    """
    root = Path(dataset_root).resolve()
    analysis_roots = _analysis_roots(root)
    if not analysis_roots:
        return []

    result: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for analysis_dir in analysis_roots:
        try:
            analysis_dir.relative_to(root)
        except ValueError:
            continue

        for f in sorted(analysis_dir.rglob("*")):
            if not f.is_file():
                continue
            try:
                path_str = str(f.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            if path_str in seen_paths:
                continue
            seen_paths.add(path_str)
            result.append({
                "id": path_str,
                "label": path_str,
                "path": path_str,
            })

    result.sort(key=lambda r: r["path"])
    return result
