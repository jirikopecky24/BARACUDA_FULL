from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import csv
import math


@dataclass(frozen=True)
class TimingTruth:
    frame_count: int
    t_first_s: float | None
    t_last_s: float | None
    elapsed_time_s: float | None
    effective_fps: float | None
    timing_source: str
    timing_source_detail: str
    timestamp_validation_pass: bool
    timestamp_validation_message: str
    frame_to_time_s: dict[int, float] | None = None


@dataclass(frozen=True)
class ScaleResolution:
    um_per_px: float | None
    scale_source: str
    scale_warning: str | None


@dataclass(frozen=True)
class BeadResolution:
    bead_diameter_um: float
    bead_radius_um: float
    bead_source: str
    bead_source_warning: str | None
    fallback_used: bool


def _finite_non_negative(value: float) -> bool:
    return math.isfinite(value) and value >= 0.0


def load_and_validate_timestamps_csv(path: Path) -> tuple[list[int], list[float], str]:
    frames: list[int] = []
    times: list[float] = []
    malformed_rows = 0

    with path.open("r", encoding="utf-8", newline="") as fobj:
        reader = csv.DictReader(fobj)
        fieldnames = set(reader.fieldnames or [])
        if "frame" not in fieldnames or "timestamp_s" not in fieldnames:
            raise ValueError(
                f"Timestamps file {path.name} must contain 'frame' and 'timestamp_s' columns."
            )
        for row in reader:
            if not row:
                continue
            try:
                frame = int(row.get("frame", "").strip())
                timestamp = float(row.get("timestamp_s", "").strip())
            except Exception:
                malformed_rows += 1
                continue
            if not _finite_non_negative(timestamp):
                raise ValueError(
                    f"Timestamps file {path.name} contains non-finite or negative timestamp values."
                )
            frames.append(frame)
            times.append(timestamp)

    if malformed_rows > 0:
        raise ValueError(
            f"Timestamps file {path.name} contains malformed rows ({malformed_rows})."
        )
    if len(frames) < 2:
        raise ValueError(
            f"Timestamps file {path.name} must contain at least two valid rows."
        )
    if len(set(frames)) != len(frames):
        raise ValueError(f"Timestamps file {path.name} contains duplicate frame indices.")
    for i in range(1, len(times)):
        if not (times[i] > times[i - 1]):
            raise ValueError(
                f"Timestamps file {path.name} must be strictly monotonic increasing."
            )
    return frames, times, "validated_timestamps_csv"


def build_timing_truth_from_timestamps(
    *,
    frames: list[int],
    times: list[float],
    source_detail: str,
) -> TimingTruth:
    frame_count = int(len(frames))
    t_first = float(times[0])
    t_last = float(times[-1])
    elapsed = float(t_last - t_first)
    effective_fps: float | None = None
    if frame_count > 1 and elapsed > 0:
        effective_fps = float((frame_count - 1) / elapsed)
    mapping = {int(fi): float(ts) for fi, ts in zip(frames, times)}
    return TimingTruth(
        frame_count=frame_count,
        t_first_s=t_first,
        t_last_s=t_last,
        elapsed_time_s=elapsed,
        effective_fps=effective_fps,
        timing_source="timestamps",
        timing_source_detail=source_detail,
        timestamp_validation_pass=True,
        timestamp_validation_message="timestamps validated",
        frame_to_time_s=mapping,
    )


def build_timing_truth_fallback(
    *,
    frame_count: int,
    fps: float | None,
    source_detail: str,
    validation_message: str,
) -> TimingTruth:
    effective_fps: float | None = None
    elapsed: float | None = None
    if fps is not None and fps > 0 and frame_count > 0:
        effective_fps = float(fps)
        elapsed = float(frame_count) / float(fps)
    return TimingTruth(
        frame_count=int(max(0, frame_count)),
        t_first_s=None,
        t_last_s=None,
        elapsed_time_s=elapsed,
        effective_fps=effective_fps,
        timing_source="estimated",
        timing_source_detail=source_detail,
        timestamp_validation_pass=False,
        timestamp_validation_message=validation_message,
        frame_to_time_s=None,
    )


def resolve_timing_truth_for_run(
    *,
    video_path: Path,
    frame_count: int,
    fps_hint: float | None,
    meta: dict[str, Any] | None = None,
) -> TimingTruth:
    payload = dict(meta or {})
    candidates: list[Path] = []
    maybe_meta_ts = payload.get("timestamps_path")
    if maybe_meta_ts:
        try:
            candidates.append(Path(str(maybe_meta_ts)))
        except Exception:
            pass
    candidates.extend(
        [
            video_path.parent / f"{video_path.stem}_timestamps.csv",
            video_path.parent / f"{video_path.name}_timestamps.csv",
            video_path.parent / "video_timestamps.csv",
        ]
    )

    seen: set[str] = set()
    unique_candidates: list[Path] = []
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(candidate)

    for candidate in unique_candidates:
        if not candidate.is_file():
            continue
        try:
            frames, times, detail = load_and_validate_timestamps_csv(candidate)
            return build_timing_truth_from_timestamps(
                frames=frames,
                times=times,
                source_detail=f"{detail}:{candidate.name}",
            )
        except Exception as exc:
            return build_timing_truth_fallback(
                frame_count=frame_count,
                fps=fps_hint,
                source_detail=f"timestamps_invalid:{candidate.name}",
                validation_message=f"timestamp validation failed: {exc}",
            )

    return build_timing_truth_fallback(
        frame_count=frame_count,
        fps=fps_hint,
        source_detail="container_or_meta_fps",
        validation_message="timestamps sidecar missing",
    )


def resolve_scale_for_run(*, explicit_scale_um_per_px: float | None, scale_source: str | None) -> ScaleResolution:
    if explicit_scale_um_per_px is None:
        return ScaleResolution(
            um_per_px=None,
            scale_source=scale_source or "missing",
            scale_warning="Scale is missing; um-level outputs are reduced-trust.",
        )
    val = float(explicit_scale_um_per_px)
    if not math.isfinite(val) or val <= 0:
        return ScaleResolution(
            um_per_px=None,
            scale_source=scale_source or "invalid",
            scale_warning="Scale is invalid; um-level outputs are reduced-trust.",
        )
    return ScaleResolution(
        um_per_px=val,
        scale_source=scale_source or "explicit",
        scale_warning=None,
    )


def resolve_bead_parameters_for_run(
    *,
    bead_diameter_um: float | None,
    bead_radius_um: float | None,
    bead_source: str | None,
    allow_fallback: bool = False,
) -> BeadResolution:
    diameter: float | None = None
    radius: float | None = None
    source = bead_source or "missing"

    if bead_diameter_um is not None:
        d = float(bead_diameter_um)
        if math.isfinite(d) and d > 0:
            diameter = d
            radius = d * 0.5
    if diameter is None and bead_radius_um is not None:
        r = float(bead_radius_um)
        if math.isfinite(r) and r > 0:
            radius = r
            diameter = r * 2.0

    if diameter is not None and radius is not None:
        return BeadResolution(
            bead_diameter_um=diameter,
            bead_radius_um=radius,
            bead_source=source,
            bead_source_warning=None,
            fallback_used=False,
        )

    if not allow_fallback:
        raise ValueError(
            "Bead size is missing or invalid for this run. "
            "Set bead_diameter_um explicitly to avoid silent physics bias."
        )

    # Explicit fallback mode only for non-physics contexts.
    diameter = 1.0
    radius = 0.5
    return BeadResolution(
        bead_diameter_um=diameter,
        bead_radius_um=radius,
        bead_source="fallback_default_1um",
        bead_source_warning="Fallback bead size 1 um used; physics outputs reduced-trust.",
        fallback_used=True,
    )


def build_collision_safe_export_path(exports_dir: Path, relative_path: str) -> tuple[Path, bool]:
    rel = Path(str(relative_path).replace("\\", "/"))
    rel = Path(*[p for p in rel.parts if p not in ("..", ".")])
    dst = exports_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        return dst, False
    stem = dst.stem
    suffix = dst.suffix
    idx = 1
    while True:
        candidate = dst.parent / f"{stem}__dup{idx:02d}{suffix}"
        if not candidate.exists():
            return candidate, True
        idx += 1
