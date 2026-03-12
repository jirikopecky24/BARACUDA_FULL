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


def discover_analysis_artifacts(
    dataset_root: Path | str,
    analysis_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    Discover all analysis files under dataset_root for Export.

    Returns one candidate per concrete file under the analysis directory(ies).
    Each candidate has unique path-based id, label, and path. Includes .json,
    .xlsx, .csv, .png, and all other real files; directories are not returned.

    Input:
        dataset_root: path to dataset root (item root, e.g. runs/.../item_id/).
        analysis_dir: optional resolved analysis directory. Can point outside
            dataset_root when a source dataset links to an OT output elsewhere.

    Returns:
        List of dicts with keys: id, label, path, analysis_rel_path.
        path is the display/export path. Only existing files are included.
    """
    root = Path(dataset_root).resolve()
    if analysis_dir is not None:
        analysis_roots = [Path(analysis_dir).resolve()]
    else:
        analysis_roots = _analysis_roots(root)
    if not analysis_roots:
        return []

    result: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for analysis_dir in analysis_roots:
        for f in sorted(analysis_dir.rglob("*")):
            if not f.is_file():
                continue
            try:
                rel_analysis = str(f.relative_to(analysis_dir)).replace("\\", "/")
            except ValueError:
                continue
            try:
                path_str = str(f.relative_to(root)).replace("\\", "/")
            except ValueError:
                path_str = f"analysis/{rel_analysis}"
            if path_str in seen_paths:
                continue
            seen_paths.add(path_str)
            result.append({
                "id": path_str,
                "label": path_str,
                "path": path_str,
                "analysis_rel_path": rel_analysis,
            })

    result.sort(key=lambda r: r["path"])
    return result
