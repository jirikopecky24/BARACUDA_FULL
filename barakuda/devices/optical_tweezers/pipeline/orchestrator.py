from __future__ import annotations

import csv
import time
import numpy as np
from typing import Any, Callable
from pathlib import Path

# Load
from barakuda.core.video_reader import VideoReader
from barakuda.core.calibration_store import load_dataset_scale

# Pipeline
from barakuda.devices.optical_tweezers.pipeline.tracking import choose_tracking_polarity, track_particle, Roi, roi_follow_center, TrackingMethod
from barakuda.devices.optical_tweezers.pipeline.preprocess import preprocess_trajectory
from barakuda.devices.optical_tweezers.pipeline.qc import compute_qc
from barakuda.devices.optical_tweezers.compute import resolve_compute_profile
from barakuda.devices.optical_tweezers import perf as ot_perf

# Strategies
from barakuda.devices.optical_tweezers.strategies.base import CalibrationStrategy


class _TimeAxisError(RuntimeError):
    """Raised when OT time-axis cannot be validated/resolved."""


def _load_timestamp_map(video_path: str) -> dict[int, float]:
    """Load frame->timestamp map from sidecar timestamps CSV."""
    vp = Path(video_path)
    candidates = [
        vp.with_name(f"{vp.stem}_timestamps.csv"),
        vp.with_name("video_timestamps.csv"),
    ]
    ts_path = next((p for p in candidates if p.is_file()), None)
    if ts_path is None:
        raise _TimeAxisError("Missing timestamps CSV next to input video.")

    frame_to_ts: dict[int, float] = {}
    with ts_path.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        if "frame" not in (rdr.fieldnames or []) or "timestamp_s" not in (rdr.fieldnames or []):
            raise _TimeAxisError(f"Invalid timestamps CSV format: {ts_path.name} (need frame,timestamp_s)")
        for row in rdr:
            if not row:
                continue
            try:
                fi = int(float(row.get("frame", "nan")))
                ts = float(row.get("timestamp_s", "nan"))
            except Exception:
                continue
            if not np.isfinite(ts):
                continue
            if fi in frame_to_ts:
                raise _TimeAxisError(f"Duplicate frame in timestamps CSV: frame={fi}")
            frame_to_ts[fi] = ts
    if len(frame_to_ts) < 2:
        raise _TimeAxisError("Timestamps CSV has too few valid rows (<2).")
    return frame_to_ts


def _resolve_time_axis(
    *,
    video_path: str,
    s: int,
    e: int,
    fps: float,
    execution_mode: str,
) -> tuple[list[float], dict[str, Any], list[str]]:
    """Resolve per-frame time axis with batch/interative policy."""
    warnings: list[str] = []
    mode = str(execution_mode).strip().lower()
    strict = mode == "batch"
    frame_ids = list(range(int(s), int(e) + 1))

    def _fps_axis() -> list[float]:
        if fps <= 0:
            raise _TimeAxisError("FPS fallback unavailable (fps<=0).")
        return [fi / float(fps) for fi in frame_ids]

    try:
        ts_map = _load_timestamp_map(video_path)
        t_s = [float(ts_map[fi]) for fi in frame_ids]
        dt = np.diff(np.asarray(t_s, dtype=np.float64))
        if dt.size == 0:
            raise _TimeAxisError("Resolved time axis has too few points.")
        if not np.all(np.isfinite(dt)):
            raise _TimeAxisError("Resolved time axis contains non-finite dt.")
        if np.any(dt <= 0):
            raise _TimeAxisError("Resolved time axis is not strictly increasing.")
        info = {
            "time_axis_source": "timestamps_csv",
            "execution_mode": mode,
            "dt_stats": {
                "min_s": float(np.min(dt)),
                "max_s": float(np.max(dt)),
                "median_s": float(np.median(dt)),
                "mean_s": float(np.mean(dt)),
                "std_s": float(np.std(dt)),
            },
            "fallback_used": False,
        }
        return t_s, info, warnings
    except Exception as ex:  # noqa: BLE001
        if strict:
            raise _TimeAxisError(
                "Batch mode requires valid timestamps; cannot continue. "
                f"Reason: {ex}"
            ) from ex
        warnings.append(f"timestamps unavailable/invalid -> fps fallback ({ex})")
        t_s = _fps_axis()
        dt = np.diff(np.asarray(t_s, dtype=np.float64))
        info = {
            "time_axis_source": "fps_fallback",
            "execution_mode": mode,
            "dt_stats": {
                "min_s": float(np.min(dt)) if dt.size else None,
                "max_s": float(np.max(dt)) if dt.size else None,
                "median_s": float(np.median(dt)) if dt.size else None,
                "mean_s": float(np.mean(dt)) if dt.size else None,
                "std_s": float(np.std(dt)) if dt.size else None,
            },
            "fallback_used": True,
            "fallback_reason": str(ex),
        }
        return t_s, info, warnings


class OTPipeline:
    """
    Bible v2.1 Optical Tweezers Pipeline Orchestrator.
    
    Single entry point for the entire OT process:
    load -> track -> preprocess (drift) -> qc -> strategy -> export
    """
    def __init__(
        self, 
        strategy: CalibrationStrategy, 
        exporter: Any, 
        log_fn: Callable[[str], None] = print
    ):
        self.strategy = strategy
        self.exporter = exporter
        self.log_fn = log_fn

    def run(self, video_path: str, run_config: dict[str, Any]) -> dict[str, Any]:
        """
        Run the full OT pipeline for a single video.
        
        Args:
            video_path: Absolute path to the OT video file.
            run_config: Configuration dict containing tracking, preprocess, qc, and strategy params.
                        Expected keys: "tracking", "preprocess", "qc", "strategy", "calibration".
        Returns:
            dict: The result generated by the strategy (also exported to ot_summary.json).
        """
        
        self.log_fn(f"[OTv2.1] Starting pipeline for {video_path}")
        start_time = time.time()
        if ot_perf.enabled():
            ot_perf.clear()
        progress_cb = run_config.get("progress_cb")
        log_progress = run_config.get("log_progress")
        should_stop = run_config.get("should_stop")

        def _emit_progress(pct: int, msg: str = "") -> None:
            if callable(progress_cb):
                progress_cb(int(max(0, min(100, pct))), msg)
            if msg and callable(log_progress):
                log_progress(msg)

        def _stop_requested() -> bool:
            try:
                return bool(should_stop()) if callable(should_stop) else False
            except Exception:
                return False
        
        # 1. Load Setup
        reader = VideoReader(video_path)
        fps_detected = float(reader.meta.fps)
        
        tc = run_config.get("tracking", {})
        pc = run_config.get("preprocess", {})
        qc = run_config.get("qc", {})
        sc = run_config.get("strategy_params", {})
        cal_c = run_config.get("calibration", {})
        runtime = run_config.get("runtime", {})
        execution_mode = str(run_config.get("execution_mode", "interactive"))
        if runtime and "resolved_device" in runtime and "resolved_profile" in runtime:
            resolved_runtime = dict(runtime)
        else:
            requested_profile = runtime.get("requested_profile", tc.get("compute_profile", "cpu"))
            resolved_runtime = resolve_compute_profile(
                str(requested_profile),
                str(tc.get("method", "RADIAL_SYMMETRY")),
            )
        self.log_fn(
            "[OTv2.1] Runtime compute "
            f"requested={resolved_runtime['requested_profile']} "
            f"resolved={resolved_runtime['resolved_profile']} "
            f"device={resolved_runtime['resolved_device']}"
        )
        _emit_progress(0, "starting")
        if resolved_runtime["resolved_device"] == "cuda":
            self.log_fn(
                "[OTv2.1] GPU "
                f"{resolved_runtime['gpu_name']} "
                f"(torch {resolved_runtime['torch_version']})"
            )
        elif resolved_runtime.get("fallback_reason"):
            self.log_fn(f"[OTv2.1] {resolved_runtime['fallback_reason']}")

        fps_override = float(tc.get("fps_override", 0.0))
        if fps_override > 0:
            fps = fps_override
            self.log_fn(f"  - Video: {reader.meta.frame_count} frames | FPS: detected={fps_detected:.2f}, override={fps_override:.2f}, using={fps:.2f} Hz")
        else:
            fps = fps_detected
            self.log_fn(f"  - Video: {reader.meta.frame_count} frames | FPS: detected={fps_detected:.2f} Hz")

        if fps <= 0:
            raise ValueError(f"Invalid FPS: {fps}")
        
        s = int(tc.get("start_frame", 0))
        e = int(tc.get("end_frame", reader.meta.frame_count - 1))
        e = min(e, reader.meta.frame_count - 1)
        if s > e:
            s, e = 0, e
        
        # Camera Meta Assembly
        # Requires: fps, roi_w_px, roi_h_px (others optional)
        exp_ms = getattr(reader.meta, "exposure_ms", None)
        gain = getattr(reader.meta, "gain", None)
        t_start = getattr(reader.meta, "timestamp_start_iso", None)
        t_end = getattr(reader.meta, "timestamp_end_iso", None)
        
        camera_meta = {
            "fps": fps,
            "exposure_ms": float(exp_ms) if exp_ms is not None else None,
            "gain": float(gain) if gain is not None else None,
            "roi_w_px": int(getattr(reader.meta, "width", 0)),
            "roi_h_px": int(getattr(reader.meta, "height", 0)),
            "timestamp_start_iso": str(t_start) if t_start is not None else None,
            "timestamp_end_iso": str(t_end) if t_end is not None else None,
            "binning": getattr(reader.meta, "binning", None),
        }
        time_axis_warnings: list[str] = []
        
        # Check if um_per_px is available
        um_per_px = cal_c.get("um_per_px")
        if um_per_px is not None:
            camera_meta["um_per_px"] = float(um_per_px)
            camera_meta["um_per_px_source"] = cal_c.get("source", "unknown")

        # 2. Tracking Loop
        self.log_fn("  - Tracking...")
        _emit_progress(5, "tracking")
        init_roi_list = tc.get("roi", [0, 0, reader.meta.width, reader.meta.height])
        roi_obj = Roi(*init_roi_list)
        
        adaptive_roi = tc.get("adaptive_roi", True)
        method = TrackingMethod(tc.get("method", "RADIAL_SYMMETRY"))
        annulus_enabled = bool(tc.get("annulus_enabled", True))
        
        t_s = []
        x_px = []
        y_px = []
        quality = []
        peak = []
        roi_x, roi_y, roi_w, roi_h = [], [], [], []
        total_frames = max(1, e - s + 1)
        last_heartbeat = time.monotonic()
        locked_invert = bool(tc.get("invert", True))
        locked_det = None
        t_axis, t_axis_info, t_axis_warnings = _resolve_time_axis(
            video_path=video_path,
            s=s,
            e=e,
            fps=fps,
            execution_mode=execution_mode,
        )
        time_axis_warnings.extend(t_axis_warnings)
        camera_meta["time_axis"] = t_axis_info
        if time_axis_warnings:
            camera_meta["time_axis_warnings"] = list(time_axis_warnings)
        
        try:
            for fi in range(s, e + 1):
                if _stop_requested():
                    raise InterruptedError("OT shadow stopped by request.")
                frame = reader.get_frame(fi)
                if locked_det is None:
                    locked_invert, locked_det = choose_tracking_polarity(
                        frame,
                        roi_obj,
                        method=method,
                        blur_sigma=tc.get("blur_sigma", 1.2),
                        radial_grad_threshold=tc.get("radial_grad_threshold", 2.0),
                        annulus_enabled=annulus_enabled,
                        annulus_auto=tc.get("annulus_auto", True) if annulus_enabled else False,
                        annulus_r_inner_px=tc.get("annulus_r_inner_px", None),
                        annulus_r_outer_px=tc.get("annulus_r_outer_px", None),
                        annulus_profile_smooth=tc.get("annulus_profile_smooth", 3),
                        compute_device=str(resolved_runtime.get("resolved_device", "cpu")),
                    ) if bool(tc.get("auto_polarity", True)) else (bool(tc.get("invert", True)), None)
                if fi == s and locked_det is not None:
                    det = locked_det
                    locked_det = None
                else:
                    det = track_particle(
                        frame,
                        roi_obj,
                        method=method,
                        compute_device=str(resolved_runtime.get("resolved_device", "cpu")),
                        invert=locked_invert,
                        blur_sigma=tc.get("blur_sigma", 1.2),
                        radial_grad_threshold=tc.get("radial_grad_threshold", 2.0),
                        auto_polarity=False,
                        annulus_enabled=annulus_enabled,
                        annulus_auto=tc.get("annulus_auto", True) if annulus_enabled else False,
                        annulus_r_inner_px=tc.get("annulus_r_inner_px", None),
                        annulus_r_outer_px=tc.get("annulus_r_outer_px", None),
                        annulus_profile_smooth=tc.get("annulus_profile_smooth", 3),
                    )
                
                t_s.append(float(t_axis[fi - s]))
                x_px.append(det.x_px)
                y_px.append(det.y_px)
                quality.append(det.quality)
                peak.append(det.peak)
                roi_x.append(roi_obj.x)
                roi_y.append(roi_obj.y)
                roi_w.append(roi_obj.w)
                roi_h.append(roi_obj.h)
                
                if adaptive_roi:
                    roi_obj = roi_follow_center(frame.shape, roi_obj, det.x_px, det.y_px)

                frame_idx = fi - s
                now = time.monotonic()
                if frame_idx == 0 or fi == e or frame_idx % 250 == 0 or (now - last_heartbeat) >= 1.0:
                    pct = 5 + int(round(65 * (frame_idx / total_frames)))
                    _emit_progress(pct, f"tracking frame {frame_idx + 1}/{total_frames}")
                    last_heartbeat = now
        finally:
            reader.close()
        
        traj_raw = {
            "t_s": np.array(t_s),
            "x_px": np.array(x_px),
            "y_px": np.array(y_px),
            "quality": np.array(quality),
            "peak": np.array(peak),
            "roi_x": np.array(roi_x), "roi_y": np.array(roi_y), 
            "roi_w": np.array(roi_w), "roi_h": np.array(roi_h)
        }
        
        if um_per_px:
            traj_raw["x_um"] = traj_raw["x_px"] * float(um_per_px)
            traj_raw["y_um"] = traj_raw["y_px"] * float(um_per_px)
            
        # 3. Preprocess (Drift)
        self.log_fn("  - Preprocessing (Drift)...")
        if _stop_requested():
            raise InterruptedError("OT shadow stopped before preprocess.")
        _emit_progress(75, "preprocess")
        drift_mode = pc.get("drift_mode", "none")
        pp_with_time = dict(pc)
        pp_with_time["execution_mode"] = execution_mode
        pp_with_time["time_axis_source"] = str(t_axis_info.get("time_axis_source", "unknown"))
        traj_pp, drift_audit = preprocess_trajectory(traj_raw, fps, drift_mode, pp_with_time)
            
        # 4. QC
        self.log_fn("  - QC...")
        if _stop_requested():
            raise InterruptedError("OT shadow stopped before qc.")
        _emit_progress(82, "qc")
        qc_audit = compute_qc(traj_pp, camera_meta, qc)
        traj_pp["lost_mask"] = qc_audit.pop("_lost_mask")
        traj_pp["lost_reason"] = qc_audit.pop("_lost_reason")
        
        # 5. Strategy
        self.log_fn(f"  - Strategy: {self.strategy.name}")
        if _stop_requested():
            raise InterruptedError("OT shadow stopped before strategy.")
        _emit_progress(90, "strategy")
        # Combine all params so strategy has what it needs (viscosity, bead diameter, etc)
        # In a real app we'd strictly namespace, but here we pass merged run_config for simplicity, 
        # or the specific sc dictionary. We'll pass sc.
        result_dict, artifacts_dict = self.strategy.compute(traj_pp, camera_meta, sc)
        if time_axis_warnings:
            result_dict.setdefault("qc_warnings", [])
            try:
                result_dict["qc_warnings"].extend(time_axis_warnings)
            except Exception:
                pass
        
        # 6. Export
        self.log_fn("  - Exporting...")
        if _stop_requested():
            raise InterruptedError("OT shadow stopped before export.")
        _emit_progress(97, "export")
        self.exporter.write_all(
            video_path=video_path,
            traj_pp=traj_pp,
            camera_meta=camera_meta,
            drift_audit=drift_audit,
            qc_audit=qc_audit,
            strategy_name=self.strategy.name,
            strategy_params=sc,
            result_dict=result_dict,
            artifacts_dict=artifacts_dict,
            export_prefix=self.strategy.export_prefix
        )
        
        elapsed = time.time() - start_time
        self.log_fn(f"[OTv2.1] Pipeline completed in {elapsed:.2f}s")
        if ot_perf.enabled():
            self.log_fn(f"[OT perf] orchestrator:{video_path}: {ot_perf.snapshot(reset=True)}")
        _emit_progress(100, "done")
        
        return result_dict
