from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Callable

import csv
import json
import time

from PyQt6.QtWidgets import QApplication

from barakuda.core.video_reader import VideoReader
from barakuda.core.video_io import is_video_file
from barakuda.core.run_manager import RunManager
from barakuda.core.calibration_store import load_dataset_scale
from barakuda.core.export_xlsx import export_ot_results_xlsx
from barakuda.core.postprocess_ot import postprocess_trajectory_csv_inplace, PostprocessParams
from barakuda.core.ot_physics import DragParams, compute_dragging_from_offset, kappa_from_fc_n_per_m
from barakuda.core.trajectory_csv_io import read_trajectory_csv

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
            if preview_roi_rect is None:
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

                roi_obj = Roi(*preview_roi_rect)
            except Exception as e:
                try:
                    vr.close()
                except Exception:
                    pass
                results.append(PreviewResult(str(p), False, "FAIL", f"Cannot read tracking params: {e}", details))
                QApplication.processEvents()
                continue

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

    # ---------------- Run Batch ----------------

    def run_batch(
        self,
        device_id: str,
        device_panel,
        roi_rect: tuple[int, int, int, int],
        dataset_set_status_fn: Callable[[Path, str], None],
        progress_fn: Callable[[int, int, str, int], None],
    ) -> None:
        if not self._preview_done:
            self._log("Run Batch blocked: Preview Gate has not passed.")
            return

        ok_paths = [Path(r.path) for r in self._last_preview_results if r.ok]
        if not ok_paths:
            self._log("Run Batch: nothing to run (0 PASS items).")
            return

        self._log(f"Run Batch start: PASS items={len(ok_paths)}")
        self._stop_requested = False
        self.last_after_overlay_path = None
        progress_fn(0, len(ok_paths), "", 0)
        QApplication.processEvents()

        if device_id != "optical_tweezers":
            self._log(f"Run Batch: device '{device_id}' not implemented yet.")
            return

        tracking_params = device_panel.get_tracking_params()
        post_params = device_panel.get_postprocess_params()
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
        )

        use_dataset_scale = bool(scale_params.get("use_dataset_scale", True))
        ui_um_per_px = float(scale_params.get("um_per_px", 0.0))

        base_roi = Roi(*roi_rect)

        ok_paths = [Path(p) for p in ok_paths]
        ok_paths = self._reorder_for_pairing(ok_paths)

        baseline_by_key: dict[str, dict[str, Any]] = {}

        done = 0
        for file_path in ok_paths:
            if self._stop_requested:
                self._log("Batch stopped before processing next file.")
                break

            file_path = Path(file_path)
            dataset_set_status_fn(file_path, "running")
            QApplication.processEvents()

            try:
                reader = VideoReader(file_path)
                fps = float(reader.meta.fps)
                fc = int(reader.meta.frame_count)

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
                if use_dataset_scale:
                    info = load_dataset_scale(file_path)
                    if info is not None and info.um_per_px is not None:
                        um_per_px = float(info.um_per_px)
                        um_src = str(info.source)
                else:
                    if ui_um_per_px > 0:
                        um_per_px = float(ui_um_per_px)
                        um_src = "ui"

                config = {
                    "device": {"id": "optical_tweezers"},
                    "tracking": {
                        "method": method.value,
                        "auto_polarity": auto_pol,
                        "invert": invert,
                        "blur_sigma": blur_sigma,
                        "radial_grad_threshold": grad_th,
                        "roi": list(roi_rect),
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
                    },
                }

                result = self.run_manager.create_run(file_path, config)
                run_dir = result.run_dir
                stem = Path(file_path).stem
                traj_path = run_dir / f"{stem}_trajectory.csv"

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
                    f_meta.write(f"# roi={list(roi_rect)}\n")
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
                            progress_fn(done, len(ok_paths), file_path.name, pct)
                            QApplication.processEvents()

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

                        if adaptive_roi:
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
                        QApplication.processEvents()

                reader.close()

                if self._stop_requested:
                    dataset_set_status_fn(file_path, "stopped")
                    done += 1
                    progress_fn(done, len(ok_paths), file_path.name, 100)
                    QApplication.processEvents()
                    break

                # Save overlays (never crash the run)
                try:
                    if first_frame is not None and first_xy is not None:
                        self.run_manager.save_overlay_png(
                            run_dir=run_dir,
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
                        # Raw frame for audit (optional)
                        # Raw frame for audit (optional)
                        self.run_manager.save_after_png(run_dir, last_frame, name=f"{stem}_after_raw.png")
                        # Overlay as 'after.png' (what user expects)
                        self.run_manager.save_overlay_png(
                            run_dir=run_dir,
                            frame_rgb=last_frame,
                            x=last_xy[0],
                            y=last_xy[1],
                            roi=(last_roi if last_roi is not None else roi_rect),
                            name=f"{stem}_after.png",
                        )
                        self.last_after_overlay_path = str(run_dir / f"{stem}_after.png")
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
                        (run_dir / f"{stem}_postprocess.json").write_text(
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
                        baseline_by_key[tok["key"]] = {
                            "path": str(file_path),
                            "run_dir": str(run_dir),
                            "base_name": str(file_path.stem),
                            "psd_fit_json": str(run_dir / f"{file_path.stem}_psd_fit.json"),
                            "trajectory_csv": str(run_dir / f"{file_path.stem}_trajectory.csv"),
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
                                    Path(run_dir / f"{file_path.stem}_trajectory.csv"), axis=axis, um_per_px=ui_um_per_px, fraction=0.5, tail=True
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

                                # Write compare artifacts into DRAG run dir
                                compare_csv = Path(run_dir) / f"{file_path.stem}_compare.csv"
                                compare_json = Path(run_dir) / f"{file_path.stem}_compare.json"
                                drag_json = Path(run_dir) / f"{file_path.stem}_drag.json"

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
                    _msd = run_dir / f"{stem}_msd.csv"
                    _psd_x = run_dir / f"{stem}_psd_x.csv"
                    _psd_y = run_dir / f"{stem}_psd_y.csv"

                    # --- _results.xlsx (4 sheets) ---
                    export_ot_results_xlsx(
                        output_dir=run_dir,
                        base_name=stem,
                        trajectory_csv_path=traj_path,
                        msd_csv_path=_msd,
                        psd_x_csv_path=_psd_x,
                        psd_y_csv_path=_psd_y,
                    )

                    # --- _results.csv (all data in one file, sections separated by headers) ---
                    results_csv = run_dir / f"{stem}_results.csv"
                    with results_csv.open("w", encoding="utf-8", newline="") as out:
                        for section, src in [
                            ("Trajectory", traj_path),
                            ("MSD", _msd),
                            ("PSD_X", _psd_x),
                            ("PSD_Y", _psd_y),
                        ]:
                            if src.exists():
                                out.write(f"# [{section}]\n")
                                txt = src.read_text(encoding="utf-8")
                                # skip existing comment lines for trajectory
                                for line in txt.splitlines():
                                    if not line.startswith("#"):
                                        out.write(line + "\n")
                                out.write("\n")

                    # Clean up intermediate CSVs — data is in _results.xlsx + _results.csv
                    for _tmp in (traj_path, _msd, _psd_x, _psd_y):
                        if _tmp.exists():
                            _tmp.unlink()
                except Exception as e:
                    self._log(f"WARN: results export failed ({file_path.name}): {e!r}")

                dataset_set_status_fn(file_path, "done")
                self._log(f"OK: {file_path.name} -> {result.run_id}")

            except Exception as e:
                dataset_set_status_fn(file_path, "failed")
                self._log(f"ERROR: {file_path.name}: {e!r}")

            done += 1
            progress_fn(done, len(ok_paths), file_path.name, 100)
            QApplication.processEvents()

        self._log("Run Batch done ✅")
