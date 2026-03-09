from __future__ import annotations

"""
OT Dataset Manifest Loader
==========================
Reads item.json and resolves all relevant paths for a single OT dataset item.

Supports both:
  - canonical layout (target):  acquisition/ + analysis/ + exports/
  - legacy layout (current):    raw/ + module/ot/

All resolution is read-only. Paths that cannot be found are left as None.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class OTItemManifest:
    """Resolved paths for a single OT dataset item."""

    item_root: Path
    item_json_path: Path

    # Acquisition
    video_path: Optional[Path] = None       # resolved video (.raw, .avi, …)
    meta_path: Optional[Path] = None        # acquisition metadata JSON
    timestamps_path: Optional[Path] = None  # acquisition timestamps CSV

    # Analysis
    analysis_dir: Optional[Path] = None
    run_json_path: Optional[Path] = None
    trajectory_path: Optional[Path] = None
    qc_json_path: Optional[Path] = None
    preview_report_path: Optional[Path] = None

    # Exports
    exports_dir: Optional[Path] = None

    # Raw manifest payload (for callers that need schema_version, batch_id, etc.)
    raw: dict = field(default_factory=dict)


def load_item_manifest(item_json_path: Path) -> OTItemManifest:
    """
    Load and resolve an OT dataset item from item.json.

    Resolution priority:
      1. Canonical  acquisition/ folder
      2. Legacy     raw/ folder (current batch_controller output)
      3. Absolute   source_input_path recorded in the manifest

    Returns an OTItemManifest with all resolvable paths populated.
    Unresolvable paths are left as None — callers should check before use.
    """
    item_json_path = Path(item_json_path).resolve()
    item_root = item_json_path.parent

    raw = json.loads(item_json_path.read_text(encoding="utf-8"))

    m = OTItemManifest(
        item_root=item_root,
        item_json_path=item_json_path,
        raw=raw,
    )

    # ── Acquisition video ───────────────────────────────────────────────────
    m.video_path = _resolve_video(item_root, raw)

    # ── Acquisition metadata JSON ────────────────────────────────────────────
    m.meta_path = _resolve_meta(item_root, raw, m.video_path)

    # ── Acquisition timestamps CSV ───────────────────────────────────────────
    m.timestamps_path = _first_existing(item_root, [
        "acquisition/video_timestamps.csv",
        "raw/video_timestamps.csv",
    ])

    # ── Analysis directory ───────────────────────────────────────────────────
    m.analysis_dir = _resolve_analysis_dir(item_root, raw)

    if m.analysis_dir is not None:
        ad = m.analysis_dir
        m.run_json_path = _first_existing(ad, ["run.json"])
        m.qc_json_path  = _first_existing(ad, ["qc.json"])

        m.trajectory_path = (
            _first_existing(ad, ["trajectory.csv", "tracking/trajectory.csv"])
            or _glob_first(ad, "*_trajectory.csv")
        )

        m.preview_report_path = _first_existing(ad, ["preview_report.json"])

    # ── Exports directory ────────────────────────────────────────────────────
    exp = _first_existing(item_root, ["exports", "module/ot/exports"])
    if exp is not None and exp.is_dir():
        m.exports_dir = exp

    return m


# ── internal helpers ────────────────────────────────────────────────────────

_VIDEO_EXTENSIONS = {".raw", ".avi", ".mp4", ".mov", ".mkv", ".m4v"}


def _resolve_video(item_root: Path, raw: dict) -> Optional[Path]:
    """Resolve the acquisition video file."""
    # 1. Canonical acquisition/ folder — first video file found
    acq_dir = item_root / "acquisition"
    if acq_dir.is_dir():
        hit = _first_video_in_dir(acq_dir)
        if hit is not None:
            return hit

    # 2. Manifest field archived_raw_video (relative to item_root)
    archived = raw.get("archived_raw_video")
    if archived:
        p = item_root / archived
        if p.exists():
            return p

    # 3. Legacy raw/ folder scan
    raw_dir = item_root / "raw"
    if raw_dir.is_dir():
        hit = _first_video_in_dir(raw_dir)
        if hit is not None:
            return hit

    # 4. source_input_path (absolute; valid if disk layout unchanged)
    src = raw.get("source_input_path")
    if src:
        p = Path(src)
        if p.exists():
            return p

    return None


def _resolve_meta(
    item_root: Path,
    raw: dict,
    video_path: Optional[Path],
) -> Optional[Path]:
    """Resolve the acquisition metadata JSON."""
    # 1. Canonical acquisition/video_meta.json
    p = item_root / "acquisition" / "video_meta.json"
    if p.exists():
        return p

    # 2. Manifest field archived_meta (relative to item_root)
    archived = raw.get("archived_meta")
    if archived:
        p = item_root / archived
        if p.exists():
            return p

    # 3. Sibling of the resolved video file
    if video_path is not None:
        for suffix in (
            video_path.stem + "_meta.json",
            video_path.name + "_meta.json",
            "video_meta.json",
        ):
            p = video_path.parent / suffix
            if p.exists():
                return p

    return None


def _resolve_analysis_dir(item_root: Path, raw: dict) -> Optional[Path]:
    """Resolve the analysis output directory."""
    # 1. Canonical analysis/ folder
    p = item_root / "analysis"
    if p.is_dir():
        return p

    # 2. Legacy module/ot/ (current batch_controller layout)
    p = item_root / "module" / "ot"
    if p.is_dir():
        return p

    # 3. Absolute run_dir recorded in the manifest
    run_dir_str = raw.get("run_dir")
    if run_dir_str:
        p = Path(run_dir_str)
        if p.is_dir():
            return p

    return None


def _first_existing(base: Path, rel_paths: list[str]) -> Optional[Path]:
    for rel in rel_paths:
        p = (base / rel).resolve()
        if p.exists():
            return p
    return None


def _first_video_in_dir(directory: Path) -> Optional[Path]:
    for ext in (".raw", ".avi", ".mp4", ".mov", ".mkv", ".m4v"):
        for f in directory.iterdir():
            if f.is_file() and f.suffix.lower() == ext:
                return f
    return None


def _glob_first(directory: Path, pattern: str) -> Optional[Path]:
    try:
        matches = sorted(directory.glob(pattern))
        return matches[0] if matches else None
    except Exception:
        return None
