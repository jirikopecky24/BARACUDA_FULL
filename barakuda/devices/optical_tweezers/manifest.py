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
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


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

        # qc: prefer manifest field, then scan
        _an = raw.get("analysis", {})
        if _an.get("qc"):
            _p = (item_root / _an["qc"])
            m.qc_json_path = _p if _p.exists() else _first_existing(ad, ["qc.json"]) or _glob_first(ad, "*_qc.json")
        else:
            m.qc_json_path = _first_existing(ad, ["qc.json"]) or _glob_first(ad, "*_qc.json")

        # trajectory: prefer manifest field, then scan
        if _an.get("trajectory"):
            _p = (item_root / _an["trajectory"])
            m.trajectory_path = _p if _p.exists() else (
                _first_existing(ad, ["trajectory.csv", "tracking/trajectory.csv"])
                or _glob_first(ad, "*_trajectory.csv")
            )
        else:
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
    # 0. Canonical acquisition.video field (new schema)
    acq_video = raw.get("acquisition", {}).get("video")
    if acq_video:
        p = item_root / acq_video
        if p.exists():
            return p

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
    # 0. Canonical acquisition.meta field (new schema)
    acq_meta = raw.get("acquisition", {}).get("meta")
    if acq_meta:
        p = item_root / acq_meta
        if p.exists():
            return p

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
    # 0. Canonical analysis.dir field (new schema, relative to item_root)
    an_dir = raw.get("analysis", {}).get("dir")
    if an_dir:
        p = item_root / an_dir
        if p.is_dir():
            return p

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


def build_item_manifest_payload(
    item_root: Path,
    item_id: str,
    *,
    module: str = "ot",
    batch_id: Optional[str] = None,
    source_input_path: Optional[str] = None,
    acquisition_video: Optional[Path] = None,
    acquisition_meta: Optional[Path] = None,
    acquisition_timestamps: Optional[Path] = None,
    fps: Optional[float] = None,
    width_px: Optional[int] = None,
    height_px: Optional[int] = None,
    frame_count: Optional[int] = None,
    roi: Optional[list] = None,
    analysis_dir: Optional[Path] = None,
    um_per_px: Optional[float] = None,
    um_per_px_source: Optional[str] = None,
    status: str = "analyzed",
    existing_payload: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Build (or update) the canonical item.json payload.

    All path arguments should be absolute.  Paths inside item_root are stored
    as relative strings; paths outside are stored as absolute strings.

    If existing_payload is provided, new fields are merged on top of it so that
    existing metadata (batch_id, created_at, etc.) is preserved.
    """
    item_root = Path(item_root)
    now = datetime.now().isoformat(timespec="seconds")

    def _rel(p: Optional[Path]) -> Optional[str]:
        if p is None:
            return None
        try:
            return str(Path(p).relative_to(item_root)).replace("\\", "/")
        except ValueError:
            return str(p)

    payload: dict[str, Any] = dict(existing_payload) if existing_payload else {}

    # ── Core identity ────────────────────────────────────────────────────────
    payload.setdefault("schema_version", 1)
    payload.setdefault("module", module)
    payload.setdefault("item_id", item_id)
    payload.setdefault("created_at", now)
    payload["updated_at"] = now
    payload["status"] = status

    if batch_id is not None:
        payload["batch_id"] = batch_id
    if source_input_path is not None:
        payload["source_input_path"] = str(source_input_path)

    # ── Acquisition section ──────────────────────────────────────────────────
    acq: dict[str, Any] = dict(payload.get("acquisition") or {})

    if acquisition_video is not None:
        rel_v = _rel(acquisition_video)
        if rel_v:
            acq["video"] = rel_v
            payload["archived_raw_video"] = rel_v   # backward-compat

    if acquisition_meta is not None:
        rel_m = _rel(acquisition_meta)
        if rel_m:
            acq["meta"] = rel_m
            payload["archived_meta"] = rel_m         # backward-compat

    if acquisition_timestamps is not None:
        rel_t = _rel(acquisition_timestamps)
        if rel_t:
            acq["timestamps"] = rel_t

    if fps is not None:
        acq["fps"] = float(fps)
    if width_px is not None:
        acq["width_px"] = int(width_px)
    if height_px is not None:
        acq["height_px"] = int(height_px)
    if frame_count is not None:
        acq["frame_count"] = int(frame_count)
    if roi is not None:
        acq["roi"] = list(roi)

    if acq:
        payload["acquisition"] = acq

    # ── Analysis section ─────────────────────────────────────────────────────
    if analysis_dir is not None:
        analysis_dir = Path(analysis_dir)
        rel_ad = _rel(analysis_dir)
        an: dict[str, Any] = dict(payload.get("analysis") or {})
        if rel_ad:
            an["dir"] = rel_ad
            payload["analysis_dir"] = rel_ad         # backward-compat
        payload["run_dir"] = str(analysis_dir)       # backward-compat

        if analysis_dir.is_dir():
            for f in analysis_dir.glob("run.json"):
                an["run_json"] = _rel(f)
            for f in sorted(analysis_dir.rglob("*_trajectory.csv")):
                an["trajectory"] = _rel(f)
                break
            for f in sorted(analysis_dir.rglob("*_qc.json")):
                an["qc"] = _rel(f)
                break
            for f in sorted(analysis_dir.rglob("*_ot_summary.json")):
                an["summary"] = _rel(f)
                break

        payload["analysis"] = an

    # ── Calibration section ──────────────────────────────────────────────────
    if um_per_px is not None:
        cal: dict[str, Any] = dict(payload.get("calibration") or {})
        cal["um_per_px"] = float(um_per_px)
        if um_per_px_source:
            cal["source"] = str(um_per_px_source)
        payload["calibration"] = cal

    # ── Artifacts inventory ──────────────────────────────────────────────────
    inv: list[str] = []
    if item_root.is_dir():
        for ap in sorted(item_root.rglob("*")):
            if ap.is_file():
                try:
                    inv.append(str(ap.relative_to(item_root)).replace("\\", "/"))
                except Exception:
                    pass
    payload["artifacts_inventory"] = inv

    return payload


def is_item_json(path: Path) -> bool:
    """Return True if path points to an OT dataset item.json manifest."""
    path = Path(path)
    return path.name == "item.json" and path.is_file()


def _glob_first(directory: Path, pattern: str) -> Optional[Path]:
    try:
        matches = sorted(directory.glob(pattern))
        return matches[0] if matches else None
    except Exception:
        return None
