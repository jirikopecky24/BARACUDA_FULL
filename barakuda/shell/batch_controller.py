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
from barakuda.core.ot_report import (
    build_ot_item_summary,
    export_ot_batch_pdf,
    export_ot_item_pdf,
)
from barakuda.core.postprocess_ot import postprocess_trajectory_csv_inplace, PostprocessParams
from barakuda.core.ot_physics import DragParams, compute_dragging_from_offset, kappa_from_fc_n_per_m
from barakuda.core.trajectory_csv_io import read_trajectory_csv

from barakuda.core.tracking import Detection, choose_tracking_polarity, track_particle, Roi, TrackingMethod, roi_follow_center
from barakuda.devices.optical_tweezers.compute import resolve_compute_profile
from barakuda.devices.optical_tweezers.manifest import resolve_ot_input_path
from barakuda.devices.optical_tweezers import perf as ot_perf



@dataclass(frozen=True)
class PreviewResult:
    path: str
    ok: bool
    status: str
    message: str
    details: Dict[str, Any]


@dataclass(frozen=True)
class OTBatchInput:
    original_path: Path
    resolved_video_path: Optional[Path]
    item_json_path: Optional[Path] = None
    item_root: Optional[Path] = None


class BatchController:
    def __init__(self, runs_folder: Path, log_fn: Callable[[str], None]):
        self.run_manager = RunManager(Path(runs_folder))
        self._log = log_fn

        self._preview_done: bool = False
        self._last_preview_results: list[PreviewResult] = []
        self._preview_dir: Optional[Path] = None
        self._preview_report_json: str | None = None
        self._preview_report_path: Optional[Path] = None
        self._stop_requested = False
        self.gate_results: dict[Path, tuple[bool, str]] = {}
        self.last_ot_overlay_video_path: str | None = None
        self.last_ot_overlay_trajectory_path: str | None = None

    def _resolve_ot_runtime(self, tracking_params: Optional[dict] = None) -> dict[str, Any]:
        params = tracking_params or {}
        profile = str(params.get("compute_profile", "cpu"))
        method = str(params.get("method", "RADIAL_SYMMETRY"))
        return resolve_compute_profile(profile, method)

    def _get_ot_shadow_mode(self) -> str:
        mode = str(os.environ.get("BARAKUDA_OT_SHADOW_MODE", "off")).strip().lower()
        if mode in {"off", "full"}:
            return mode
        return "off"

    def _normalize_ot_postprocess_params(self, post_params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(post_params)
        diameter_um = float(normalized.get("bead_diameter_um", 1.0))
        if not np.isfinite(diameter_um) or diameter_um <= 0:
            raise ValueError("bead_diameter_um must be > 0")
        normalized["bead_diameter_um"] = float(diameter_um)
        normalized["bead_radius_um"] = float(diameter_um * 0.5)
        return normalized

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

    def _pairing_sort_key(self, p: Path) -> tuple[str, float, str]:
        t = self._parse_capture_tokens(p)
        if t.get("ok"):
            return (str(t["key"]), float(t["speed"]), str(p))
        return ("~", 1e99, str(p))

    @staticmethod
    def _normalize_ot_input(path: Path | str) -> OTBatchInput:
        resolved = resolve_ot_input_path(path)
        return OTBatchInput(
            original_path=Path(path),
            resolved_video_path=resolved.video_path,
            item_json_path=resolved.item_json_path,
            item_root=resolved.item_root,
        )

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
        self._preview_report_json = None
        self._preview_report_path = None

    def stop(self) -> None:
        """Request cooperative stop of the running batch."""
        self._stop_requested = True
        self._log("STOP requested: batch will stop at the next safe checkpoint.")

    def _clear_perf(self) -> None:
        if ot_perf.enabled():
            ot_perf.clear()

    def _log_perf_summary(self, scope: str, **extra: Any) -> None:
        if not ot_perf.enabled():
            return
        payload: dict[str, Any] = {}
        for key, value in extra.items():
            if value is not None:
                payload[key] = value
        stats = ot_perf.snapshot(reset=True)
        if stats:
            payload["stats"] = stats
        self._log(f"[OT perf] {scope}: {json.dumps(payload, ensure_ascii=False)}")

    def _resolve_auto_roi(
        self,
        reader: VideoReader,
        device_panel,
        tracking_params: dict[str, Any],
        post_params: dict[str, Any],
        *,
        log_name: str,
    ) -> tuple[int, int, int, int] | None:
        with ot_perf.record("batch.auto_roi.resolve"):
            from barakuda.devices.optical_tweezers.pipeline.auto_roi import auto_roi_rs

            scale_params = device_panel.get_scale_params()
            um_per_px_auto = float(scale_params.get("um_per_px", 0.0))
            dia_auto = float(post_params.get("bead_diameter_um", 1.0))
            margin_auto = float(tracking_params.get("roi_margin", 1.8))
            frame0 = reader.get_frame(0)
            roi = auto_roi_rs(frame0, um_per_px_auto, dia_auto, margin_factor=margin_auto)
            self._log(f"[OT] Auto ROI for {log_name}: {roi}")
            return roi

    def _resolve_locked_polarity(
        self,
        frame: np.ndarray,
        roi_obj: Roi,
        *,
        method: TrackingMethod,
        compute_device: str,
        invert: bool,
        blur_sigma: float,
        radial_grad_threshold: float,
        auto_polarity: bool,
        annulus_enabled: bool,
        annulus_auto: bool,
        annulus_r_inner_px: float | None,
        annulus_r_outer_px: float | None,
        annulus_profile_smooth: int,
    ) -> tuple[bool, Detection | None]:
        if not auto_polarity:
            return bool(invert), None
        chosen_invert, chosen_det = choose_tracking_polarity(
            frame,
            roi_obj,
            method=method,
            blur_sigma=blur_sigma,
            radial_grad_threshold=radial_grad_threshold,
            annulus_enabled=annulus_enabled,
            annulus_r_inner_px=annulus_r_inner_px,
            annulus_r_outer_px=annulus_r_outer_px,
            annulus_auto=annulus_auto,
            annulus_profile_smooth=annulus_profile_smooth,
            compute_device=compute_device,
        )
        return bool(chosen_invert), chosen_det

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
        self._clear_perf()
        preview_started = time.perf_counter()

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

        self._preview_dir = None
        self._preview_report_path = None

        results: list[PreviewResult] = []

        for p in file_paths:
            p = Path(p)
            if not p.exists():
                results.append(PreviewResult(str(p), False, "FAIL", "File not found", {}))
                continue

            original_input_path = p
            resolved_item_root: Optional[Path] = None
            resolved_item_json: Optional[Path] = None
            if device_id == "optical_tweezers":
                try:
                    normalized = self._normalize_ot_input(p)
                    resolved_item_root = normalized.item_root
                    resolved_item_json = normalized.item_json_path
                    if normalized.resolved_video_path is not None and normalized.resolved_video_path.exists():
                        p = normalized.resolved_video_path
                    elif normalized.item_json_path is not None or normalized.item_root is not None:
                        results.append(PreviewResult(
                            str(original_input_path), False, "FAIL",
                            "dataset item: no acquisition video found", {}
                        ))
                        continue
                except Exception as _mf_err:
                    results.append(PreviewResult(
                        str(original_input_path), False, "FAIL",
                        f"dataset item load error: {_mf_err!r}", {}
                    ))
                    continue

            if device_id == "optical_tweezers":
                if not is_video_file(p):
                    results.append(PreviewResult(str(original_input_path), False, "FAIL", "Not a video file", {}))
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
                    "original_input_path": str(original_input_path),
                    "resolved_video_path": str(p),
                    "item_json_path": (str(resolved_item_json) if resolved_item_json is not None else None),
                    "dataset_item_root": (str(resolved_item_root) if resolved_item_root is not None else None),
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
                results.append(PreviewResult(str(original_input_path), False, "FAIL", f"Cannot read video metadata: {e}", {}))
                continue

            if device_id != "optical_tweezers":
                try:
                    vr.close()
                except Exception:
                    pass
                results.append(PreviewResult(str(original_input_path), True, "OK", "Preview metadata OK", details))
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
                    tracking_params_for_roi = device_panel.get_tracking_params() if hasattr(device_panel, "get_tracking_params") else {}
                    post_params_for_roi = device_panel.get_postprocess_params() if hasattr(device_panel, "get_postprocess_params") else {}
                    file_roi = self._resolve_auto_roi(
                        vr,
                        device_panel,
                        tracking_params_for_roi,
                        post_params_for_roi,
                        log_name=p.name,
                    )
                except Exception as e:
                    self._log(f"WARN: auto ROI failed for {p.name}: {e!r}")
            
            if file_roi is None:
                file_roi = preview_roi_rect

            if file_roi is None:
                try:
                    vr.close()
                except Exception:
                    pass
                results.append(PreviewResult(str(original_input_path), False, "FAIL", "ROI not set (required for OT preview)", details))
                QApplication.processEvents()
                continue

            # Fetch tracking params once (deterministic)
            try:
                params = device_panel.get_tracking_params()
                ot_runtime = self._resolve_ot_runtime(params)
                method_str = str(params.get("method", "RADIAL_SYMMETRY"))
                try:
                    method = TrackingMethod(method_str)
                except Exception:
                    method = TrackingMethod.RADIAL_SYMMETRY

                roi_obj = Roi(*file_roi)
                details["compute_profile_requested"] = ot_runtime["requested_profile"]
                details["compute_profile_resolved"] = ot_runtime["resolved_profile"]
                details["compute_device"] = ot_runtime["resolved_device"]
                details["torch_version"] = ot_runtime["torch_version"]
                details["gpu_name"] = ot_runtime["gpu_name"]
                details["fallback_applied"] = ot_runtime["fallback_applied"]
                details["compute_fallback_reason"] = ot_runtime["fallback_reason"]
            except Exception as e:
                try:
                    vr.close()
                except Exception:
                    pass
                results.append(PreviewResult(str(original_input_path), False, "FAIL", f"Cannot read tracking params: {e}", details))
                QApplication.processEvents()
                continue

            samples: list[Dict[str, Any]] = []
            pass_count = 0
            fail_messages: list[str] = []
            locked_invert = bool(params.get("invert", True))
            locked_det: Detection | None = None

            # Loop sampled frames
            for fi in frame_indices:
                try:
                    frame = vr.get_frame(int(fi))
                    if locked_det is None:
                        locked_invert, locked_det = self._resolve_locked_polarity(
                            frame,
                            roi_obj,
                            method=method,
                            compute_device=str(ot_runtime.get("resolved_device", "cpu")),
                            invert=bool(params.get("invert", True)),
                            blur_sigma=float(params.get("blur_sigma", 1.2)),
                            radial_grad_threshold=float(params.get("radial_grad_threshold", 2.0)),
                            auto_polarity=bool(params.get("auto_polarity", True)),
                            annulus_enabled=bool(params.get("annulus_enabled", True)),
                            annulus_auto=bool(params.get("annulus_auto", True)) if bool(params.get("annulus_enabled", True)) else False,
                            annulus_r_inner_px=params.get("annulus_r_inner_px", None),
                            annulus_r_outer_px=params.get("annulus_r_outer_px", None),
                            annulus_profile_smooth=int(params.get("annulus_profile_smooth", 3)),
                        )
                    if int(fi) == int(frame_indices[0]) and locked_det is not None:
                        det = locked_det
                        locked_det = None
                    else:
                        det = track_particle(
                            frame,
                            roi_obj,
                            method=method,
                            compute_device=str(ot_runtime.get("resolved_device", "cpu")),
                            invert=locked_invert,
                            blur_sigma=float(params.get("blur_sigma", 1.2)),
                            radial_grad_threshold=float(params.get("radial_grad_threshold", 2.0)),
                            auto_polarity=False,
                            annulus_enabled=bool(params.get("annulus_enabled", True)),
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
                "roi": list(file_roi),
                "resolved_roi": list(file_roi),
                "polarity_locked_invert": bool(locked_invert),
                "pass_count": int(pass_count),
                "sample_n": int(n),
                "pass_ratio": float(ratio),
                "max_jump_px": float(max_jump),
                "median_quality": float(median_q),
                "fail_reason": "; ".join(fail_reasons),
                "samples": samples,
            })

            if ok_overall:
                results.append(PreviewResult(str(original_input_path), True, "OK", f"OT gate PASS ({pass_count}/{n})", details))
            else:
                msg = f"OT gate FAIL ({pass_count}/{n})"
                fr = details.get("fail_reason", "")
                if fr:
                    msg += f" — {fr}"
                results.append(PreviewResult(str(original_input_path), False, "FAIL", msg, details))

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
        self._preview_report_json = json.dumps(report, indent=2, ensure_ascii=False)

        ok_all = all(r.ok for r in results)
        self._preview_done = ok_all
        self._last_preview_results = results

        # Build gate_results for shell icon updates
        self.gate_results = {}
        for r in results:
            self.gate_results[Path(r.path)] = (r.ok, r.message)

        self._log(f"Preview Gate finished: {'PASS' if ok_all else 'FAIL'} (items={len(results)})")
        self._log("Preview report prepared in memory.")
        self._log_perf_summary(
            "preview_gate",
            items=len(results),
            elapsed_ms=round((time.perf_counter() - preview_started) * 1000.0, 3),
        )
        return results

    def get_preview_gate_results(self) -> list[PreviewResult]:
        """Last Preview Gate results (per-file)."""
        return list(self._last_preview_results)

    def get_preview_gate_report_path(self) -> Path | None:
        """Path to preview_report.json for the last gate run."""
        p = self._preview_report_path
        if p is None:
            return None
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

        ok_inputs: list[OTBatchInput] = []
        for r in self._last_preview_results:
            if not r.ok:
                continue
            resolved_video = Path(r.details.get("resolved_video_path") or r.path)
            item_json_path = r.details.get("item_json_path")
            item_root = r.details.get("dataset_item_root")
            ok_inputs.append(
                OTBatchInput(
                    original_path=Path(r.path),
                    resolved_video_path=resolved_video,
                    item_json_path=(Path(item_json_path) if item_json_path else None),
                    item_root=(Path(item_root) if item_root else None),
                )
            )
        if checked_paths is not None:
            cset = {str(Path(p)) for p in checked_paths}
            ok_inputs = [entry for entry in ok_inputs if str(entry.original_path) in cset]

        if not ok_inputs:
            self._log("Run Batch: nothing to run (0 checked PASS items).")
            return

        self._log(f"Run Batch start: PASS items={len(ok_inputs)}")
        self._stop_requested = False
        self.last_ot_overlay_video_path = None
        self.last_ot_overlay_trajectory_path = None
        progress_fn(0, len(ok_inputs), "", 0)

        if device_id != "optical_tweezers":
            self._log(f"Run Batch: device '{device_id}' not implemented yet.")
            return

        # Note: We now fetch parameters *inside* the loop so that if device_panel
        # supports per-video overrides (like MockPanel does), we use them.
        
        base_roi = Roi(*roi_rect)

        ok_inputs = sorted(ok_inputs, key=lambda entry: self._pairing_sort_key(entry.resolved_video_path or entry.original_path))
        preview_result_by_path = {Path(r.path): r for r in self._last_preview_results}

        _ot_mirror_root: Path | None = None
        _ot_items_root: Path | None = None
        _ot_output_root: Path | None = None
        _ot_batch_id: str | None = None
        _ot_batch_created_at: str | None = None
        _ot_batch_items: list[dict] = []
        _ot_batch_preview_report_written = False
        _ot_report_items: list[dict[str, Any]] = []
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
        for batch_input in ok_inputs:
            if self._stop_requested:
                self._log("Batch stopped before processing next file.")
                break
            run_dir: Path | None = None
            dir_audit: Path | None = None
            dir_results: Path | None = None
            dir_csv: Path | None = None
            run_id: str | None = None
            self._clear_perf()
            file_started = time.perf_counter()
            auto_roi_reused = False
            tracking_elapsed_ms: float | None = None
            postprocess_elapsed_ms: float | None = None
            locked_invert = False

            original_input_path = Path(batch_input.original_path)
            file_path = Path(batch_input.resolved_video_path)
            dataset_set_status_fn(original_input_path, "running")
            
            # Inform the mock panel of the current file being processed
            if hasattr(device_panel, "set_current_path"):
                device_panel.set_current_path(str(original_input_path))
                
            tracking_params = device_panel.get_tracking_params()
            post_params = self._normalize_ot_postprocess_params(device_panel.get_postprocess_params())
            post_params.setdefault("temperature_c", 25.0)
            ot_runtime = self._resolve_ot_runtime(tracking_params)
            shadow_mode = self._get_ot_shadow_mode()
            ot_runtime["shadow_mode"] = shadow_mode
            
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

            if ot_runtime["fallback_applied"]:
                self._log(
                    "[OT runtime] "
                    f"requested={ot_runtime['requested_profile']} -> "
                    f"resolved={ot_runtime['resolved_profile']} "
                    f"({ot_runtime['fallback_reason']})"
                )
            else:
                self._log(
                    "[OT runtime] "
                    f"requested={ot_runtime['requested_profile']} -> "
                    f"resolved={ot_runtime['resolved_profile']} "
                    f"device={ot_runtime['resolved_device']}"
                )
            if ot_runtime["resolved_device"] == "cuda":
                self._log(
                    "[OT runtime] "
                    f"GPU={ot_runtime['gpu_name']} "
                    f"torch={ot_runtime['torch_version']}"
                )
            self._log(f"[OT runtime] shadow_mode={shadow_mode}")

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
                        preview_result = preview_result_by_path.get(original_input_path)
                        preview_roi = preview_result.details.get("resolved_roi") if preview_result is not None else None
                        if isinstance(preview_roi, list) and len(preview_roi) == 4:
                            file_roi_rect = tuple(int(v) for v in preview_roi)
                            auto_roi_reused = True
                            self._log(f"[OT] Reusing preview Auto ROI for {file_path.name}: {file_roi_rect}")
                        else:
                            _resolved_auto_roi = self._resolve_auto_roi(
                                reader,
                                device_panel,
                                tracking_params,
                                post_params,
                                log_name=file_path.name,
                            )
                            if _resolved_auto_roi is not None:
                                file_roi_rect = _resolved_auto_roi
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
                # 2) Otherwise fall back to UI value (default should be 0.060420 µm/px).
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
                    "runtime": ot_runtime,
                    "tracking": {
                        "method": method.value,
                        "compute_profile": ot_runtime["requested_profile"],
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

                stem = Path(file_path).stem

                # Detect whether this video lives inside an existing dataset item folder.
                _dataset_item_root = batch_input.item_root or self._detect_dataset_item_root(file_path)
                _source_item_json_path = (
                    batch_input.item_json_path
                    or ((_dataset_item_root / "item.json") if _dataset_item_root is not None else None)
                )

                # STEP A: select output root
                if _ot_items_root is not None and _ot_batch_id is not None:
                    # All OT runs write into the selected Output Root, including dataset inputs.
                    _ot_items_root.mkdir(parents=True, exist_ok=True)  # lazy creation
                    _base_name = _dataset_item_root.name if _dataset_item_root is not None else stem
                    _base = re.sub(r"[^A-Za-z0-9._\-]", "_", _base_name)
                    _item_id_for_run = _base
                    _n_coll = 1
                    while (_ot_items_root / _item_id_for_run).exists():
                        _item_id_for_run = f"{_base}_{_n_coll:02d}"
                        _n_coll += 1
                    _item_root_for_run = _ot_items_root / _item_id_for_run
                    run_dir = _item_root_for_run / "analysis"
                    for _sd in ("raw",):
                        (_item_root_for_run / _sd).mkdir(parents=True, exist_ok=True)
                    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + stem
                else:
                    result = self.run_manager.create_run(file_path, config)
                    run_dir = result.run_dir
                    run_id = result.run_id
                    _item_id_for_run = None
                    _item_root_for_run = None
                    _dataset_item_root = None

                run_dir.mkdir(parents=True, exist_ok=True)
                dir_audit = run_dir / "audit"
                dir_results = run_dir / "results"
                dir_csv = run_dir / "csv"
                for _d in (dir_audit, dir_results, dir_csv):
                    _d.mkdir(parents=True, exist_ok=True)

                run_json_payload = {
                    "run_id": run_id,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "input_path": str(file_path),
                    "config": config,
                }
                run_json_path = dir_audit / "run.json"
                if _item_root_for_run is None and (run_dir / "run.json").exists():
                    try:
                        (run_dir / "run.json").rename(run_json_path)
                    except Exception:
                        run_json_path.write_text(
                            json.dumps(run_json_payload, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                else:
                    run_json_path.write_text(
                        json.dumps(run_json_payload, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )

                _shadow_progress_span = 40 if shadow_mode == "full" else 0
                _main_progress_base = _shadow_progress_span
                _main_progress_span = max(1, 100 - _main_progress_base)

                def _emit_main_progress(raw_pct: int) -> None:
                    pct = int(round(_main_progress_base + (_main_progress_span * max(0, min(100, raw_pct)) / 100.0)))
                    progress_fn(done, len(ok_inputs), file_path.name, max(0, min(100, pct)))
                
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
                            "runtime": ot_runtime,
                            "tracking": config["tracking"],
                            "calibration": config["calibration"],
                            "progress_cb": lambda pct, msg="": progress_fn(
                                done,
                                len(ok_inputs),
                                file_path.name,
                                int(round((_shadow_progress_span * max(0, min(100, pct))) / 100.0)),
                            ),
                            "log_progress": lambda msg: self._log(f"[OT shadow] {msg}"),
                            "should_stop": lambda: self._stop_requested,
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
                            "strategy_params": post_params
                        }
                        
                        pipeline.run(str(file_path), shadow_config)
                        
                        _trace("EXIT shadow OK")
                        self._log(f"[OT shadow] OTPipeline finished successfully for {file_path.name}.")
                    except InterruptedError as err:
                        _trace(f"EXIT shadow STOP: {err!r}")
                        self._log(f"[OT shadow] Stopped: {err}")
                        self._stop_requested = True
                    except Exception as err:
                        _trace(f"EXIT shadow FAIL: {err!r}")
                        import traceback
                        self._log(f"[OT shadow] OTPipeline failed: {err!r}")
                        self._log(traceback.format_exc())
                else:
                    self._log(f"[OT shadow] Skipped for {file_path.name} (shadow_mode=off).")
                # -----------------------------------

                traj_path = dir_csv / f"{stem}_trajectory.csv"

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
                    locked_invert = invert
                    locked_det: Detection | None = None

                    total_frames = max(1, e - s + 1)
                    tracking_started = time.perf_counter()

                    for fi in range(s, e + 1):
                        if self._stop_requested:
                            self._log(f"Batch stopped during '{file_path.name}' at frame {fi}.")
                            break

                        # Per-frame progress (throttled: every 10 frames + first + last)
                        frame_idx = fi - s
                        if frame_idx % 10 == 0 or fi == e:
                            pct = int(100 * frame_idx / total_frames)
                            _emit_main_progress(pct)

                        frame = reader.get_frame(fi)
                        roi_obj = current_roi
                        if locked_det is None:
                            locked_invert, locked_det = self._resolve_locked_polarity(
                                frame,
                                roi_obj,
                                method=method,
                                compute_device=str(ot_runtime.get("resolved_device", "cpu")),
                                invert=invert,
                                blur_sigma=blur_sigma,
                                radial_grad_threshold=grad_th,
                                auto_polarity=auto_pol,
                                annulus_enabled=ann_enabled,
                                annulus_auto=ann_auto if ann_enabled else False,
                                annulus_r_inner_px=ann_r_in,
                                annulus_r_outer_px=ann_r_out,
                                annulus_profile_smooth=ann_smooth,
                            )
                        if fi == s and locked_det is not None:
                            det = locked_det
                            locked_det = None
                        else:
                            det = track_particle(
                                frame,
                                roi_obj,
                                method=method,
                                compute_device=str(ot_runtime.get("resolved_device", "cpu")),
                                invert=locked_invert,
                                blur_sigma=blur_sigma,
                                radial_grad_threshold=grad_th,
                                auto_polarity=False,
                                annulus_enabled=ann_enabled,
                                annulus_auto=ann_auto if ann_enabled else False,
                                annulus_r_inner_px=ann_r_in,
                                annulus_r_outer_px=ann_r_out,
                                annulus_profile_smooth=ann_smooth,
                            )

                        if adaptive_roi and fi > s:
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
                tracking_elapsed_ms = round((time.perf_counter() - tracking_started) * 1000.0, 3)

                if self._stop_requested:
                    _ot_report_items.append(
                        build_ot_item_summary(
                            run_dir=run_dir,
                            base_name=stem,
                            item_id=_item_id_for_run or (_dataset_item_root.name if _dataset_item_root is not None else stem),
                            source_input_path=str(original_input_path),
                            original_input_path=str(original_input_path),
                            resolved_video_path=str(file_path),
                            status="stopped",
                            run_id=run_id,
                            batch_id=_ot_batch_id,
                            output_root=(str(_ot_output_root) if _ot_output_root is not None else None),
                            error="Run stopped by user.",
                            file_name=file_path.name,
                        )
                    )
                    dataset_set_status_fn(original_input_path, "stopped")
                    done += 1
                    progress_fn(done, len(ok_inputs), file_path.name, 100)
                    break

                # Finalize preview report placement (never crash the run)
                try:
                    if self._preview_report_json:
                        if _ot_mirror_root is not None and not _ot_batch_preview_report_written:
                            _ot_mirror_root.mkdir(parents=True, exist_ok=True)
                            preview_report_path = _ot_mirror_root / "preview_report.json"
                            preview_report_path.write_text(
                                self._preview_report_json,
                                encoding="utf-8",
                            )
                            self._preview_report_path = preview_report_path
                            _ot_batch_preview_report_written = True
                        elif _item_root_for_run is not None:
                            preview_report_path = dir_audit / "preview_report.json"
                            preview_report_path.write_text(
                                self._preview_report_json,
                                encoding="utf-8",
                            )
                            self._preview_report_path = preview_report_path
                except Exception as e:
                    self._log(f"WARN: preview report finalization failed ({file_path.name}): {e!r}")

                self.last_ot_overlay_video_path = str(file_path)
                self.last_ot_overlay_trajectory_path = str(traj_path)

                if pp_enabled:
                    try:
                        post_started = time.perf_counter()
                        pp_summary = postprocess_trajectory_csv_inplace(
                            trajectory_csv_path=traj_path,
                            fps=fps,
                            um_per_px=um_per_px,
                            params=pp,
                            start_frame=int(s),
                            end_frame=int(e),
                        )
                        (dir_audit / f"{stem}_postprocess.json").write_text(
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
                        postprocess_elapsed_ms = round((time.perf_counter() - post_started) * 1000.0, 3)
                    except Exception as e:
                        self._log(f"WARN: postprocess failed ({file_path.name}): {e!r}")

                # --- 2-video Pairing & Comparison (Brownian vs Dragging) ---
                try:
                    tok = self._parse_capture_tokens(file_path)
                    if tok.get("ok") and float(tok["speed"]) == 0.0:
                        # Store Brownian baseline info for later comparison
                        # Store paths after organize: psd_fit in audit/, trajectory in csv/
                        baseline_by_key[tok["key"]] = {
                            "path": str(file_path),
                            "run_dir": str(run_dir),
                            "base_name": str(file_path.stem),
                            "psd_fit_json": str(dir_audit / f"{file_path.stem}_psd_fit.json"),
                            "trajectory_csv": str(dir_csv / f"{file_path.stem}_trajectory.csv"),
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
                                    Path(dir_csv / f"{file_path.stem}_trajectory.csv"), axis=axis, um_per_px=ui_um_per_px, fraction=0.5, tail=True
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

                                # Write compare artifacts into CSV / audit outputs
                                compare_csv = dir_csv / f"{file_path.stem}_compare.csv"
                                compare_json = dir_audit / f"{file_path.stem}_compare.json"
                                drag_json = dir_audit / f"{file_path.stem}_drag.json"

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
                    # postprocess_ot writes to trajectory dir (run_dir/csv/)
                    _tracking = dir_csv
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
                        run_payload = json.loads((dir_audit / "run.json").read_text(encoding="utf-8"))
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
                        ("postprocess", dir_audit / f"{stem}_postprocess.json"),
                        ("calibration", _cal_json),
                    ]:
                        if pth.exists():
                            try:
                                _flatten(f"{tag}.", json.loads(pth.read_text(encoding="utf-8")), meta_pairs)
                            except Exception:
                                meta_pairs.append((f"{tag}_json_error", f"failed to parse {pth.name}"))

                    # --- _results.csv (single-file bundle; keep canonical CSVs too) ---
                    results_csv = dir_csv / f"{stem}_results.csv"
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

                    # --- Organize Outputs (Audit / CSV / Results) ---
                    # Subfolders already exist; move postprocess outputs by file type.
                    dir_tracking = dir_csv

                    # Helper to move file if exists
                    def _move_to(src_path: Path, dest_dir: Path) -> None:
                        if src_path.exists():
                            try:
                                src_path.rename(dest_dir / src_path.name)
                            except Exception as e:
                                self._log(f"WARN: failed to move {src_path.name} -> {dest_dir.name}: {e}")

                    # 1. Audit: all JSON artifacts go to audit
                    _move_to(_tracking / f"{stem}_psd_fit.json", dir_audit)
                    _move_to(_tracking / f"{stem}_calibration.json", dir_audit)

                    # 2. CSV: trajectory and all .csv stay in csv/

                    # 3. Results: all PNG artifacts go to results/
                    for _png_name in (
                        f"{stem}_qc.png",
                        f"{stem}_hist_x.png",
                        f"{stem}_hist_y.png",
                        f"{stem}_hist_r.png",
                    ):
                        _move_to(_tracking / _png_name, dir_results)

                    export_ot_results_xlsx(
                        output_dir=dir_results,
                        base_name=stem,
                        trajectory_csv_path=traj_path,
                        msd_csv_path=_msd,
                        psd_x_csv_path=_psd_x,
                        psd_y_csv_path=_psd_y,
                    )

                    # IMPORTANT: run.json lives in audit/; results workbook in results/; all CSV in csv/.

                except Exception as e:
                    self._log(f"WARN: results export/organization failed ({file_path.name}): {e!r}")

                item_summary = build_ot_item_summary(
                    run_dir=run_dir,
                    base_name=stem,
                    item_id=_item_id_for_run or (_dataset_item_root.name if _dataset_item_root is not None else stem),
                    source_input_path=str(original_input_path),
                    original_input_path=str(original_input_path),
                    resolved_video_path=str(file_path),
                    status="success",
                    run_id=run_id,
                    batch_id=_ot_batch_id,
                    output_root=(str(_ot_output_root) if _ot_output_root is not None else None),
                    file_name=file_path.name,
                )
                try:
                    if dir_results is not None:
                        item_pdf_path = dir_results / f"{stem}_summary.pdf"
                        export_ot_item_pdf(item_pdf_path, item_summary)
                        item_summary.setdefault("artifacts", {})["item_pdf"] = str(item_pdf_path)
                except Exception as e:
                    self._log(f"WARN: item report export failed ({file_path.name}): {e!r}")
                _ot_report_items.append(item_summary)

                # --- OT canonical metadata (item.json + batch.json) ---
                try:
                    if _ot_items_root is not None and _ot_batch_id is not None and _item_root_for_run is not None:
                        _item_id = _item_id_for_run
                        _item_root = _item_root_for_run
                        _src_video = Path(file_path)

                        # C) copy source video into item_root/raw/
                        _dst_video = _item_root / "raw" / _src_video.name
                        if not _dst_video.exists() or _dst_video.stat().st_size != _src_video.stat().st_size:
                            shutil.copy2(_src_video, _dst_video)

                        def _first_existing_path(*candidates: Path) -> Path | None:
                            for _candidate in candidates:
                                try:
                                    if _candidate is not None and _candidate.exists():
                                        return _candidate
                                except Exception:
                                    continue
                            return None

                        # D) copy acquisition meta / timestamps if available
                        _meta_src: Path | None = None
                        _ts_src: Path | None = None
                        if _dataset_item_root is not None:
                            _meta_src = _first_existing_path(
                                _dataset_item_root / "acquisition" / "video_meta.json",
                                _dataset_item_root / "raw" / "video_meta.json",
                            )
                            _ts_src = _first_existing_path(
                                _dataset_item_root / "acquisition" / "video_timestamps.csv",
                                _dataset_item_root / "raw" / "video_timestamps.csv",
                            )
                        if _meta_src is None:
                            _meta_src = _first_existing_path(
                                _src_video.parent / f"{_src_video.stem}_meta.json",
                                _src_video.parent / f"{_src_video.name}_meta.json",
                                _src_video.parent / "video_meta.json",
                            )
                        if _ts_src is None:
                            _ts_src = _first_existing_path(
                                _src_video.parent / f"{_src_video.stem}_timestamps.csv",
                                _src_video.parent / f"{_src_video.name}_timestamps.csv",
                                _src_video.parent / "video_timestamps.csv",
                            )

                        _archived_meta: str | None = None
                        _archived_ts: str | None = None
                        if _meta_src is not None:
                            shutil.copy2(_meta_src, _item_root / "raw" / "video_meta.json")
                            _archived_meta = "raw/video_meta.json"
                        if _ts_src is not None:
                            shutil.copy2(_ts_src, _item_root / "raw" / "video_timestamps.csv")
                            _archived_ts = "raw/video_timestamps.csv"

                        from barakuda.devices.optical_tweezers.manifest import (
                            build_item_manifest_payload,
                        )
                        _new_payload = build_item_manifest_payload(
                            item_root=_item_root,
                            item_id=_item_id,
                            batch_id=_ot_batch_id,
                            source_input_path=str(original_input_path),
                            acquisition_video=_dst_video,
                            acquisition_meta=(_item_root / "raw" / "video_meta.json") if _archived_meta else None,
                            acquisition_timestamps=(_item_root / "raw" / "video_timestamps.csv") if _archived_ts else None,
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

                        # E) Write lightweight link back into the source dataset item.
                        if _dataset_item_root is not None and _source_item_json_path is not None and _source_item_json_path.exists():
                            try:
                                _source_existing = json.loads(_source_item_json_path.read_text(encoding="utf-8"))
                            except Exception:
                                _source_existing = {}
                            _source_status = str(_source_existing.get("status", "acquired") or "acquired")
                            _source_updated = build_item_manifest_payload(
                                item_root=_dataset_item_root,
                                item_id=_dataset_item_root.name,
                                analysis_dir=run_dir,
                                status=_source_status,
                                existing_payload=_source_existing,
                            )
                            _source_analysis = dict(_source_updated.get("analysis") or {})
                            _source_analysis["ot_last_output_item"] = str(_item_root)
                            _source_analysis["ot_last_output_dir"] = str(run_dir)
                            _source_updated["analysis"] = _source_analysis
                            _source_item_json_path.write_text(
                                json.dumps(_source_updated, indent=2, ensure_ascii=False),
                                encoding="utf-8",
                            )

                        # F) write/update batch.json
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

                dataset_set_status_fn(original_input_path, "done")
                self._log(f"OK: {file_path.name} -> {run_id}")
                self._log_perf_summary(
                    f"run_batch:{file_path.name}",
                    auto_roi_reused=auto_roi_reused,
                    polarity_locked_invert=bool(locked_invert),
                    tracking_elapsed_ms=tracking_elapsed_ms,
                    postprocess_elapsed_ms=postprocess_elapsed_ms,
                    total_elapsed_ms=round((time.perf_counter() - file_started) * 1000.0, 3),
                )

            except Exception as e:
                _ot_report_items.append(
                    build_ot_item_summary(
                        run_dir=run_dir,
                        base_name=(Path(file_path).stem if 'file_path' in locals() else original_input_path.stem),
                        item_id=_item_id_for_run or (_dataset_item_root.name if '_dataset_item_root' in locals() and _dataset_item_root is not None else original_input_path.stem),
                        source_input_path=str(original_input_path),
                        original_input_path=str(original_input_path),
                        resolved_video_path=(str(file_path) if 'file_path' in locals() else None),
                        status="failed",
                        run_id=run_id,
                        batch_id=_ot_batch_id,
                        output_root=(str(_ot_output_root) if _ot_output_root is not None else None),
                        error=str(e),
                        file_name=(file_path.name if 'file_path' in locals() else original_input_path.name),
                    )
                )
                dataset_set_status_fn(original_input_path, "failed")
                self._log(f"ERROR: {file_path.name}: {e!r}")
                self._log_perf_summary(
                    f"run_batch:{file_path.name}:failed",
                    total_elapsed_ms=round((time.perf_counter() - file_started) * 1000.0, 3),
                )

            done += 1
            progress_fn(done, len(ok_inputs), file_path.name, 100)

        if _ot_mirror_root is not None and _ot_report_items:
            try:
                _ot_mirror_root.mkdir(parents=True, exist_ok=True)
                export_ot_batch_pdf(
                    _ot_mirror_root / "batch_summary.pdf",
                    {
                        "batch_id": _ot_batch_id,
                        "output_root": str(_ot_output_root) if _ot_output_root is not None else "",
                        "batch_root": str(_ot_mirror_root),
                        "items": _ot_report_items,
                    },
                )
            except Exception as e:
                self._log(f"WARN: batch PDF export failed: {e!r}")

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
        import math
        import numpy as np
        import imageio.v3 as iio

        from barakuda.core.afm_report import (
            build_afm_item_summary,
            export_afm_batch_pdf,
            export_afm_item_pdf,
        )
        from barakuda.devices.afm.core.overlay_ellipse import render_ellipse_overlay
        from barakuda.devices.afm.manifest import (
            build_item_manifest_payload,
            resolve_afm_input_path,
        )
        from barakuda.devices.afm.methods import get_afm_method

        total = len(file_paths)
        progress_fn(0, total, "", 0)
        x, y, w, h = roi_rect
        method_id = str(afm_params.get("afm_method", "rod_bacteria") or "rod_bacteria")
        method = get_afm_method(method_id)
        output_root = self.run_manager.runs_folder / "afm"
        batch_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        batch_root = output_root / batch_id
        items_root = batch_root / "items"
        items_root.mkdir(parents=True, exist_ok=True)
        batch_items: list[dict[str, Any]] = []
        report_items: list[dict[str, Any]] = []
        used_item_ids: set[str] = set()
        batch_created_at = datetime.now().isoformat(timespec="seconds")

        def _slug(text: str) -> str:
            candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip()).strip("._-")
            return candidate or "afm_item"

        def _unique_item_id(base: str) -> str:
            candidate = _slug(base)
            if candidate not in used_item_ids:
                used_item_ids.add(candidate)
                return candidate
            idx = 2
            while f"{candidate}_{idx}" in used_item_ids:
                idx += 1
            unique = f"{candidate}_{idx}"
            used_item_ids.add(unique)
            return unique

        self._stop_requested = False

        for i, original_path in enumerate(file_paths, start=1):
            if self._stop_requested:
                self._log("AFM batch stopped before processing next file.")
                break
            try:
                dataset_set_status_fn(original_path, "running")

                resolved = resolve_afm_input_path(original_path)
                input_path = resolved.image_path or resolved.resolved_input_path
                if not input_path.exists():
                    raise FileNotFoundError(f"AFM input not found: {input_path}")

                item_base = resolved.item_root.name if resolved.item_root is not None else input_path.stem
                item_id = _unique_item_id(item_base)
                item_root = items_root / item_id
                acquisition_dir = item_root / "acquisition"
                analysis_dir = item_root / "analysis"
                dir_audit = analysis_dir / "audit"
                dir_csv = analysis_dir / "csv"
                dir_results = analysis_dir / "results"
                for directory in (acquisition_dir, dir_audit, dir_csv, dir_results):
                    directory.mkdir(parents=True, exist_ok=True)

                # --- LOAD IMAGE ---
                loader_meta = {}
                if str(input_path).lower().endswith(".spm"):
                    try:
                        from barakuda.devices.afm.io.afmreader_loader import load_spm_height
                        img, loader_meta = load_spm_height(str(input_path))
                        self._log(f"[AFM] Loaded .spm via {loader_meta.get('loader', '?')}: "
                                  f"channel={loader_meta.get('selected_channel', '?')}, "
                                  f"shape={loader_meta.get('shape', '?')}, "
                                  f"px_to_nm={loader_meta.get('pixel_to_nm', '?')}")
                    except Exception as e:
                        self._log(f"ERROR: Failed to load .spm file {input_path.name}: {e!r}")
                        dataset_set_status_fn(original_path, "failed")
                        continue
                else:
                    img_orig = iio.imread(input_path)
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

                runtime_params = method.build_runtime_params(afm_params)
                cfg = {
                    "device": "afm",
                    "method": method_id,
                    "roi_rect": [x0, y0, w0, h0],
                    "params": afm_params,
                    "source_input_path": str(original_path),
                }
                run_id = f"{batch_id}-{item_id}"
                run_json_path = dir_audit / "run.json"
                run_json_path.write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                            "input_path": str(input_path),
                            "config": cfg,
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                stem = input_path.stem

                res = method.compute(roi_img, runtime_params, um_per_px=float(loader_meta.get("afm_um_per_px", 0.0)))
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
                audit["method_id"] = method_id
                audit["loader"] = loader_meta.get("loader", "unknown")
                audit["selected_channel"] = loader_meta.get("selected_channel", "unknown")
                audit["afmreader_version"] = loader_meta.get("afmreader_version", None)
                audit["pixel_to_nm"] = loader_meta.get("pixel_to_nm", 0.0)
                audit["pixel_to_nm_source"] = loader_meta.get("pixel_to_nm_source", "unknown")
                audit["afm_um_per_px"] = loader_meta.get("afm_um_per_px", 0.0)
                audit["afm_um_per_px_source"] = loader_meta.get("afm_um_per_px_source", "unknown")

                n_rods = len(rod_table.get("label", []))

                # --- EXPORT: rods_mask.png (FULL SIZE) ---
                rods_mask_path = dir_results / f"{stem}_rods_mask.png"
                full_mask = np.zeros((H, W), dtype=np.uint8)
                full_mask[y0:y0+h0, x0:x0+w0] = (rod_labels > 0).astype(np.uint8) * 255
                iio.imwrite(rods_mask_path, full_mask)

                # --- EXPORT: rods_props.csv (with orientation_folded_rad) ---
                rods_csv = dir_csv / f"{stem}_rods_props.csv"
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
                cp_audit = audit.get("cellpose", {})
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
                            dir_results / f"{stem}_orientation_hist_rad_count.png",
                        )
                        cnt_raw_d, edg_raw_d = _render_hist(
                            ori_raw, sturges_k, range_raw,
                            "Orientation (°)", "Frequency (%)", title_raw,
                            dir_results / f"{stem}_orientation_hist_deg_density.png",
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
                        fig_d.savefig(str(dir_results / f"{stem}_orientation_hist_deg_density.png"),
                                      dpi=300, facecolor="white")
                        plt.close(fig_d)

                        # ---- orientation_folded_rad ----
                        range_fld = (0.0, _math2.pi / 2)
                        title_fld = f"Folded orientation (N={n_rods}, bins={sturges_k})"

                        cnt_fld_c, edg_fld_c = _render_hist(
                            ori_folded, sturges_k, range_fld,
                            "Folded orientation (rad)", "Count", title_fld,
                            dir_results / f"{stem}_orientation_folded_hist_rad_count.png",
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
                        fig_f.savefig(str(dir_results / f"{stem}_orientation_folded_hist_deg_density.png"),
                                      dpi=300, facecolor="white")
                        plt.close(fig_f)

                        # --- JSON metadata (extended) ---
                        hist_json_path = dir_audit / f"{stem}_orientation_hist.json"
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
                    full_norm = _normalize(img, runtime_params.invert, runtime_params.clip_p_low, runtime_params.clip_p_high)
                    full_img8 = (full_norm * 255.0).astype(np.uint8)
                    overlay = render_ellipse_overlay(full_img8, rod_table, thickness_px=int(runtime_params.ellipse_thickness_px), ellipse_alpha=float(runtime_params.ellipse_alpha))
                    
                    import cv2
                    cv2.rectangle(overlay, (x0, y0), (x0+w0, y0+h0), (255, 255, 0), max(1, int(runtime_params.ellipse_thickness_px)))

                    overlay_path = dir_results / f"{stem}_overlay.png"
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
                    if int(runtime_params.ellipse_thickness_px) > 1:
                        ell_mask = sk_morph.binary_dilation(ell_mask, sk_morph.disk(int(runtime_params.ellipse_thickness_px) - 1))
                    contours_rgba[ell_mask, 0] = 255  # R
                    contours_rgba[ell_mask, 1] = 255  # G
                    contours_rgba[ell_mask, 2] = 0    # B
                    contours_rgba[ell_mask, 3] = 255  # A (opaque where ellipse)
                    contours_path = dir_results / f"{stem}_contours.png"
                    iio.imwrite(contours_path, contours_rgba)

                # --- EXPORT: summary.json (full audit + top-level must-have) ---
                summary_json = dir_audit / f"{stem}_summary.json"
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
                    "compute_profile_requested": cp_audit.get("requested_profile", cp_audit.get("compute_profile", "unknown")),
                    "compute_profile_resolved": cp_audit.get("resolved_profile", cp_audit.get("compute_profile", "unknown")),
                    "compute_profile": cp_audit.get("resolved_profile", cp_audit.get("compute_profile", "unknown")),
                    "compute_device_resolved": cp_audit.get("device", "unknown"),
                    "compute_backend": cp_audit.get("backend", "cellpose"),
                    "compute_fallback_applied": bool(cp_audit.get("fallback_applied", False)),
                    "compute_fallback_reason": cp_audit.get("fallback_reason", ""),
                    "torch_version": cp_audit.get("torch_version", "unknown"),
                    "cellpose_version": cp_audit.get("cellpose_version", "unknown"),
                    
                    # Core AFM Params
                    "cellpose_model": cp_audit.get("cellpose_model", runtime_params.cp_model),
                    "diameter_mode": runtime_params.cp_diameter_mode,
                    "diameter_effective_px": diam_eff,
                    "flow_threshold": cp_audit.get("flow_threshold", runtime_params.cp_flow_threshold),
                    "cellprob_threshold": cp_audit.get("cellprob_threshold", runtime_params.cp_cellprob_threshold),
                    "rod_filter": audit.get("rod_filter", {}),
                    
                    # Performance & Diagnostics
                    "preview_downscale_applied": audit.get("preview_downscale_applied", False),
                    "preview_downscale_factor": audit.get("preview_downscale_factor", 1.0),
                    "timings_ms": timings,
                    
                    # Batch metadata
                    "n_labels": int(labels.max()),
                    "n_rods": n_rods,
                    "method_id": method_id,
                    "roi_rect": [x0, y0, w0, h0],
                    "source_image": input_path.name,
                    # Orientation histogram audit
                    "orientation_histogram": _ori_hist_audit,
                    # Full audit trace (for granular bug reports)
                    "audit": audit,
                }
                summary_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

                archived_image = acquisition_dir / input_path.name
                if not archived_image.exists():
                    shutil.copy2(input_path, archived_image)

                item_payload = build_item_manifest_payload(
                    item_root=item_root,
                    item_id=item_id,
                    batch_id=batch_id,
                    source_input_path=str(original_path),
                    acquisition_image=archived_image,
                    analysis_dir=analysis_dir,
                    roi=[x0, y0, w0, h0],
                    afm_um_per_px=float(loader_meta.get("afm_um_per_px", 0.0) or 0.0),
                    afm_um_per_px_source=str(loader_meta.get("afm_um_per_px_source", "unknown")),
                    selected_channel=str(loader_meta.get("selected_channel", "unknown")),
                    params=dict(afm_params),
                    status="analyzed",
                )
                (item_root / "item.json").write_text(
                    json.dumps(item_payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                if resolved.item_json_path is not None and resolved.item_root is not None and resolved.item_json_path.exists():
                    try:
                        source_existing = json.loads(resolved.item_json_path.read_text(encoding="utf-8"))
                    except Exception:
                        source_existing = {}
                    source_updated = build_item_manifest_payload(
                        item_root=resolved.item_root,
                        item_id=resolved.item_root.name,
                        batch_id=str(source_existing.get("batch_id") or batch_id),
                        source_input_path=str(original_path),
                        analysis_dir=analysis_dir,
                        params=dict(afm_params),
                        status=str(source_existing.get("status", "acquired") or "acquired"),
                        existing_payload=source_existing,
                    )
                    source_analysis = dict(source_updated.get("analysis") or {})
                    source_analysis["afm_last_output_item"] = str(item_root)
                    source_analysis["afm_last_output_dir"] = str(analysis_dir)
                    source_updated["analysis"] = source_analysis
                    resolved.item_json_path.write_text(
                        json.dumps(source_updated, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )

                item_summary = build_afm_item_summary(
                    analysis_dir=analysis_dir,
                    base_name=stem,
                    item_id=item_id,
                    source_input_path=str(original_path),
                    status="success",
                    run_id=run_id,
                    batch_id=batch_id,
                    output_root=str(output_root),
                    file_name=input_path.name,
                )
                try:
                    item_pdf_path = dir_results / f"{stem}_summary.pdf"
                    export_afm_item_pdf(item_pdf_path, item_summary)
                    item_summary.setdefault("artifacts", {})["item_pdf"] = str(item_pdf_path)
                except Exception as e:
                    self._log(f"WARN: AFM item report export failed ({input_path.name}): {e!r}")
                report_items.append(item_summary)
                batch_items.append(
                    {
                        "item_id": item_id,
                        "source_file_name": input_path.name,
                        "item_path": f"items/{item_id}/",
                    }
                )

                dataset_set_status_fn(original_path, "done")
                self._log(f"OK AFM: {input_path.name} -> {run_id} (rods={n_rods}, total_labels={int(labels.max())})")

            except Exception as e:
                dataset_set_status_fn(original_path, "failed")
                self._log(f"ERROR AFM: {original_path.name}: {e!r}")

            pct = int(round(100.0 * i / max(1, total)))
            progress_fn(i, total, original_path.name, pct)

        batch_payload = {
            "schema_version": 1,
            "module": "afm",
            "batch_id": batch_id,
            "created_at": batch_created_at,
            "items": batch_items,
        }
        (batch_root / "batch.json").write_text(
            json.dumps(batch_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if report_items:
            try:
                export_afm_batch_pdf(
                    batch_root / "batch_summary.pdf",
                    {
                        "batch_id": batch_id,
                        "output_root": str(output_root),
                        "batch_root": str(batch_root),
                        "items": report_items,
                    },
                )
            except Exception as e:
                self._log(f"WARN: AFM batch PDF export failed: {e!r}")

        self._log("Run Batch done ✅")

    def compute_afm_preview(self, file_path: str, roi_rect, afm_params: dict):
        """Compute AFM preview overlay (yellow ellipse outlines).

        Returns:
          dict with keys: overlay (RGB uint8), n_rods (int)
        """
        import imageio.v2 as iio
        import numpy as np

        from barakuda.devices.afm.core.afm_v2_pipeline import _normalize
        from barakuda.devices.afm.core.overlay_ellipse import render_ellipse_overlay
        from barakuda.devices.afm.manifest import resolve_afm_input_path
        from barakuda.devices.afm.methods import get_afm_method

        resolved = resolve_afm_input_path(file_path)
        source_path = str(resolved.image_path or resolved.resolved_input_path)
        loader_meta = None
        if source_path.lower().endswith(".spm"):
            from barakuda.devices.afm.io.afmreader_loader import load_spm_height
            img, loader_meta = load_spm_height(source_path)
            img_orig = img
        else:
            img_orig = iio.imread(source_path)

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
        method = get_afm_method(afm_params.get("afm_method"))
        runtime_params = method.build_runtime_params(afm_params)
        res = method.compute(roi_img, runtime_params, um_per_px=float((loader_meta or {}).get("afm_um_per_px", 0.0)))

        rod_table = res["rod_table"]
        n_rods = len(rod_table.get("label", []))
        if "centroid_x" in rod_table and len(rod_table.get("centroid_x", [])) > 0:
            rod_table["centroid_x"] = rod_table["centroid_x"] + x
            rod_table["centroid_y"] = rod_table["centroid_y"] + y

        full_norm = _normalize(img, runtime_params.invert, runtime_params.clip_p_low, runtime_params.clip_p_high)
        full_img8 = (full_norm * 255.0).astype(np.uint8)
        overlay = render_ellipse_overlay(
            full_img8,
            rod_table,
            thickness_px=int(runtime_params.ellipse_thickness_px),
            ellipse_alpha=float(runtime_params.ellipse_alpha),
        )

        return {"overlay": overlay, "n_rods": n_rods, "loader_meta": loader_meta}

    # NOTE: _build_afm_seg_params removed — legacy pipeline no longer used

