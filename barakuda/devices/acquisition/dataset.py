"""Acquisition dataset home — canonical item.json writer.

After a recording completes, call create_acquisition_dataset_home() to
materialise a canonical dataset item under runs/acquisition/<item_id>/:

    runs/
      acquisition/
        <item_id>/
          item.json
          acquisition/
            video.raw  (or video.avi)
            video_meta.json
            video_timestamps.csv   (if present)
            qc.json                (if present)

Files are copied from the user-chosen recording directory into the
canonical acquisition/ subfolder.  The originals are left in place for
backward compatibility.  If a file was already copied (e.g. on re-run),
the copy is skipped.

item.json is written (or updated in place) with:
  schema_version, module, item_id, created_at, source_type,
  acquisition (video, meta, timestamps, qc, fps_effective,
               pixel_format, roi, frame_count), status
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_SCHEMA_VERSION = 1


def create_acquisition_dataset_home(
    *,
    item_id: str,
    video_path: Path,
    meta_path: Optional[Path],
    timestamps_path: Optional[Path],
    qc_path: Optional[Path],
    runs_root: Path,
    fps_effective: Optional[float] = None,
    pixel_format: Optional[str] = None,
    roi: Optional[dict] = None,
    frame_count: Optional[int] = None,
) -> Path:
    """Create (or update) the canonical dataset home for one acquisition output.

    Copies acquisition files into <runs_root>/acquisition/<item_id>/acquisition/
    and writes item.json at the item_root level.

    Safe to call more than once: existing destination files are not re-copied,
    and item.json is merged in place (preserving created_at and any extra keys).

    Returns item_root (the directory containing item.json).
    """
    runs_root = Path(runs_root)
    item_id, item_root = _reserve_item_root(runs_root, item_id)
    acq_dir = item_root / "acquisition"
    acq_dir.mkdir(parents=True, exist_ok=True)

    # ── Copy acquisition files into canonical acquisition/ subfolder ─────────
    video_dest = _copy_to_acq(video_path, acq_dir, "video" + Path(video_path).suffix)
    meta_dest = _copy_to_acq(meta_path, acq_dir, "video_meta.json")
    ts_dest = _copy_to_acq(timestamps_path, acq_dir, "video_timestamps.csv")
    qc_dest = _copy_to_acq(qc_path, acq_dir, "qc.json")

    # ── Build item.json payload ───────────────────────────────────────────────
    now = datetime.now().isoformat(timespec="seconds")

    def _rel(p: Optional[Path]) -> Optional[str]:
        if p is None:
            return None
        try:
            return str(Path(p).relative_to(item_root)).replace("\\", "/")
        except ValueError:
            return None

    source_type = Path(video_path).suffix.lstrip(".")  # "raw" or "avi"

    acq_section: dict[str, Any] = {}
    if video_dest is not None:
        acq_section["video"] = _rel(video_dest)
    if meta_dest is not None:
        acq_section["meta"] = _rel(meta_dest)
    if ts_dest is not None:
        acq_section["timestamps"] = _rel(ts_dest)
    if qc_dest is not None:
        acq_section["qc"] = _rel(qc_dest)
    if fps_effective is not None:
        acq_section["fps_effective"] = round(fps_effective, 3)
    if pixel_format is not None:
        acq_section["pixel_format"] = pixel_format
    if roi is not None:
        acq_section["roi"] = roi
    if frame_count is not None:
        acq_section["frame_count"] = int(frame_count)

    # Merge with any existing item.json (preserves created_at, extra keys)
    item_json_path = item_root / "item.json"
    existing: dict[str, Any] = {}
    if item_json_path.exists():
        try:
            existing = json.loads(item_json_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    payload: dict[str, Any] = dict(existing)
    payload.setdefault("schema_version", _SCHEMA_VERSION)
    payload.setdefault("module", "acquisition")
    payload.setdefault("item_id", item_id)
    payload.setdefault("created_at", now)
    payload["updated_at"] = now
    payload["source_type"] = source_type
    payload.setdefault("status", "acquired")
    if acq_section:
        payload["acquisition"] = {
            **dict(payload.get("acquisition") or {}),
            **acq_section,
        }

    item_json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return item_root


# ── private helpers ──────────────────────────────────────────────────────────

def _copy_to_acq(
    src: Optional[Path],
    acq_dir: Path,
    dest_name: str,
) -> Optional[Path]:
    """Copy src → acq_dir/dest_name.  Returns dest if copied/already present."""
    if src is None:
        return None
    src = Path(src)
    if not src.exists():
        return None
    dest = acq_dir / dest_name
    if not dest.exists():
        shutil.copy2(str(src), str(dest))
    return dest


def _reserve_item_root(runs_root: Path, item_id: str) -> tuple[str, Path]:
    base_root = runs_root / "acquisition"
    base_name = str(item_id).strip() or "acquisition_item"
    candidate_id = base_name
    candidate_root = base_root / candidate_id
    suffix = 1
    while candidate_root.exists():
        candidate_id = f"{base_name}_{suffix:02d}"
        candidate_root = base_root / candidate_id
        suffix += 1
    return candidate_id, candidate_root
