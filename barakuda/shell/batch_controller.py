from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Callable

import csv
import json
import os
import re
import shutil
import time
from datetime import datetime

import numpy as np

from PyQt6.QtWidgets import QApplication

from barakuda.core.video_reader import VideoReader
from barakuda.core.video_io import is_video_file
from barakuda.core.run_manager import RunManager
from barakuda.core.calibration_store import load_dataset_scale
from barakuda.core.export_xlsx import export_ot_results_xlsx
from barakuda.core.postprocess_ot import postprocess_trajectory_csv_inplace, PostprocessParams
from barakuda.core.ot_physics import DragParams, compute_dragging_from_offset, kappa_from_fc_n_per_m
from barakuda.core.trajectory_csv_io import read_trajectory_csv
from barakuda.devices.optical_tweezers.compute import resolve_compute_profile

from barakuda.core.tracking import track_particle, Roi, TrackingMethod, roi_follow_center



@dataclass(frozen=True)
class PreviewResult:
    path: str
    ok: bool
    status: str
    message: str
    details: Dict[str, Any]


class BatchController:
    def __init__(self, runs_folder: Path, log_fn: Callable[[str], None]):
        self.run_manager = RunManager(Path(runs_folder))
        self._log = log_fn

        self._preview_done: bool = False
        self._last_preview_results: list[PreviewResult] = []
        self._preview_dir: Optional[Path] = None
        self._stop_requested = False
        self.gate_results: dict[Path, tuple[bool, str]] = {}
        self.last_after_overlay_path: str | None = None

    def _parse_capture_tokens(self, p: Path) -> dict[str, Any]:
        """
        Expected filename (stem) format:
          YYYY-MM-DD-SampleName-Speed-Unit
        Example:
          2026-02-13-MySample-0-um_s
          2026-02-13-MySample-10-um_s

        Returns:
          {
            "ok": bool,
            "key": str,   # pairing key (date + sample + unit)
            "speed": float,
            "unit": str,
          }
        """
        stem = p.stem
        parts = stem.split("-")
        if len(parts) < 5:
            return {"ok": False}

        date = "-".join(parts[0:3])
        unit = parts[-1]
        speed_s = parts[-2]
        sample = "-".join(parts[3:-2]).strip()
        if not sample:
            return {"ok": False}

        try:
            speed = float(speed_s)
        except Exception:
            return {"ok": False}

        key = f"{date}|{sample}|{unit}"
        return {"ok": True, "key": key, "speed": float(speed), "unit": unit, "date": date, "sample": sample}

    def _reorder_for_pairing(self, paths: list[Path]) -> list[Path]:
        """
        Deterministic: for each key, process speed==0 first, then ascending speed.
        """
        tagged = []
        for p in paths:
            t = self._parse_capture_tokens(p)
            if t.get("ok"):
                tagged.append((t["key"], t["speed"], str(p)))
            else:
                # non-conforming names go last, keep stable order
                tagged.append(("~", 1e99, str(p)))

        tagged.sort(key=lambda x: (x[0], x[1], x[2]))
        return [Path(s) for _, _, s in tagged]

    def _mean_axis_um(self, trajectory_csv: Path, axis: str, um_per_px: float, fraction: float, tail: bool) -> float:
        """
        mean of x/y (corrected if present) over fraction of samples.
        tail=True => last fraction, tail=False => first fraction
        """
        table = read_trajectory_csv(trajectory_csv)
        axis = axis.lower().strip()
        if axis not in ("x", "y"):
            raise ValueError("axis must be x or y")

        def col(name: str) -> np.ndarray:
            idx = table.header.index(name)
            return np.array([float(r.get(name, "nan")) for r in table.rows], dtype=np.float64)

        x = col("x_corr_px") if "x_corr_px" in table.header else col("x_px")
        y = col("y_corr_px") if "y_corr_px" in table.header else col("y_px")
        sig = x if axis == "x" else y
        sig = sig[np.isfinite(sig)]
        if sig.size < 16:
            raise ValueError("not enough finite samples for mean")

        n = sig.size
        k = max(5, int(round(float(fraction) * n)))
        k = min(k, n)

        sl = sig[-k:] if tail else sig[:k]
        return float(np.mean(sl) * float(um_per_px))

    @property
    def preview_done(self) -> bool:
        return self._preview_done

    @property
    def last_preview_results(self) -> list[PreviewResult]:
        return self._last_preview_results

    @property
    def preview_dir(self) -> Optional[Path]:
        return self._preview_dir

    def reset_gate(self) -> None:
        self._preview_done = False
        self._last_preview_results = []
        self._preview_dir = None

    def stop(self) -> None:
        """Request cooperative stop of the running batch."""
        self._stop_requested = True
        self._log("STOP requested: batch will stop at the next safe checkpoint.")

    def _resolve_ot_runtime(self, tracking_params: dict[str, Any]) -> dict[str, Any]:
        method_str = str(tracking_params.get("method", "RADIAL_SYMMETRY"))
        profile = str(tracking_params.get("compute_profile", "cpu"))
        return resolve_compute_profile(profile, method_str)

    def _get_ot_shadow_mode(self) -> str:
        shadow_mode = str(os.getenv("BARAKUDA_OT_SHADOW_MODE", "off")).strip().lower()
        if shadow_mode not in {"off", "full"}:
            shadow_mode = "off"
        return shadow_mode

    @staticmethod
    def _shadow_progress_span() -> tuple[int, int]:
        return (0, 25)

    @staticmethod
    def _main_progress_span() -> tuple[int, int]:
        return (25, 100)

    def _emit_main_progress(
        self,
        progress_fn: Callable[[int, int, str, int], None],
        done: int,
        total: int,
        filename: str,
        pct: int,
        shadow_mode: str,
    ) -> None:
        if str(shadow_mode).lower() == "full":
            base, end = self._main_progress_span()
        else:
            base, end = (0, 100)
        pct = max(0, min(100, int(pct)))
        mapped = base + int((end - base) * (pct / 100.0))
        progress_fn(done, total, filename, mapped)

    # ---------------- Preview Gate ----------------

    def run_preview_gate(
        self,
        file_paths: list[Path],
        device_id: str,
        device_panel,
        preview_roi_rect: Optional[tuple[int, int, int, int]],
        preview_frame_index: int,
        gate_policy: str = "STRICT",
    ) -> list[PreviewResult]:
        self.reset_gate()
        if not file_paths:
            return []

        # Defaults (device panel may override)
        SAMPLE_COUNT = 7
        PASS_MIN_RATIO = 1.0
        Q_MIN_GATE = 0.0
        JUMP_MAX_GATE_PX = 50.0

        try:
            if hasattr(device_panel, "get_preview_gate_params"):
                gp = device_panel.get_preview_gate_params()  # type: ignore[attr-defined]
                SAMPLE_COUNT = int(gp.get("sample_count", SAMPLE_COUNT))
                PASS_MIN_RATIO = float(gp.get("pass_min_ratio", PASS_MIN_RATIO))
                Q_MIN_GATE = float(gp.get("q_min", Q_MIN_GATE))
                JUMP_MAX_GATE_PX = float(gp.get("jump_max_px", JUMP_MAX_GATE_PX))
        except Exception:
            pass

        SAMPLE_COUNT = max(1, int(SAMPLE_COUNT))
        PASS_MIN_RATIO = max(0.0, min(1.0, float(PASS_MIN_RATIO)))
        Q_MIN_GATE = max(0.0, float(Q_MIN_GATE))
        JUMP_MAX_GATE_PX = max(0.0, float(JUMP_MAX_GATE_PX))

        # Apply policy override (audit-first)
        gate_policy = str(gate_policy or "STRICT").upper()
        if gate_policy == "STRICT":
            PASS_MIN_RATIO = 1.0
        elif gate_policy == "ROBUST":
            PASS_MIN_RATIO = 0.85
        elif gate_policy == "CUSTOM":
            # keep PASS_MIN_RATIO from panel
            pass
        else:
            # unknown policy -> safest fallback
            gate_policy = "STRICT"
            PASS_MIN_RATIO = 1.0

        def _sample_indices(frame_count: int, preferred: int, n: int) -> list[int]:
            if frame_count <= 0:
                return [0]
            preferred = int(max(0, min(int(preferred), frame_count - 1)))

            anchors = [0, preferred, frame_count // 2, frame_count - 1]

            # Evenly spaced points across the range (deterministic)
            if n > len(anchors):
                k = n - len(anchors)
                if frame_count > 1 and k > 0:
                    for i in range(1, k + 1):
                        idx = int(round(i * (frame_count - 1) / (k + 1)))
                        anchors.append(idx)

            # Unique + sorted, then cap to n
            uniq = sorted(set(int(x) for x in anchors))
            if len(uniq) > n:
                # Keep preferred + ends if possible, then fill deterministically
                keep: list[int] = []
                for x in [0, preferred, frame_count - 1]:
                    if x in uniq and x not in keep:
                        keep.append(x)
                for x in uniq:
                    if x not in keep:
                        keep.append(x)
                    if len(keep) >= n:
                        break
                uniq = keep[:n]
            return uniq

        ts = time.strftime("%Y%m%d-%H%M%S")
        self._preview_dir = self.run_manager.runs_folder / f"PREVIEW-{ts}"
        self._preview_dir.mkdir(parents=True, exist_ok=True)

        results: list[PreviewResult] = []

        for p in file_paths:
            p = Path(p)
            if not p.exists():
                results.append(PreviewResult(str(p), False, "FAIL", "File not found", {}))
                continue

            # OT dataset manifest: resolve item.json → acquisition video path.
            # The resolved video path is used for all subsequent gate operations.
            # PreviewResult stores the resolved video path so run_batch receives it.
            if device_id == "optical_tweezers" and p.name == "item.json":
                try:
                    from barakuda.devices.optical_tweezers.manifest import load_item_manifest
                    _mf = load_item_manifest(p)
                    if _mf.video_path is not None:
                        p = _mf.video_path
                    else:
                        results.append(PreviewResult(
                            str(p), False, "FAIL",
                            "item.json: no acquisition video found", {}
                        ))
                        continue
                except Exception as _mf_err:
                    results.append(PreviewResult(
                        str(p), False, "FAIL",
                        f"item.json load error: {_mf_err!r}", {}
                    ))
                    continue

            if device_id == "optical_tweezers":
                if not is_video_file(p):
                    results.append(PreviewResult(str(p), False, "FAIL", "Not a video file", {}))
                    continue

            # --- read metadata ---
            try:
                vr = VideoReader(p)
                meta = vr.meta
                frame_count = int(getattr(meta, "frame_count", 0) or 0)
                fps = float(getattr(meta, "fps", 0.0) or 0.0)
                w = int(getattr(meta, "width", 0) or 0)
                h = int(getattr(meta, "height", 0) or 0)

                details: Dict[str, Any] = {
                    "frame_count": frame_count,
                    "fps": fps,
                    "width": w,
                    "height": h,
                    "sample_count": int(SAMPLE_COUNT),
                    "pass_min_ratio": float(PASS_MIN_RATIO),
                    "gate_q_min": float(Q_MIN_GATE),
                    "gate_jump_max_px": float(JUMP_MAX_GATE_PX),
                    "gate_policy": gate_policy,
                }

                frame_indices = _sample_indices(frame_count, int(preview_frame_index), int(SAMPLE_COUNT))
                details["preview_frame_indices"] = list(frame_indices)

            except Exception as e:
                results.append(PreviewResult(str(p), False, "FAIL", f"Cannot read video metadata: {e}", {}))
                continue

            if device_id != "optical_tweezers":
                try:
                    vr.close()
                except Exception:
                    pass
                results.append(PreviewResult(str(p), True, "OK", "Preview metadata OK", details))
                QApplication.processEvents()
                continue

            # --- OT-specific gate ---
            # Determine if Auto ROI On Load is ON
            is_auto_roi_on_load = False
            try:
                if hasattr(device_panel, "is_auto_roi_on_load"):
                    is_auto_roi_on_load = device_panel.is_auto_roi_on_load()
            except Exception:
                pass

            file_roi = None
            if is_auto_roi_on_load:
                try:
                    from barakuda.devices.optical_tweezers.pipeline.auto_roi import auto_roi_rs
                    scale_params = device_panel.get_scale_params()
                    um_per_px_auto = float(scale_params.get("um_per_px", 0.0))
                    
                    dia_auto = 1.0
                    if hasattr(device_panel, "get_postprocess_params"):
                        dia_auto = float(device_panel.get_postprocess_params().get("bead_diameter_um", 1.0))
                    elif hasattr(device_panel, "_bead_diameter_um"):
                        dia_auto = float(device_panel._bead_diameter_um.value())
                    
                    margin_auto = 1.8
                    if hasattr(device_panel, "get_tracking_params"):
                        margin_auto = float(device_panel.get_tracking_params().get("roi_margin", 1.8))
                    elif hasattr(device_panel, "_roi_margin"):
                        margin_auto = float(device_panel._roi_margin.value())

                    frame0 = vr.get_frame(0)
                    rx, ry, rw, rh = auto_roi_rs(frame0, um_per_px_auto, dia_auto, margin_factor=margin_auto)
                    file_roi = (rx, ry, rw, rh)
                except Exception as e:
                    self._log(f"WARN: auto ROI failed for {p.name}: {e!r}")
            
            if file_roi is None:
                file_roi = preview_roi_rect

            if file_roi is None:
                try:
                    vr.close()
                except Exception:
                    pass
                results.append(PreviewResult(str(p), False, "FAIL", "ROI not set (required for OT preview)", details))
                QApplication.processEvents()
                continue

            # Fetch tracking params once (deterministic)
            try:
                params = device_panel.get_tracking_params()
                method_str = str(params.get("method", "RADIAL_SYMMETRY"))
                try:
                    method = TrackingMethod(method_str)
                except Exception:
                    method = TrackingMethod.RADIAL_SYMMETRY

                roi_obj = Roi(*file_roi)
            except Exception as e:
                try:
                    vr.close()
                except Exception:
                    pass
                results.append(PreviewResult(str(p), False, "FAIL", f"Cannot read tracking params: {e}", details))
                QApplication.processEvents()
                continue

            ot_runtime = self._resolve_ot_runtime(params)
            details["compute_runtime"] = {
                "requested_profile": ot_runtime.get("requested_profile"),
                "resolved_profile": ot_runtime.get("resolved_profile"),
                "resolved_device": ot_runtime.get("resolved_device"),
                "fallback_reason": ot_runtime.get("fallback_reason"),
                "cuda_available": ot_runtime.get("cuda_available"),
                "gpu_name": ot_runtime.get("gpu_name"),
            }

            samples: list[Dict[str, Any]] = []
            pass_count = 0
            fail_messages: list[str] = []

            # Loop sampled frames
            for fi in frame_indices:
                try:
                    frame = vr.get_frame(int(fi))
                    det = track_particle(
                        frame,
                        roi_obj,
                        method=method,
                        invert=bool(params.get("invert", True)),
                        blur_sigma=float(params.get("blur_sigma", 1.2)),
                        radial_grad_threshold=float(params.get("radial_grad_threshold", 2.0)),
                        auto_polarity=bool(params.get("auto_polarity", True)),
                        annulus_auto=bool(params.get("annulus_auto", True)) if bool(params.get("annulus_enabled", True)) else False,
                        annulus_r_inner_px=params.get("annulus_r_inner_px", None),
                        annulus_r_outer_px=params.get("annulus_r_outer_px", None),
                        annulus_profile_smooth=int(params.get("annulus_profile_smooth", 3)),
                    )

                    # Minimal, physically safe gate: finite outputs
                    finite = (
                        (det.quality == det.quality) and
                        (det.peak == det.peak) and
                        (det.x_px == det.x_px) and
                        (det.y_px == det.y_px)
                    )

                    if not finite:
                        ok = False
                        msg = "NaN in detection"
                    elif float(det.quality) < float(Q_MIN_GATE):
                        ok = False
                        msg = f"quality<{Q_MIN_GATE:g}"
                    else:
                        ok = True
                        msg = "OK"

                    if ok:
                        pass_count += 1

                    samples.append({
                        "frame_index": int(fi),
                        "ok": bool(ok),
                        "message": msg,
                        "x_px": float(det.x_px),
                        "y_px": float(det.y_px),
                        "quality": float(det.quality),
                        "peak": float(det.peak),
                    })
                    if not ok:
                        fail_messages.append(f"frame {fi}: {msg}")

                except Exception as e:
                    samples.append({
                        "frame_index": int(fi),
                        "ok": False,
                        "message": f"error: {e}",
                    })
                    fail_messages.append(f"frame {fi}: error: {e}")

                QApplication.processEvents()

            try:
                vr.close()
            except Exception:
                pass

            # Compute max jump between consecutive OK samples (in frame order)
            ok_pts = [(s["frame_index"], s.get("x_px"), s.get("y_px")) for s in samples if s.get("ok") is True and s.get("x_px") is not None and s.get("y_px") is not None]
            ok_pts.sort(key=lambda t: int(t[0]))
            max_jump = 0.0
            for i in range(1, len(ok_pts)):
                dx = float(ok_pts[i][1]) - float(ok_pts[i-1][1])
                dy = float(ok_pts[i][2]) - float(ok_pts[i-1][2])
                j = (dx*dx + dy*dy) ** 0.5
                if j > max_jump:
                    max_jump = j

            # Median quality (from OK samples)
            ok_q = [float(s.get("quality")) for s in samples if s.get("ok") is True and s.get("quality") is not None]
            if ok_q:
                ok_q_sorted = sorted(ok_q)
                mid = len(ok_q_sorted) // 2
                median_q = ok_q_sorted[mid] if (len(ok_q_sorted) % 2 == 1) else 0.5 * (ok_q_sorted[mid-1] + ok_q_sorted[mid])
            else:
                median_q = 0.0

            n = max(1, len(frame_indices))
            ratio = float(pass_count) / float(n)
            fail_reasons: list[str] = []

            if ratio < float(PASS_MIN_RATIO):
                fail_reasons.append(f"pass_ratio<{PASS_MIN_RATIO:g} ({pass_count}/{n})")
            if float(median_q) < float(Q_MIN_GATE):
                fail_reasons.append(f"median_q<{Q_MIN_GATE:g} ({median_q:g})")
            if float(max_jump) > float(JUMP_MAX_GATE_PX):
                fail_reasons.append(f"max_jump>{JUMP_MAX_GATE_PX:g}px ({max_jump:g})")

            ok_overall = (len(fail_reasons) == 0)

            details.update({
                "method": method.value,
                "roi": list(preview_roi_rect),
                "pass_count": int(pass_count),
                "sample_n": int(n),
                "pass_ratio": float(ratio),
                "max_jump_px": float(max_jump),
                "median_quality": float(median_q),
                "fail_reason": "; ".join(fail_reasons),
                "samples": samples,
            })

            if ok_overall:
                results.append(PreviewResult(str(p), True, "OK", f"OT gate PASS ({pass_count}/{n})", details))
            else:
                msg = f"OT gate FAIL ({pass_count}/{n})"
                fr = details.get("fail_reason", "")
                if fr:
                    msg += f" — {fr}"
                results.append(PreviewResult(str(p), False, "FAIL", msg, details))

            QApplication.processEvents()

        report = {
            "device_id": device_id,
            "preview_roi_rect": list(preview_roi_rect) if preview_roi_rect else None,
            "preview_frame_index": int(preview_frame_index),
            "sample_count": int(SAMPLE_COUNT),
            "pass_min_ratio": float(PASS_MIN_RATIO),
            "gate_policy": gate_policy,
            "results": [
                {
                    "path": r.path,
                    "ok": r.ok,
                    "status": r.status,
                    "message": r.message,
                    "details": r.details,
                }
                for r in results
            ],
        }
        (self._preview_dir / "preview_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        ok_all = all(r.ok for r in results)
        self._preview_done = ok_all
        self._last_preview_results = results

        # Build gate_results for shell icon updates
        self.gate_results = {}
        for r in results:
            self.gate_results[Path(r.path)] = (r.ok, r.message)

        self._log(f"Preview Gate finished: {'PASS' if ok_all else 'FAIL'} (items={len(results)})")
        self._log(f"Preview report saved: {self._preview_dir / 'preview_report.json'}")
        return results

    def get_preview_gate_results(self) -> list[PreviewResult]:
        """Last Preview Gate results (per-file)."""
        return list(self._last_preview_results)

    def get_preview_gate_report_path(self) -> Path | None:
        """Path to preview_report.json for the last gate run."""
        if self._preview_dir is None:
            return None
        p = Path(self._preview_dir) / "preview_report.json"
        return p if p.exists() else None

    # ---------------- Dataset Item Detection ----------------

    @staticmethod
    def _detect_dataset_item_root(video_path: Path) -> Optional[Path]:
        """
        If video_path lives inside a dataset item folder (acquisition/ or raw/),
        return the item root directory (parent of those folders, where item.json lives).
        Returns None for standalone videos not inside a known item layout.
        """
        parent = video_path.parent
        if parent.name in ("acquisition", "raw"):
            item_root = parent.parent
            if (item_root / "item.json").is_file():
                return item_root
        return None

    # ---------------- Run Batch ----------------

    def run_batch(
        self,
        device_id: str,
        device_panel,
        roi_rect: tuple[int, int, int, int],
        dataset_set_status_fn: Callable[[Path, str], None],
        progress_fn: Callable[[int, int, str, int], None],
        checked_paths: list[Path] | list[str] | None = None,
    ) -> None:
        if not self._preview_done:
            self._log("Run Batch blocked: Preview Gate has not passed.")
            return

        ok_paths = [Path(r.path) for r in self._last_preview_results if r.ok]
        if checked_paths is not None:
            cset = {str(Path(p)) for p in checked_paths}
            ok_paths = [p for p in ok_paths if str(p) in cset]

        if not ok_paths:
            self._log("Run Batch: nothing to run (0 checked PASS items).")
            return

        self._log(f"Run Batch start: PASS items={len(ok_paths)}")
        self._stop_requested = False
        self.last_after_overlay_path = None
        progress_fn(0, len(ok_paths), "", 0)

        if device_id != "optical_tweezers":
            self._log(f"Run Batch: device '{device_id}' not implemented yet.")
            return

        # Note: We now fetch parameters *inside* the loop so that if device_panel
        # supports per-video overrides (like MockPanel does), we use them.
        
        base_roi = Roi(*roi_rect)

        ok_paths = [Path(p) for p in ok_paths]
        ok_paths = self._reorder_for_pairing(ok_paths)

        _ot_mirror_root: Path | None = None
        _ot_items_root: Path | None = None
        _ot_batch_id: str | None = None
        _ot_batch_created_at: str | None = None
        _ot_batch_items: list[dict] = []
        _ot_batch_preview_report_written = False
        if device_id == "optical_tweezers":
            _ot_output_root = self.run_manager.runs_folder / "ot"
            try:
                if hasattr(device_panel, "get_run_output_root"):
                    _raw_output_root = str(device_panel.get_run_output_root() or "").strip()
                    if _raw_output_root:
                        _candidate_output_root = Path(_raw_output_root).expanduser()
                        if _candidate_output_root.exists() and not _candidate_output_root.is_dir():
                            raise ValueError(f"not a directory: {_candidate_output_root}")
                        _ot_output_root = _candidate_output_root
            except Exception as e:
                self._log(f"WARN: invalid OT Output Root, using default: {e!r}")
            _ot_batch_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            _ot_mirror_root = _ot_output_root / _ot_batch_id
            _ot_items_root = _ot_mirror_root / "items"
            # Directory created lazily: only when a non-dataset item actually needs it.
            _ot_batch_created_at = datetime.now().isoformat()

        baseline_by_key: dict[str, dict[str, Any]] = {}

        done = 0
        for file_path in ok_paths:
            if self._stop_requested:
                self._log("Batch stopped before processing next file.")
                break

            file_path = Path(file_path)
            dataset_set_status_fn(file_path, "running")
            
            # Inform the mock panel of the current file being processed
            if hasattr(device_panel, "set_current_path"):
                device_panel.set_current_path(str(file_path))
                
            tracking_params = device_panel.get_tracking_params()
            post_params = device_panel.get_postprocess_params()
            post_params.setdefault("temperature_c", 25.0)
            post_params.setdefault("bead_diameter_um", 1.0)
            ot_runtime = self._resolve_ot_runtime(tracking_params)
            shadow_mode = self._get_ot_shadow_mode()
            
            scale_params = device_panel.get_scale_params()
            start_frame, end_frame = device_panel.get_frame_range()
            
            method_str = str(tracking_params.get("method", "RADIAL_SYMMETRY"))
            try:
                method = TrackingMethod(method_str)
            except Exception:
                method = TrackingMethod.RADIAL_SYMMETRY

            invert = bool(tracking_params.get("invert", True))
            blur_sigma = float(tracking_params.get("blur_sigma", 1.2))
            grad_th = float(tracking_params.get("radial_grad_threshold", 2.0))
            auto_pol = bool(tracking_params.get("auto_polarity", True))
            adaptive_roi = bool(tracking_params.get("adaptive_roi", True))

            ann_enabled = bool(tracking_params.get("annulus_enabled", True))
            ann_auto = bool(tracking_params.get("annulus_auto", True))
            ann_r_in = tracking_params.get("annulus_r_inner_px", None)
            ann_r_out = tracking_params.get("annulus_r_outer_px", None)
            ann_smooth = int(tracking_params.get("annulus_profile_smooth", 3))

            pp_enabled = bool(post_params.get("enabled", True))
            pp = PostprocessParams(
                qc_enabled=bool(post_params.get("qc_enabled", True)),
                q_min=float(post_params.get("q_min", 0.0)),
                jump_max_px=float(post_params.get("jump_max_px", 50.0)),
                drift_enabled=bool(post_params.get("drift_enabled", True)),
                drift_window_s=float(post_params.get("drift_window_s", 1.0)),
                physics_mode=str(post_params.get("physics_mode", "BROWNIAN")),
                stage_speed_um_s=float(post_params.get("stage_speed_um_s", 0.0)),
                drag_axis=str(post_params.get("drag_axis", "x")),
                viscosity_pa_s=float(post_params.get("viscosity_pa_s", 1.0e-3)),
                bead_radius_um=float(post_params.get("bead_radius_um", 0.5)),
                temperature_c=float(post_params.get("temperature_c", 25.0)),
                bead_diameter_um=float(post_params.get("bead_diameter_um", 1.0)),
            )

            use_dataset_scale = bool(scale_params.get("use_dataset_scale", True))
            ui_um_per_px = float(scale_params.get("um_per_px", 0.0))

            try:
                reader = VideoReader(file_path)
                fps = float(reader.meta.fps)
                fc = int(reader.meta.frame_count)
                _reader_w = int(getattr(reader.meta, "width", 0)) or None
                _reader_h = int(getattr(reader.meta, "height", 0)) or None

                # Auto-ROI per file if enabled
                file_roi_rect = roi_rect
                is_auto_roi_on_load = False
                try:
                    if hasattr(device_panel, "is_auto_roi_on_load"):
                        is_auto_roi_on_load = device_panel.is_auto_roi_on_load()
                except Exception:
                    pass
                    
                if is_auto_roi_on_load:
                    try:
                        from barakuda.devices.optical_tweezers.pipeline.auto_roi import auto_roi_rs
                        scale_params = device_panel.get_scale_params()
                        um_per_px_auto = float(scale_params.get("um_per_px", 0.0))
                        
                        dia_auto = float(post_params.get("bead_diameter_um", 1.0))
                        margin_auto = float(tracking_params.get("roi_margin", 1.8))

                        frame0 = reader.get_frame(0)
                        file_roi_rect = auto_roi_rs(frame0, um_per_px_auto, dia_auto, margin_factor=margin_auto)
                        self._log(f"[OT] Auto ROI for {file_path.name}: {file_roi_rect}")
                    except Exception as e:
                        self._log(f"WARN: auto ROI failed for {file_path.name}: {e!r}")
                
                base_roi = Roi(*file_roi_rect)

                s = int(start_frame)
                e = int(end_frame)
                if s < 0:
                    s = 0
                if e <= 0 or e >= fc:
                    e = max(0, fc - 1)
                if s > e:
                    s, e = 0, e

                um_per_px: float | None = None
                um_src = "none"

                # Scale policy (audit-first):
                # 1) If dataset sidecar exists and enabled → use it.
                # 2) Otherwise fall back to UI value (default should be 0.066528 µm/px).
                # This prevents silent "um_per_px=None" causing calibration exports to disappear.
                if use_dataset_scale:
                    info = load_dataset_scale(file_path)
                    if info is not None and info.um_per_px is not None and float(info.um_per_px) > 0:
                        um_per_px = float(info.um_per_px)
                        um_src = str(info.source)

                # UI fallback (also used when use_dataset_scale=False)
                if um_per_px is None and ui_um_per_px > 0:
                    um_per_px = float(ui_um_per_px)
                    um_src = "ui" if not use_dataset_scale else "ui_fallback"

                config = {
                    "device": {"id": "optical_tweezers"},
                    "tracking": {
                        "method": method.value,
                        "compute_profile": str(tracking_params.get("compute_profile", "cpu")),
                        "auto_polarity": auto_pol,
                        "invert": invert,
                        "blur_sigma": blur_sigma,
                        "radial_grad_threshold": grad_th,
                        "roi": list(file_roi_rect),
                        "adaptive_roi": adaptive_roi,
                        "fps": fps,
                        "frame_count": fc,
                        "annulus_enabled": ann_enabled,
                        "annulus_auto": ann_auto,
                        "annulus_r_inner_px": ann_r_in,
                        "annulus_r_outer_px": ann_r_out,
                        "annulus_profile_smooth": ann_smooth,
                        "start_frame": s,
                        "end_frame": e,
                    },
                    "calibration": {"um_per_px": um_per_px, "source": um_src},
                    "postprocess": {
                        "enabled": pp_enabled,
                        "qc_enabled": pp.qc_enabled,
                        "q_min": pp.q_min,
                        "jump_max_px": pp.jump_max_px,
                        "drift_enabled": pp.drift_enabled,
                        "drift_window_s": pp.drift_window_s,
                        "export_um_columns": bool(pp.export_um_columns),
                        "physics_mode": str(pp.physics_mode),
                        "stage_speed_um_s": float(pp.stage_speed_um_s),
                        "drag_axis": str(pp.drag_axis),
                        "viscosity_pa_s": float(pp.viscosity_pa_s),
                        "bead_radius_um": float(pp.bead_radius_um),
                        "temperature_c": float(pp.temperature_c),
                        "bead_diameter_um": float(pp.bead_diameter_um),
                    },
                }

                self._log(
                    "[OT runtime] requested="
                    f"{str(ot_runtime.get('requested_profile', 'cpu')).upper()} "
                    "resolved="
                    f"{str(ot_runtime.get('resolved_profile', 'cpu')).upper()} "
                    f"device={ot_runtime.get('resolved_device', 'cpu')}"
                )
                if bool(ot_runtime.get("cuda_available")):
                    self._log(f"[OT runtime] detected CUDA GPU: {ot_runtime.get('gpu_name', 'unknown')}")
                fallback_reason = str(ot_runtime.get("fallback_reason", "")).strip()
                if fallback_reason:
                    self._log(f"[OT runtime] {fallback_reason}")
                self._log(f"[OT shadow] mode={shadow_mode}")

                stem = Path(file_path).stem

                # Detect whether this video lives inside an existing dataset item folder.
                _dataset_item_root = self._detect_dataset_item_root(file_path)

                # STEP A: select output root
                if _dataset_item_root is not None:
                    # Dataset mode: write analysis directly into existing item home.
                    # No new batch item directory is created.
                    _item_root_for_run = _dataset_item_root
                    run_dir = _item_root_for_run / "analysis"
                    run_dir.mkdir(parents=True, exist_ok=True)
                    for _sd in ("audit", "tracking", "physics"):
                        (run_dir / _sd).mkdir(parents=True, exist_ok=True)
                    _item_id_for_run = _item_root_for_run.name
                    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + stem
                    (run_dir / "run.json").write_text(
                        json.dumps({
                            "run_id": run_id,
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                            "input_path": str(file_path),
                            "config": config,
                        }, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                elif _ot_items_root is not None and _ot_batch_id is not None:
                    # New-batch mode: create a fresh item directory under current batch.
                    _ot_items_root.mkdir(parents=True, exist_ok=True)  # lazy creation
                    _base = re.sub(r"[^A-Za-z0-9._\-]", "_", stem)
                    _item_id_for_run = _base
                    _n_coll = 1
                    while (_ot_items_root / _item_id_for_run).exists():
                        _item_id_for_run = f"{_base}_{_n_coll:02d}"
                        _n_coll += 1
                    _item_root_for_run = _ot_items_root / _item_id_for_run
                    run_dir = _item_root_for_run / "module" / "ot"
                    run_dir.mkdir(parents=True, exist_ok=True)
                    for _sd in ("raw",):
                        (_item_root_for_run / _sd).mkdir(parents=True, exist_ok=True)
                    for _d in ("audit", "tracking", "physics"):
                        (run_dir / _d).mkdir(parents=True, exist_ok=True)
                    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + stem
                    (run_dir / "run.json").write_text(
                        json.dumps({
                            "run_id": run_id,
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                            "input_path": str(file_path),
                            "config": config,
                        }, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                else:
                    result = self.run_manager.create_run(file_path, config)
                    run_dir = result.run_dir
                    run_id = result.run_id
                    _item_id_for_run = None
                    _item_root_for_run = None
                    _dataset_item_root = None
                    for _d in ("audit", "tracking", "physics"):
                        (run_dir / _d).mkdir(parents=True, exist_ok=True)
                
                # --- OT Pipeline v2.1 Shadow Run ---
                if shadow_mode == "full":
                    def _trace(msg: str) -> None:
                        try:
                            with open("ot_shadow_trace.log", "a", encoding="utf-8") as f:
                                f.write(msg + "\n")
                        except Exception:
                            pass
                    
                    try:
                        _trace(f"ENTER shadow for <{file_path.name}>")
                        self._log(f"[OT shadow] Running OTPipeline v2.1 for {file_path.name}...")
                        from barakuda.devices.optical_tweezers.pipeline.orchestrator import OTPipeline
                        from barakuda.devices.optical_tweezers.export.exporter import OTExporter
                        
                        strat_name = str(post_params.get("strategy", "PSD_Welch"))
                        if strat_name == "Drag_ConstantVelocity":
                            from barakuda.devices.optical_tweezers.strategies.drag_constant_velocity import DragConstantVelocityStrategy
                            strat = DragConstantVelocityStrategy()
                        elif strat_name == "Piezo_Oscillation":
                            from barakuda.devices.optical_tweezers.strategies.piezo_oscillation import PiezoOscillationStrategy
                            strat = PiezoOscillationStrategy()
                        elif strat_name == "PSD_ProcFFT":
                            from barakuda.devices.optical_tweezers.strategies.psd_procfft import PsdProcFftStrategy
                            strat = PsdProcFftStrategy()
                        else:  # PSD_Welch or PSD_Lorentzian fallback
                            from barakuda.devices.optical_tweezers.strategies.psd_welch import PsdWelchStrategy
                            strat = PsdWelchStrategy()
                            
                        # Dataset and non-dataset: write OTPipeline outputs under pipeline/
                        # (manifest supports both pipeline/ and ot_v2_shadow/ for backward compat).
                        shadow_dir = run_dir / "pipeline"
                        shadow_dir.mkdir(parents=True, exist_ok=True)
                        exporter = OTExporter(shadow_dir)
                        pipeline = OTPipeline(strat, exporter, self._log)
                        
                        shadow_config = {
                            "tracking": config["tracking"],
                            "calibration": config["calibration"],
                            "preprocess": {
                                "drift_mode": str(post_params.get("drift_mode", "none")),
                                "cutoff_hz": 3.0,
                                "filter_type": "butterworth",
                                "order": 4
                            },
                            "qc": {
                                "qc_enabled": bool(post_params.get("qc_enabled", True)),
                                "q_min": float(post_params.get("q_min", 0.0)),
                                "jump_max_px": float(post_params.get("jump_max_px", 50.0))
                            },
                            "strategy_params": post_params,
                            "runtime": ot_runtime,
                            "progress_cb": lambda pct: progress_fn(
                                done,
                                len(ok_paths),
                                file_path.name,
                                self._shadow_progress_span()[0]
                                + int((self._shadow_progress_span()[1] - self._shadow_progress_span()[0]) * (max(0, min(100, int(pct))) / 100.0)),
                            ),
                            "log_progress": True,
                            "should_stop": lambda: self._stop_requested,
                        }
                        
                        pipeline.run(str(file_path), shadow_config)
                        
                        _trace("EXIT shadow OK")
                        self._log(f"[OT shadow] OTPipeline finished successfully for {file_path.name}.")
                    except InterruptedError:
                        _trace("EXIT shadow STOP")
                        self._stop_requested = True
                        self._log(f"[OT shadow] OTPipeline stopped for {file_path.name}.")
                    except Exception as err:
                        _trace(f"EXIT shadow FAIL: {err!r}")
                        import traceback
                        self._log(f"[OT shadow] OTPipeline failed: {err!r}")
                        self._log(traceback.format_exc())
                # -----------------------------------

                traj_path = run_dir / "tracking" / f"{stem}_trajectory.csv"


                # Tracking loop bookkeeping for overlays:
                first_frame = None
                first_xy = None
                first_roi: tuple[int, int, int, int] | None = None

                last_frame = None
                last_xy = None
                last_roi: tuple[int, int, int, int] | None = None

                with traj_path.open("w", newline="", encoding="utf-8") as f_meta:
                    f_meta.write(f"# source_file={file_path.name}\n")
                    f_meta.write(f"# method={method.value}\n")
                    f_meta.write(f"# roi={list(file_roi_rect)}\n")
                    f_meta.write(f"# adaptive_roi={adaptive_roi}\n")
                    f_meta.write(f"# auto_polarity={auto_pol}\n")
                    f_meta.write(f"# invert={invert}\n")
                    f_meta.write(f"# blur_sigma={blur_sigma}\n")
                    f_meta.write(f"# radial_grad_threshold={grad_th}\n")
                    f_meta.write(f"# annulus_enabled={ann_enabled}\n")
                    f_meta.write(f"# annulus_auto={ann_auto}\n")
                    f_meta.write(f"# annulus_r_inner_px={ann_r_in}\n")
                    f_meta.write(f"# annulus_r_outer_px={ann_r_out}\n")
                    f_meta.write(f"# annulus_profile_smooth={ann_smooth}\n")
                    f_meta.write(f"# fps={fps}\n")
                    f_meta.write(f"# start_frame={s}\n")
                    f_meta.write(f"# end_frame={e}\n")
                    f_meta.write(f"# um_per_px={um_per_px}\n")
                    f_meta.write(f"# um_per_px_source={um_src}\n")

                    w = csv.writer(f_meta)
                    w.writerow(["frame", "t_s", "x_px", "y_px", "quality", "peak", "roi_x", "roi_y", "roi_w", "roi_h"])

                    current_roi = base_roi

                    total_frames = max(1, e - s + 1)

                    for fi in range(s, e + 1):
                        if self._stop_requested:
                            self._log(f"Batch stopped during '{file_path.name}' at frame {fi}.")
                            break

                        # Per-frame progress (throttled: every 10 frames + first + last)
                        frame_idx = fi - s
                        if frame_idx % 10 == 0 or fi == e:
                            pct = int(100 * frame_idx / total_frames)
                            self._emit_main_progress(progress_fn, done, len(ok_paths), file_path.name, pct, shadow_mode)

                        frame = reader.get_frame(fi)
                        roi_obj = current_roi
                        det = track_particle(
                            frame,
                            roi_obj,
                            method=method,
                            invert=invert,
                            blur_sigma=blur_sigma,
                            radial_grad_threshold=grad_th,
                            auto_polarity=auto_pol,
                            annulus_auto=ann_auto if ann_enabled else False,
                            annulus_r_inner_px=ann_r_in,
                            annulus_r_outer_px=ann_r_out,
                            annulus_profile_smooth=ann_smooth,
                        )

                        if first_frame is None:
                            first_frame = frame
                            first_xy = (float(det.x_px), float(det.y_px))
                            first_roi = (roi_obj.x, roi_obj.y, roi_obj.w, roi_obj.h)

                        last_frame = frame
                        last_xy = (float(det.x_px), float(det.y_px))
                        last_roi = (roi_obj.x, roi_obj.y, roi_obj.w, roi_obj.h)

                        if adaptive_roi and first_frame is not None and fi > s:
                            # Follow the detected center with fixed window size.
                            current_roi = roi_follow_center(frame.shape, current_roi, det.x_px, det.y_px)

                        t_s = (fi / fps) if fps > 0 else 0.0
                        w.writerow([
                            fi,
                            f"{t_s:.9f}",
                            f"{det.x_px:.6f}",
                            f"{det.y_px:.6f}",
                            f"{det.quality:.6f}",
                            f"{det.peak:.6f}",
                            int(roi_obj.x), int(roi_obj.y), int(roi_obj.w), int(roi_obj.h),
                        ])

                reader.close()

                if self._stop_requested:
                    dataset_set_status_fn(file_path, "stopped")
                    done += 1
                    progress_fn(done, len(ok_paths), file_path.name, 100)
                    break

                # Save overlays (never crash the run)
                try:
                    if first_frame is not None and first_xy is not None:
                        dir_preview = run_dir / "preview"
                        dir_preview.mkdir(parents=True, exist_ok=True)
                        if self._preview_dir and (self._preview_dir / "preview_report.json").exists():
                            if _dataset_item_root is not None:
                                shutil.copy2(
                                    self._preview_dir / "preview_report.json",
                                    dir_preview / "preview_report.json",
                                )
                            elif _ot_mirror_root is not None and not _ot_batch_preview_report_written:
                                _ot_mirror_root.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(
                                    self._preview_dir / "preview_report.json",
                                    _ot_mirror_root / "preview_report.json",
                                )
                                _ot_batch_preview_report_written = True
                        self.run_manager.save_overlay_png(
                            run_dir=dir_preview,
                            frame_rgb=first_frame,
                            x=first_xy[0],
                            y=first_xy[1],
                            roi=(first_roi if first_roi is not None else roi_rect),
                            name=f"{stem}_preview_tracking.png",
                        )
                except Exception as e:
                    self._log(f"WARN: preview overlay failed ({file_path.name}): {e!r}")

                try:
                    if last_frame is not None and last_xy is not None:
                        dir_tracking = run_dir / "tracking"
                        # Raw frame for audit (optional)
                        self.run_manager.save_after_png(dir_tracking, last_frame, name=f"{stem}_after_raw.png")
                        # Overlay as 'after.png' (what user expects)
                        self.run_manager.save_overlay_png(
                            run_dir=dir_tracking,
                            frame_rgb=last_frame,
                            x=last_xy[0],
                            y=last_xy[1],
                            roi=(last_roi if last_roi is not None else roi_rect),
                            name=f"{stem}_after.png",
                        )
                        self.last_after_overlay_path = str(dir_tracking / f"{stem}_after.png")
                except Exception as e:
                    self._log(f"WARN: after overlay failed ({file_path.name}): {e!r}")

                if pp_enabled:
                    try:
                        pp_summary = postprocess_trajectory_csv_inplace(
                            trajectory_csv_path=traj_path,
                            fps=fps,
                            um_per_px=um_per_px,
                            params=pp,
                            start_frame=int(s),
                            end_frame=int(e),
                        )
                        (run_dir / "audit" / f"{stem}_postprocess.json").write_text(
                            json.dumps({
                                "enabled": True,
                                "params": {
                                    "qc_enabled": bool(pp.qc_enabled),
                                    "q_min": float(pp.q_min),
                                    "jump_max_px": float(pp.jump_max_px),
                                    "drift_enabled": bool(pp.drift_enabled),
                                    "drift_window_s": float(pp.drift_window_s),
                                    "export_um_columns": bool(pp.export_um_columns),
                                },
                                "summary": pp_summary,
                            }, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    except Exception as e:
                        self._log(f"WARN: postprocess failed ({file_path.name}): {e!r}")

                # --- 2-video Pairing & Comparison (Brownian vs Dragging) ---
                try:
                    tok = self._parse_capture_tokens(file_path)
                    if tok.get("ok") and float(tok["speed"]) == 0.0:
                        # Store Brownian baseline info for later comparison
                        # Store paths after organize: psd_fit in audit/, trajectory in tracking/
                        baseline_by_key[tok["key"]] = {
                            "path": str(file_path),
                            "run_dir": str(run_dir),
                            "base_name": str(file_path.stem),
                            "psd_fit_json": str(run_dir / "audit" / f"{file_path.stem}_psd_fit.json"),
                            "trajectory_csv": str(run_dir / "tracking" / f"{file_path.stem}_trajectory.csv"),
                        }
                    
                    elif tok.get("ok") and float(tok["speed"]) > 0.0:
                        key = tok["key"]
                        if key not in baseline_by_key:
                            self._log(f"[DRAGGING] Missing baseline (speed=0) for key={key}. Cannot compare.")
                            # non-fatal, just no comparison
                        else:
                            # Resolve drag params
                            stage_speed_ui = float(post_params.get("stage_speed_um_s", 0.0))
                            stage_speed = stage_speed_ui if stage_speed_ui > 0 else float(tok["speed"])
                            axis = str(post_params.get("drag_axis", "x")).lower().strip()
                            eta = float(post_params.get("viscosity_pa_s", 1.0e-3))
                            r_um = float(post_params.get("bead_radius_um", 0.5))

                            if ui_um_per_px <= 0:
                                self._log("[DRAGGING] um_per_px must be > 0 for stiffness comparison.")
                            else:
                                base_info = baseline_by_key[key]

                                # baseline mean from static (first 50%)
                                baseline_mean_um = self._mean_axis_um(
                                    Path(base_info["trajectory_csv"]), axis=axis, um_per_px=ui_um_per_px, fraction=0.5, tail=False
                                )
                                # steady mean from drag: last 50%
                                steady_mean_um = self._mean_axis_um(
                                    Path(run_dir / "tracking" / f"{file_path.stem}_trajectory.csv"), axis=axis, um_per_px=ui_um_per_px, fraction=0.5, tail=True
                                )

                                offset_um = float(steady_mean_um - baseline_mean_um)

                                drag_res = compute_dragging_from_offset(
                                    offset_um,
                                    DragParams(
                                        stage_speed_um_s=float(stage_speed),
                                        axis=axis,
                                        viscosity_pa_s=float(eta),
                                        bead_radius_um=float(r_um),
                                    ),
                                )

                                # Brownian kappa from baseline fc
                                fit_json_path = Path(base_info["psd_fit_json"])
                                if fit_json_path.exists():
                                    import json as _json
                                    fit_payload = _json.loads(fit_json_path.read_text(encoding="utf-8"))
                                    # fit_x or fit_y depending on axis
                                    fit_axis = fit_payload.get("fit_x" if axis == "x" else "fit_y", {})
                                    if fit_axis and "fc_hz" in fit_axis:
                                        fc = float(fit_axis.get("fc_hz", 0.0))
                                        kappa_b = kappa_from_fc_n_per_m(fc, viscosity_pa_s=float(eta), bead_radius_um=float(r_um))
                                        kappa_b_pn_um = float(abs(kappa_b) * 1e6 * 1e12)
                                    else:
                                        fc, kappa_b, kappa_b_pn_um = 0.0, 0.0, 0.0
                                else:
                                    fc, kappa_b, kappa_b_pn_um = 0.0, 0.0, 0.0

                                # Write compare artifacts into DRAG run dir (physics subdir)
                                compare_csv = Path(run_dir) / "physics" / f"{file_path.stem}_compare.csv"
                                compare_json = Path(run_dir) / "physics" / f"{file_path.stem}_compare.json"
                                drag_json = Path(run_dir) / "physics" / f"{file_path.stem}_drag.json"

                                import json as _json
                                drag_json.write_text(_json.dumps({
                                    "pair_key": key,
                                    "baseline": base_info,
                                    "drag": {"path": str(file_path), "run_dir": str(run_dir)},
                                    "params": {
                                        "axis": axis,
                                        "stage_speed_um_s": float(stage_speed),
                                        "viscosity_pa_s": float(eta),
                                        "bead_radius_um": float(r_um),
                                        "um_per_px": float(ui_um_per_px),
                                    },
                                    "means_um": {
                                        "baseline_mean_um": float(baseline_mean_um),
                                        "steady_mean_um": float(steady_mean_um),
                                        "offset_um": float(offset_um),
                                    },
                                    "dragging": {
                                        "drag_force_n": float(drag_res.drag_force_n),
                                        "kappa_n_per_m": float(drag_res.kappa_n_per_m),
                                        "kappa_pn_per_um": float(drag_res.kappa_pn_per_um),
                                    }
                                }, indent=2, ensure_ascii=False), encoding="utf-8")

                                import csv as _csv
                                with compare_csv.open("w", encoding="utf-8", newline="") as f:
                                    w = _csv.DictWriter(f, fieldnames=[
                                        "pair_key",
                                        "axis",
                                        "fc_hz",
                                        "kappa_brownian_n_per_m",
                                        "kappa_brownian_pn_per_um",
                                        "kappa_drag_n_per_m",
                                        "kappa_drag_pn_per_um",
                                        "ratio_drag_over_brownian",
                                        "delta_n_per_m",
                                    ])
                                    w.writeheader()
                                    w.writerow({
                                        "pair_key": key,
                                        "axis": axis,
                                        "fc_hz": f"{fc:.12g}",
                                        "kappa_brownian_n_per_m": f"{kappa_b:.12g}",
                                        "kappa_brownian_pn_per_um": f"{kappa_b_pn_um:.12g}",
                                        "kappa_drag_n_per_m": f"{drag_res.kappa_n_per_m:.12g}",
                                        "kappa_drag_pn_per_um": f"{drag_res.kappa_pn_per_um:.12g}",
                                        "ratio_drag_over_brownian": f"{(abs(drag_res.kappa_n_per_m)/abs(kappa_b)):.12g}" if abs(kappa_b) > 0 else "nan",
                                        "delta_n_per_m": f"{(drag_res.kappa_n_per_m - kappa_b):.12g}",
                                    })

                                compare_json.write_text(_json.dumps({
                                    "pair_key": key,
                                    "axis": axis,
                                    "brownian": {
                                        "fc_hz": fc,
                                        "kappa_n_per_m": kappa_b,
                                        "kappa_pn_per_um": kappa_b_pn_um,
                                        "psd_fit_json": base_info["psd_fit_json"],
                                    },
                                    "dragging": {
                                        "kappa_n_per_m": float(drag_res.kappa_n_per_m),
                                        "kappa_pn_per_um": float(drag_res.kappa_pn_per_um),
                                        "drag_json": str(drag_json),
                                    },
                                    "delta": {
                                        "delta_n_per_m": float(drag_res.kappa_n_per_m - kappa_b),
                                        "ratio_drag_over_brownian": float(abs(drag_res.kappa_n_per_m)/abs(kappa_b)) if abs(kappa_b) > 0 else None,
                                    },
                                }, indent=2, ensure_ascii=False), encoding="utf-8")

                except Exception as e:
                    self._log(f"WARN: drag comparison failed ({file_path.name}): {e!r}")

                try:
                    # postprocess_ot writes to trajectory dir (run_dir/tracking/)
                    _tracking = run_dir / "tracking"
                    _msd = _tracking / f"{stem}_msd.csv"
                    _psd_x = _tracking / f"{stem}_psd_x.csv"
                    _psd_y = _tracking / f"{stem}_psd_y.csv"
                    _cal_csv = _tracking / f"{stem}_calibration.csv"
                    _cal_json = _tracking / f"{stem}_calibration.json"
                    _hist_x = _tracking / f"{stem}_hist_x.csv"
                    _hist_y = _tracking / f"{stem}_hist_y.csv"
                    _hist_r = _tracking / f"{stem}_hist_r.csv"
                    _derived = _tracking / f"{stem}_derived.csv"

                    # --- metadata.csv (audit-first, key/value) ---
                    def _flatten(prefix: str, obj: Any, out: list[tuple[str, str]]) -> None:
                        if isinstance(obj, dict):
                            for k in sorted(obj.keys(), key=lambda x: str(x)):
                                _flatten(f"{prefix}{k}.", obj[k], out)
                        elif isinstance(obj, list):
                            out.append((prefix[:-1] if prefix.endswith(".") else prefix, json.dumps(obj, ensure_ascii=False)))
                        else:
                            key = prefix[:-1] if prefix.endswith(".") else prefix
                            out.append((key, "" if obj is None else str(obj)))

                    meta_pairs: list[tuple[str, str]] = []
                    try:
                        run_payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                        _flatten("run.", run_payload, meta_pairs)
                    except Exception:
                        meta_pairs.append(("run_json_error", "failed to parse run.json"))

                    # trajectory.csv header lines (start with '#')
                    try:
                        table = read_trajectory_csv(traj_path)
                        for i, line in enumerate(table.meta_lines):
                            meta_pairs.append((f"trajectory_meta[{i}]", line))
                    except Exception:
                        meta_pairs.append(("trajectory_meta_error", "failed to read trajectory.csv meta lines"))

                    # postprocess + calibration json (if present)
                    for tag, pth in [
                        ("postprocess", run_dir / "audit" / f"{stem}_postprocess.json"),
                        ("calibration", _cal_json),
                    ]:
                        if pth.exists():
                            try:
                                _flatten(f"{tag}.", json.loads(pth.read_text(encoding="utf-8")), meta_pairs)
                            except Exception:
                                meta_pairs.append((f"{tag}_json_error", f"failed to parse {pth.name}"))

                    # --- Result summaries under summary/ (new runs only; legacy root-level remains readable) ---
                    dir_summary = run_dir / "summary"
                    dir_summary.mkdir(parents=True, exist_ok=True)
                    export_ot_results_xlsx(
                        output_dir=dir_summary,
                        base_name=stem,
                        trajectory_csv_path=traj_path,
                        msd_csv_path=_msd,
                        psd_x_csv_path=_psd_x,
                        psd_y_csv_path=_psd_y,
                    )

                    # --- _results.csv (single-file bundle; keep canonical CSVs too) ---
                    results_csv = dir_summary / f"{stem}_results.csv"
                    with results_csv.open("w", encoding="utf-8", newline="") as out:
                        # Metadata section (key/value)
                        out.write("# [Metadata]\n")
                        out.write("key,value\n")
                        for k, v in meta_pairs:
                            out.write(f"{k},{json.dumps(v, ensure_ascii=False)}\n")
                        out.write("\n")

                        for section, src, keep_comments in [
                            ("Trajectory", traj_path, True),
                            ("MSD", _msd, False),
                            ("PSD_X", _psd_x, False),
                            ("PSD_Y", _psd_y, False),
                            ("Calibration", _cal_csv, False),
                            ("Derived_Physics", _derived, False),
                            ("Hist_X", _hist_x, False),
                            ("Hist_Y", _hist_y, False),
                            ("Hist_R", _hist_r, False),
                        ]:
                            if src.exists():
                                out.write(f"# [{section}]\n")
                                txt_blob = src.read_text(encoding="utf-8")
                                for line in txt_blob.splitlines():
                                    if (not keep_comments) and line.startswith("#"):
                                        continue
                                    out.write(line + "\n")
                                out.write("\n")

                    # --- Organize Outputs (Audit/Tracking/Physics) ---
                    # Subfolders already exist; move postprocess_ot outputs from tracking/ to audit/ and physics/
                    dir_audit = run_dir / "audit"
                    dir_tracking = run_dir / "tracking"
                    dir_physics = run_dir / "physics"

                    # Helper to move file if exists
                    def _move_to(src_path: Path, dest_dir: Path) -> None:
                        if src_path.exists():
                            try:
                                src_path.rename(dest_dir / src_path.name)
                            except Exception as e:
                                self._log(f"WARN: failed to move {src_path.name} -> {dest_dir.name}: {e}")

                    # 1. Audit: psd_fit and calibration written by postprocess_ot to tracking/ -> move to audit
                    _move_to(_tracking / f"{stem}_psd_fit.json", dir_audit)
                    _move_to(_tracking / f"{stem}_calibration.json", dir_audit)

                    # 2. Tracking: trajectory, after.png, after_raw.png already written to tracking/; no move needed

                    # 3. Physics: move postprocess_ot outputs from tracking/ to physics; compare/drag already in physics/
                    _move_to(_msd, dir_physics)
                    _move_to(_psd_x, dir_physics)
                    _move_to(_psd_y, dir_physics)
                    _move_to(_cal_csv, dir_physics)
                    _move_to(_hist_x, dir_physics)
                    _move_to(_hist_y, dir_physics)
                    _move_to(_hist_r, dir_physics)
                    _move_to(_derived, dir_physics)

                    # QC image under qc/ (postprocess_ot wrote it to tracking/)
                    dir_qc = run_dir / "qc"
                    dir_qc.mkdir(parents=True, exist_ok=True)
                    _move_to(_tracking / f"{stem}_qc.png", dir_qc)

                    # IMPORTANT: run.json stays in ROOT; _qc.png under qc/; _results.* under summary/.

                except Exception as e:
                    self._log(f"WARN: results export/organization failed ({file_path.name}): {e!r}")

                # --- OT canonical metadata (item.json + batch.json) ---
                try:
                    if _dataset_item_root is not None:
                        # Dataset mode: update existing item.json with canonical fields.
                        from barakuda.devices.optical_tweezers.manifest import (
                            build_item_manifest_payload,
                        )
                        _item_json_path = _dataset_item_root / "item.json"
                        try:
                            _existing_item = json.loads(_item_json_path.read_text(encoding="utf-8"))
                        except Exception:
                            _existing_item = {}
                        _updated = build_item_manifest_payload(
                            item_root=_dataset_item_root,
                            item_id=_dataset_item_root.name,
                            fps=fps,
                            width_px=_reader_w,
                            height_px=_reader_h,
                            frame_count=fc,
                            roi=list(file_roi_rect) if file_roi_rect else None,
                            analysis_dir=run_dir,
                            um_per_px=um_per_px if um_per_px else None,
                            um_per_px_source=um_src if um_src else None,
                            status="analyzed",
                            existing_payload=_existing_item,
                        )
                        _item_json_path.write_text(
                            json.dumps(_updated, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    elif _ot_items_root is not None and _ot_batch_id is not None and _item_root_for_run is not None:
                        _item_id = _item_id_for_run
                        _item_root = _item_root_for_run
                        _src_video = Path(file_path)

                        # C) copy raw video into item_root/raw/
                        _dst_video = _item_root / "raw" / _src_video.name
                        if not _dst_video.exists() or _dst_video.stat().st_size != _src_video.stat().st_size:
                            shutil.copy2(_src_video, _dst_video)

                        # D) copy acquisition meta if present next to source video
                        _meta_src: Path | None = None
                        for _mc in (
                            _src_video.parent / f"{_src_video.stem}_meta.json",
                            _src_video.parent / f"{_src_video.name}_meta.json",
                        ):
                            if _mc.exists():
                                _meta_src = _mc
                                break
                        _archived_meta: str | None = None
                        if _meta_src is not None:
                            shutil.copy2(_meta_src, _item_root / "raw" / "video_meta.json")
                            _archived_meta = "raw/video_meta.json"

                        # E) run_dir IS item_root/module/ot/ — no copy required (STEP A)

                        # F) artifacts inventory (recursive under item_root)
                        _inv: list[str] = []
                        for _ap in _item_root.rglob("*"):
                            if _ap.is_file():
                                try:
                                    _inv.append(str(_ap.relative_to(_item_root)).replace("\\", "/"))
                                except Exception:
                                    pass

                        from barakuda.devices.optical_tweezers.manifest import (
                            build_item_manifest_payload,
                        )
                        _new_payload = build_item_manifest_payload(
                            item_root=_item_root,
                            item_id=_item_id,
                            batch_id=_ot_batch_id,
                            source_input_path=str(file_path),
                            acquisition_video=_dst_video,
                            acquisition_meta=(_item_root / "raw" / "video_meta.json") if _archived_meta else None,
                            fps=fps,
                            width_px=_reader_w,
                            height_px=_reader_h,
                            frame_count=fc,
                            roi=list(file_roi_rect) if file_roi_rect else None,
                            analysis_dir=run_dir,
                            um_per_px=um_per_px if um_per_px else None,
                            um_per_px_source=um_src if um_src else None,
                            status="analyzed",
                        )
                        (_item_root / "item.json").write_text(
                            json.dumps(_new_payload, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )

                        # G) write/update batch.json
                        _batch_json_path = _ot_mirror_root / "batch.json"
                        _batch_items_entry = {
                            "item_id": _item_id,
                            "source_file_name": _src_video.name,
                            "item_path": f"items/{_item_id}/",
                        }
                        _ot_batch_items.append(_batch_items_entry)
                        _batch_payload: dict = {
                            "schema_version": 1,
                            "module": "ot",
                            "batch_id": _ot_batch_id,
                            "created_at": _ot_batch_created_at,
                            "items": _ot_batch_items,
                        }
                        if _batch_json_path.exists():
                            try:
                                _existing = json.loads(_batch_json_path.read_text(encoding="utf-8"))
                                _existing_ids = {i["item_id"] for i in _existing.get("items", [])}
                                for _bi in _ot_batch_items:
                                    if _bi["item_id"] not in _existing_ids:
                                        _existing.setdefault("items", []).append(_bi)
                                _batch_payload = _existing
                            except Exception:
                                pass
                        _batch_json_path.write_text(
                            json.dumps(_batch_payload, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                except Exception as _mirror_err:
                    self._log(f"WARN: OT canonical metadata failed ({file_path.name}): {_mirror_err!r}")

                dataset_set_status_fn(file_path, "done")
                self._log(f"OK: {file_path.name} -> {run_id}")

            except Exception as e:
                dataset_set_status_fn(file_path, "failed")
                self._log(f"ERROR: {file_path.name}: {e!r}")

            done += 1
            progress_fn(done, len(ok_paths), file_path.name, 100)

        self._log("Run Batch done ✅")

    def run_afm_batch(
        self,
        file_paths: list[Path],
        roi_rect: tuple[int, int, int, int],
        afm_params: dict,
        dataset_set_status_fn: Callable[[Path, str], None],
        progress_fn: Callable[[int, int, str, int], None],
    ) -> None:
        import csv
        import json
        import numpy as np
        import imageio.v3 as iio

        from barakuda.devices.afm.core.afm_v2_pipeline import run_afm_v2, AfmV2Params
        from barakuda.devices.afm.core.overlay_ellipse import render_ellipse_overlay

        total = len(file_paths)
        progress_fn(0, total, "", 0)

        # ROI
        x, y, w, h = roi_rect

        def _f(key, default): return float(afm_params.get(key, default))
        def _i(key, default): return int(afm_params.get(key, default))
        def _b(key, default): return bool(afm_params.get(key, default))
        def _s(key, default): return str(afm_params.get(key, default))

        for i, p in enumerate(file_paths, start=1):
            try:
                dataset_set_status_fn(p, "running")

                # --- LOAD IMAGE ---
                loader_meta = {}
                if str(p).lower().endswith(".spm"):
                    try:
                        from barakuda.devices.afm.io.afmreader_loader import load_spm_height
                        img, loader_meta = load_spm_height(str(p))
                        self._log(f"[AFM] Loaded .spm via {loader_meta.get('loader', '?')}: "
                                  f"channel={loader_meta.get('selected_channel', '?')}, "
                                  f"shape={loader_meta.get('shape', '?')}, "
                                  f"px_to_nm={loader_meta.get('pixel_to_nm', '?')}")
                    except Exception as e:
                        self._log(f"ERROR: Failed to load .spm file {p.name}: {e!r}")
                        dataset_set_status_fn(p, "failed")
                        continue
                else:
                    img_orig = iio.imread(p)
                    img = img_orig
                    if img.ndim == 3:
                        if img.shape[-1] >= 3:
                            img = (img[..., 0].astype(np.float32) * 0.299 +
                                   img[..., 1].astype(np.float32) * 0.587 +
                                   img[..., 2].astype(np.float32) * 0.114)
                        else:
                            img = img[..., 0]
                    img = np.asarray(img, dtype=np.float32)
                    loader_meta = {"loader": "imageio", "loader_reason": "standard image file"}

                H, W = int(img.shape[0]), int(img.shape[1])
                # clamp ROI
                x0 = max(0, min(int(x), W - 1))
                y0 = max(0, min(int(y), H - 1))
                w0 = max(1, min(int(w), W - x0))
                h0 = max(1, min(int(h), H - y0))

                roi_img = img[y0:y0 + h0, x0:x0 + w0]

                cfg = {
                    "device": "afm",
                    "method": "AFM_V2",
                    "roi_rect": [x0, y0, w0, h0],
                    "params": afm_params,
                }

                run = self.run_manager.create_run(input_path=p, config=cfg)
                run_dir = run.run_dir
                stem = p.stem

                # --- BUILD V2 PARAMS (Cellpose-only) ---
                _cp_diam_px = afm_params.get("cp_diameter_px")
                p_v2 = AfmV2Params(
                    compute_profile=_s("compute_profile", "auto"),
                    preview_fast_mode=_b("preview_fast_mode", False),
                    preview_downscale=_f("preview_downscale", 0.5),
                    invert=_b("invert", False),
                    clip_p_low=_f("clip_p_low", 1.0),
                    clip_p_high=_f("clip_p_high", 99.0),
                    cp_model=_s("cp_model", "cyto3"),
                    cp_diameter_mode=_s("cp_diameter_mode", "auto"),
                    cp_diameter_px=int(_cp_diam_px) if _cp_diam_px is not None else None,
                    cp_flow_threshold=_f("cp_flow_threshold", 0.4),
                    cp_cellprob_threshold=_f("cp_cellprob_threshold", -0.5),
                    rods_only=_b("rods_only", True),
                    rods_min_major_axis_px=_f("rods_min_major_axis_px", 12.0),
                    rods_min_aspect_ratio=_f("rods_min_aspect_ratio", 1.8),
                    rods_min_eccentricity=_f("rods_min_eccentricity", 0.65),
                    rods_min_area_px=_i("rods_min_area_px", 8),
                    ellipse_thickness_px=_i("ellipse_thickness_px", 2),
                    ellipse_alpha=_f("ellipse_alpha", 0.6),
                )

                # --- RUN V2 PIPELINE ---
                res = run_afm_v2(roi_img, p_v2, float(loader_meta.get("afm_um_per_px", 0.0)))
                labels = res["labels"]
                rod_labels = res["rod_labels"]
                rod_table = res["rod_table"]
                audit = res["audit"]

                # --- Map coords back to FULL image ---
                if "centroid_x" in rod_table and len(rod_table["centroid_x"]) > 0:
                    rod_table["centroid_x"] += x0
                    rod_table["centroid_y"] += y0

                # --- Merge loader metadata into audit ---
                audit["device"] = "AFM"
                audit["loader"] = loader_meta.get("loader", "unknown")
                audit["selected_channel"] = loader_meta.get("selected_channel", "unknown")
                audit["afmreader_version"] = loader_meta.get("afmreader_version", None)
                audit["pixel_to_nm"] = loader_meta.get("pixel_to_nm", 0.0)
                audit["pixel_to_nm_source"] = loader_meta.get("pixel_to_nm_source", "unknown")
                audit["afm_um_per_px"] = loader_meta.get("afm_um_per_px", 0.0)
                audit["afm_um_per_px_source"] = loader_meta.get("afm_um_per_px_source", "unknown")

                n_rods = len(rod_table.get("label", []))

                # --- EXPORT: rods_mask.png (FULL SIZE) ---
                rods_mask_path = run_dir / f"{stem}_rods_mask.png"
                full_mask = np.zeros((H, W), dtype=np.uint8)
                full_mask[y0:y0+h0, x0:x0+w0] = (rod_labels > 0).astype(np.uint8) * 255
                iio.imwrite(rods_mask_path, full_mask)

                # --- EXPORT: rods_props.csv (with orientation_folded_rad) ---
                rods_csv = run_dir / f"{stem}_rods_props.csv"
                cols = ["label", "centroid_x", "centroid_y", "orientation_rad",
                        "orientation_folded_rad",
                        "major_axis_px", "minor_axis_px", "aspect_ratio",
                        "eccentricity", "solidity", "area_px"]

                # Compute folded orientation: (pi/2) - abs(orientation_rad)
                import math as _math
                ori_raw = np.asarray(rod_table.get("orientation_rad", []), dtype=np.float64)
                ori_folded = ((_math.pi / 2.0) - np.abs(ori_raw))
                rod_table["orientation_folded_rad"] = ori_folded

                with rods_csv.open("w", encoding="utf-8", newline="") as f:
                    wcsv = csv.writer(f)
                    wcsv.writerow(cols)
                    for k in range(n_rods):
                        row = []
                        for c in cols:
                            val = rod_table[c][k]
                            row.append(f"{val:.6f}" if isinstance(val, (float, np.floating)) else str(val))
                        wcsv.writerow(row)

                # --- EXPORT: orientation histograms (Sturges, 4 variants) ---
                _ori_hist_audit = {}
                if n_rods > 0:
                    try:
                        import math as _math2
                        import matplotlib
                        matplotlib.use("Agg")
                        import matplotlib.pyplot as plt

                        sturges_k = max(1, _math2.ceil(_math2.log2(n_rods) + 1))
                        _ori_hist_audit = {"rule": "sturges", "n": n_rods, "bins": sturges_k}
                        _R2D = 180.0 / _math2.pi
                        _RWIDTH = 0.92

                        # ---------- helper: render one histogram ----------
                        def _render_hist(data, bins, hist_range, xlabel, ylabel,
                                         title, out_path, density=False):
                            counts, edges = np.histogram(
                                data, bins=bins, range=hist_range, density=density,
                            )
                            bw = np.diff(edges)
                            fig, ax = plt.subplots(figsize=(6, 4))
                            ax.bar(
                                edges[:-1] + bw * (1.0 - _RWIDTH) / 2.0,
                                counts, width=bw * _RWIDTH,
                                align="edge",
                                facecolor="none", edgecolor="black", linewidth=1.0,
                            )
                            ax.set_xlabel(xlabel)
                            ax.set_ylabel(ylabel)
                            ax.set_title(title)
                            fig.tight_layout()
                            fig.savefig(str(out_path), dpi=300, facecolor="white")
                            plt.close(fig)
                            return counts, edges

                        # ---- orientation_rad ----
                        range_raw = (-_math2.pi / 2, _math2.pi / 2)
                        title_raw = f"Orientation (N={n_rods}, bins={sturges_k})"

                        cnt_raw_c, edg_raw_c = _render_hist(
                            ori_raw, sturges_k, range_raw,
                            "Orientation (rad)", "Count", title_raw,
                            run_dir / f"{stem}_orientation_hist_rad_count.png",
                        )
                        cnt_raw_d, edg_raw_d = _render_hist(
                            ori_raw, sturges_k, range_raw,
                            "Orientation (°)", "Frequency (%)", title_raw,
                            run_dir / f"{stem}_orientation_hist_deg_density.png",
                            density=True,
                        )
                        # fix x-axis to degrees for the density plot
                        # (re-render with converted edges + percentage y)
                        cnt_raw_d2, _ = np.histogram(ori_raw * _R2D, bins=sturges_k,
                                                     range=(range_raw[0]*_R2D, range_raw[1]*_R2D),
                                                     density=True)
                        cnt_raw_d2_pct = cnt_raw_d2 * 100.0
                        edg_raw_d2 = edg_raw_d * _R2D
                        fig_d, ax_d = plt.subplots(figsize=(6, 4))
                        bw_d = np.diff(edg_raw_d2)
                        ax_d.bar(edg_raw_d2[:-1] + bw_d*(1-_RWIDTH)/2, cnt_raw_d2_pct,
                                 width=bw_d*_RWIDTH, align="edge",
                                 facecolor="none", edgecolor="black", linewidth=1.0)
                        ax_d.set_xlabel("Orientation (°)")
                        ax_d.set_ylabel("Frequency (%)")
                        ax_d.set_title(title_raw)
                        fig_d.tight_layout()
                        fig_d.savefig(str(run_dir / f"{stem}_orientation_hist_deg_density.png"),
                                      dpi=300, facecolor="white")
                        plt.close(fig_d)

                        # ---- orientation_folded_rad ----
                        range_fld = (0.0, _math2.pi / 2)
                        title_fld = f"Folded orientation (N={n_rods}, bins={sturges_k})"

                        cnt_fld_c, edg_fld_c = _render_hist(
                            ori_folded, sturges_k, range_fld,
                            "Folded orientation (rad)", "Count", title_fld,
                            run_dir / f"{stem}_orientation_folded_hist_rad_count.png",
                        )
                        cnt_fld_d2, _ = np.histogram(ori_folded * _R2D, bins=sturges_k,
                                                     range=(range_fld[0]*_R2D, range_fld[1]*_R2D),
                                                     density=True)
                        cnt_fld_d2_pct = cnt_fld_d2 * 100.0
                        edg_fld_d2 = edg_fld_c * _R2D
                        fig_f, ax_f = plt.subplots(figsize=(6, 4))
                        bw_f = np.diff(edg_fld_d2)
                        ax_f.bar(edg_fld_d2[:-1] + bw_f*(1-_RWIDTH)/2, cnt_fld_d2_pct,
                                 width=bw_f*_RWIDTH, align="edge",
                                 facecolor="none", edgecolor="black", linewidth=1.0)
                        ax_f.set_xlabel("Folded orientation (°)")
                        ax_f.set_ylabel("Frequency (%)")
                        ax_f.set_title(title_fld)
                        fig_f.tight_layout()
                        fig_f.savefig(str(run_dir / f"{stem}_orientation_folded_hist_deg_density.png"),
                                      dpi=300, facecolor="white")
                        plt.close(fig_f)

                        # --- JSON metadata (extended) ---
                        hist_json_path = run_dir / f"{stem}_orientation_hist.json"
                        hist_json_path.write_text(json.dumps({
                            "orientation_rad": {
                                "n_samples": n_rods,
                                "sturges_bins": sturges_k,
                                "range_rad": list(range_raw),
                                "range_deg": [range_raw[0]*_R2D, range_raw[1]*_R2D],
                                "bin_edges_rad": edg_raw_c.tolist(),
                                "bin_edges_deg": edg_raw_d2.tolist(),
                                "counts": cnt_raw_c.tolist(),
                                "density": cnt_raw_d2.tolist(),
                                "units": "rad",
                                "y_mode": "count+density",
                                "rwidth": _RWIDTH,
                                "parameter": "orientation_rad",
                                "pipeline_version": audit.get("pipeline_version", "AFM_V2_CELLPOSE"),
                                "compute_profile": cp_audit.get("compute_profile", "unknown"),
                            },
                            "orientation_folded_rad": {
                                "n_samples": n_rods,
                                "sturges_bins": sturges_k,
                                "range_rad": list(range_fld),
                                "range_deg": [range_fld[0]*_R2D, range_fld[1]*_R2D],
                                "bin_edges_rad": edg_fld_c.tolist(),
                                "bin_edges_deg": edg_fld_d2.tolist(),
                                "counts": cnt_fld_c.tolist(),
                                "density": cnt_fld_d2.tolist(),
                                "units": "rad",
                                "y_mode": "count+density",
                                "rwidth": _RWIDTH,
                                "parameter": "orientation_folded_rad",
                                "pipeline_version": audit.get("pipeline_version", "AFM_V2_CELLPOSE"),
                                "compute_profile": cp_audit.get("compute_profile", "unknown"),
                            },
                        }, indent=2, ensure_ascii=False), encoding="utf-8")

                    except Exception as e:
                        self._log(f"WARN: orientation histogram failed ({p.name}): {e!r}")

                # --- EXPORT: overlay.png (FULL SIZE with ROI box) ---
                if bool(afm_params.get("save_overlay", True)):
                    from barakuda.devices.afm.core.afm_v2_pipeline import _normalize
                    full_norm = _normalize(img, p_v2.invert, p_v2.clip_p_low, p_v2.clip_p_high)
                    full_img8 = (full_norm * 255.0).astype(np.uint8)
                    overlay = render_ellipse_overlay(full_img8, rod_table, thickness_px=int(p_v2.ellipse_thickness_px), ellipse_alpha=float(p_v2.ellipse_alpha))
                    
                    import cv2
                    cv2.rectangle(overlay, (x0, y0), (x0+w0, y0+h0), (255, 255, 0), max(1, int(p_v2.ellipse_thickness_px)))

                    overlay_path = run_dir / f"{stem}_overlay.png"
                    iio.imwrite(overlay_path, overlay)

                    # --- EXPORT: contours-only PNG (transparent background) ---
                    # Render ellipse outlines on a transparent RGBA canvas
                    contours_rgba = np.zeros((H, W, 4), dtype=np.uint8)  # fully transparent
                    # Reuse ellipse perimeter mask from overlay_ellipse logic
                    from skimage import draw as sk_draw, morphology as sk_morph
                    ell_mask = np.zeros((H, W), dtype=bool)
                    for _ki in range(n_rods):
                        _cy = float(rod_table["centroid_y"][_ki])
                        _cx = float(rod_table["centroid_x"][_ki])
                        _maj = float(rod_table["major_axis_px"][_ki])
                        _mio = float(rod_table["minor_axis_px"][_ki])
                        _ang = float(rod_table["orientation_rad"][_ki])
                        _rr = max(1, int(round(_maj / 2.0)))
                        _rc = max(1, int(round(_mio / 2.0)))
                        try:
                            _pr, _pc = sk_draw.ellipse_perimeter(
                                int(round(_cy)), int(round(_cx)),
                                _rr, _rc, orientation=-_ang, shape=(H, W),
                            )
                            ell_mask[_pr, _pc] = True
                        except Exception:
                            continue
                    if int(p_v2.ellipse_thickness_px) > 1:
                        ell_mask = sk_morph.binary_dilation(ell_mask, sk_morph.disk(int(p_v2.ellipse_thickness_px) - 1))
                    contours_rgba[ell_mask, 0] = 255  # R
                    contours_rgba[ell_mask, 1] = 255  # G
                    contours_rgba[ell_mask, 2] = 0    # B
                    contours_rgba[ell_mask, 3] = 255  # A (opaque where ellipse)
                    contours_path = run_dir / f"{stem}_contours.png"
                    iio.imwrite(contours_path, contours_rgba)

                # --- EXPORT: summary.json (full audit + top-level must-have) ---
                summary_json = run_dir / f"{stem}_summary.json"
                
                cp_audit = audit.get("cellpose", {})
                timings = audit.get("timings_ms", {})
                diam_eff = cp_audit.get("diameter_effective_px", "Auto")
                
                payload = {
                    # Top-level must-have keys (Bible spec)
                    "pipeline_version": audit.get("pipeline_version", "AFM_V2_CELLPOSE"),
                    "device": "AFM",
                    "loader": audit.get("loader", "unknown"),
                    "selected_channel": audit.get("selected_channel", "unknown"),
                    "afm_um_per_px": audit.get("afm_um_per_px", 0.0),
                    "afm_um_per_px_source": audit.get("afm_um_per_px_source", "unknown"),
                    "afm_scan_size_um": loader_meta.get("afm_scan_size_um", 0.0),
                    
                    # Compute & Environment
                    "compute_profile": cp_audit.get("compute_profile", "unknown"),
                    "compute_device_resolved": cp_audit.get("device", "unknown"),
                    "torch_version": cp_audit.get("torch_version", "unknown"),
                    "cellpose_version": cp_audit.get("cellpose_version", "unknown"),
                    
                    # Core AFM Params
                    "cellpose_model": cp_audit.get("cellpose_model", p_v2.cp_model),
                    "diameter_mode": p_v2.cp_diameter_mode,
                    "diameter_effective_px": diam_eff,
                    "flow_threshold": cp_audit.get("flow_threshold", p_v2.cp_flow_threshold),
                    "cellprob_threshold": cp_audit.get("cellprob_threshold", p_v2.cp_cellprob_threshold),
                    "rod_filter": audit.get("rod_filter", {}),
                    
                    # Performance & Diagnostics
                    "preview_downscale_applied": audit.get("preview_downscale_applied", False),
                    "preview_downscale_factor": audit.get("preview_downscale_factor", 1.0),
                    "timings_ms": timings,
                    
                    # Batch metadata
                    "n_labels": int(labels.max()),
                    "n_rods": n_rods,
                    "roi_rect": [x0, y0, w0, h0],
                    "source_image": p.name,
                    # Orientation histogram audit
                    "orientation_histogram": _ori_hist_audit,
                    # Full audit trace (for granular bug reports)
                    "audit": audit,
                }
                summary_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

                dataset_set_status_fn(p, "done")
                self._log(f"OK AFM: {p.name} -> {run.run_id} (rods={n_rods}, total_labels={int(labels.max())})")

            except Exception as e:
                dataset_set_status_fn(p, "failed")
                self._log(f"ERROR AFM: {p.name}: {e!r}")

            pct = int(round(100.0 * i / max(1, total)))
            progress_fn(i, total, p.name, pct)

        self._log("Run Batch done ✅")

    def compute_afm_preview(self, file_path: str, roi_rect, afm_params: dict):
        """Compute AFM preview overlay (yellow ellipse outlines).

        Returns:
          dict with keys: overlay (RGB uint8), n_rods (int)
        """
        import imageio.v2 as iio
        import numpy as np

        from barakuda.devices.afm.core.afm_v2_pipeline import run_afm_v2, AfmV2Params
        from barakuda.devices.afm.core.overlay_ellipse import render_ellipse_overlay

        loader_meta = None
        if file_path.lower().endswith(".spm"):
            from barakuda.devices.afm.io.afmreader_loader import load_spm_height
            img, loader_meta = load_spm_height(file_path)
            img_orig = img
        else:
            img_orig = iio.imread(file_path)

        self._last_afm_loader_meta = loader_meta
        img = img_orig

        # ensure 2D grayscale for segmentation (PNG can be RGB)
        if img.ndim == 3:
            if img.shape[-1] >= 3:
                img = (img[..., 0].astype(np.float32) * 0.299 +
                       img[..., 1].astype(np.float32) * 0.587 +
                       img[..., 2].astype(np.float32) * 0.114)
            else:
                img = img[..., 0]
        img = np.asarray(img, dtype=np.float32)

        # crop ROI (x, y, w, h) — clamped to image bounds
        x, y, w, h = roi_rect
        H, W = img.shape[:2]
        x = max(0, min(x, W - 1))
        y = max(0, min(y, H - 1))
        w = max(1, min(w, W - x))
        h = max(1, min(h, H - y))
        roi_img = img[y:y + h, x:x + w]

        # Build V2 params
        def _f(key, default): return float(afm_params.get(key, default))
        def _i(key, default): return int(afm_params.get(key, default))
        def _b(key, default): return bool(afm_params.get(key, default))
        def _s(key, default): return str(afm_params.get(key, default))

        p_v2 = AfmV2Params(
            invert=_b("invert", False),
            clip_p_low=_f("clip_p_low", 1.0),
            clip_p_high=_f("clip_p_high", 99.0),
            cp_model=_s("cp_model", "cyto3"),
            cp_diameter=_f("cp_diameter", 0.0),
            cp_flow_threshold=_f("cp_flow_threshold", 0.4),
            cp_cellprob_threshold=_f("cp_cellprob_threshold", -0.5),
            rods_only=_b("rods_only", True),
            rods_min_major_axis_px=_f("rods_min_major_axis_px", 12.0),
            rods_min_aspect_ratio=_f("rods_min_aspect_ratio", 1.8),
            rods_min_eccentricity=_f("rods_min_eccentricity", 0.65),
            rods_min_area_px=_i("rods_min_area_px", 8),
            ellipse_thickness_px=_i("ellipse_thickness_px", 2),
            ellipse_alpha=_f("ellipse_alpha", 0.6),
        )

        res = run_afm_v2(roi_img, p_v2)

        rod_table = res["rod_table"]
        n_rods = len(rod_table.get("label", []))

        # Overlay: single call to render_ellipse_overlay (no inline drawing)
        overlay = render_ellipse_overlay(roi_img, rod_table, thickness_px=int(p_v2.ellipse_thickness_px), ellipse_alpha=float(p_v2.ellipse_alpha))

        return {"overlay": overlay, "n_rods": n_rods}

    # NOTE: _build_afm_seg_params removed — legacy pipeline no longer used

