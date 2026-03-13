"""Dataset artifact discovery for AFM export."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _analysis_roots(root: Path) -> list[Path]:
    candidates = [
        root / "analysis",
    ]
    return [p for p in candidates if p.is_dir()]


def discover_analysis_artifacts(
    dataset_root: Path | str,
    analysis_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    root = Path(dataset_root).resolve()
    if analysis_dir is not None:
        analysis_roots = [Path(analysis_dir).resolve()]
    else:
        analysis_roots = _analysis_roots(root)
    if not analysis_roots:
        return []

    result: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for analysis_root in analysis_roots:
        for file_path in sorted(analysis_root.rglob("*")):
            if not file_path.is_file():
                continue
            try:
                rel_analysis = str(file_path.relative_to(analysis_root)).replace("\\", "/")
            except ValueError:
                continue
            try:
                path_str = str(file_path.relative_to(root)).replace("\\", "/")
            except ValueError:
                path_str = f"analysis/{rel_analysis}"
            if path_str in seen_paths:
                continue
            seen_paths.add(path_str)
            result.append(
                {
                    "id": path_str,
                    "label": path_str,
                    "path": path_str,
                    "analysis_rel_path": rel_analysis,
                }
            )

    result.sort(key=lambda row: row["path"])
    return result
