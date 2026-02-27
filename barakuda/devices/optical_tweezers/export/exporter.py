from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

# Optional: For rendering plots if matplotlib is available
try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


class OTExporter:
    """
    Handles all file writing for the OT pipeline.
    Ensures mandatory files are always created and strategy artifacts are 
    namespaced with their export_prefix.
    """
    
    def __init__(self, output_dir: Path | str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def write_all(
        self,
        video_path: str,
        traj_pp: dict[str, Any],
        camera_meta: dict[str, Any],
        drift_audit: dict[str, Any],
        qc_audit: dict[str, Any],
        strategy_name: str,
        strategy_params: dict[str, Any],
        result_dict: dict[str, Any],
        artifacts_dict: dict[str, Any],
        export_prefix: str
    ) -> None:
        video_stem = Path(video_path).stem
        
        # 1. camera_meta.json
        meta_path = self.output_dir / f"{video_stem}_camera_meta.json"
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(camera_meta, f, indent=2)
            
        # 2. qc.json
        qc_path = self.output_dir / f"{video_stem}_qc.json"
        with qc_path.open("w", encoding="utf-8") as f:
            json.dump(qc_audit, f, indent=2)
            
        # 3. trajectory.csv
        # Columns: t_s, x_px, y_px, confidence, [x_um, y_um]
        traj_path = self.output_dir / f"{video_stem}_trajectory.csv"
        
        has_um = "um_per_px" in camera_meta
        um_audit_note = "available" if has_um else "nan_no_scale"
        
        with traj_path.open("w", newline="", encoding="utf-8") as f:
            # Audit headers
            f.write(f"# source_file={Path(video_path).name}\n")
            f.write(f"# um_columns={um_audit_note}\n")
            if has_um:
                f.write(f"# um_per_px={camera_meta['um_per_px']}\n")
                
            writer = csv.writer(f)
            header = ["t_s", "x_px", "y_px", "confidence", "x_um", "y_um", "x_corr_px", "y_corr_px", "lost", "lost_reason"]
            if has_um:
                header.extend(["x_corr_um", "y_corr_um"])
            writer.writerow(header)
            
            n_frames = len(traj_pp["t_s"])
            for i in range(n_frames):
                row = [
                    f"{float(traj_pp['t_s'][i]):.6f}",
                    f"{float(traj_pp['x_px'][i]):.6f}",
                    f"{float(traj_pp['y_px'][i]):.6f}",
                    f"{float(traj_pp['quality'][i]):.6f}",
                ]
                
                if has_um:
                    row.extend([
                        f"{float(traj_pp['x_um'][i]):.6f}",
                        f"{float(traj_pp['y_um'][i]):.6f}"
                    ])
                else:
                    row.extend(["nan", "nan"])
                    
                row.extend([
                    f"{float(traj_pp['x_corr_px'][i]):.6f}",
                    f"{float(traj_pp['y_corr_px'][i]):.6f}",
                    "1" if bool(traj_pp['lost_mask'][i]) else "0",
                    str(traj_pp['lost_reason'][i])
                ])
                
                if has_um:
                    row.extend([
                        f"{float(traj_pp['x_corr_um'][i]):.6f}",
                        f"{float(traj_pp['y_corr_um'][i]):.6f}"
                    ])
                    
                writer.writerow(row)
                
        # 4. Strategy Artifacts (Plots)
        saved_artifacts = {}
        for key, data in artifacts_dict.items():
            if key.startswith("psd_") and MATPLOTLIB_AVAILABLE:
                # Render PSD plot
                plot_name = f"{export_prefix}{key}.png"
                plot_path = self.output_dir / plot_name
                self._render_psd_plot(data, plot_path, title=key)
                saved_artifacts[plot_name] = str(plot_path.name)
            elif key.startswith("drag_response_") and MATPLOTLIB_AVAILABLE:
                # Render Drag plot
                plot_name = f"{export_prefix}{key}.png"
                plot_path = self.output_dir / plot_name
                self._render_drag_plot(data, plot_path, title=key)
                saved_artifacts[plot_name] = str(plot_path.name)
            elif isinstance(data, dict):
                # Fallback generic JSON dump for strategy dicts
                fname = f"{export_prefix}{key}.json"
                fpath = self.output_dir / fname
                with fpath.open("w", encoding="utf-8") as f:
                    # Filter out large numpy arrays before dumping
                    clean_data = {k: v for k, v in data.items() if not hasattr(v, "shape")}
                    json.dump(clean_data, f, indent=2)
                saved_artifacts[fname] = str(fpath.name)

        # 5. ot_summary.json (Audit)
        from barakuda.devices.optical_tweezers.audit.schema import build_ot_summary
        
        summary = build_ot_summary(
            camera_meta=camera_meta,
            drift_audit=drift_audit,
            qc_audit=qc_audit,
            strategy_name=strategy_name,
            strategy_params=strategy_params,
            result_dict=result_dict,
            artifacts=saved_artifacts,
            um_audit_note=um_audit_note,
            header_cols=header
        )
        
        summary_path = self.output_dir / f"{video_stem}_ot_summary.json"
        with summary_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
            
        # 6. run_manifest.json (Index)
        manifest_path = self.output_dir / "run_manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump({
                "video_file": Path(video_path).name,
                "summary_file": summary_path.name,
                "trajectory_file": traj_path.name,
                "camera_meta_file": meta_path.name,
                "qc_file": qc_path.name,
                "artifacts": saved_artifacts
            }, f, indent=2)

    def _render_psd_plot(self, data: dict, filepath: Path, title: str):
        plt.figure(figsize=(8, 6))
        plt.loglog(data["freq_hz"], data["psd"], alpha=0.5, label="Data")
        if "fit_curve" in data:
            plt.loglog(data["freq_hz"], data["fit_curve"], 'r-', linewidth=2, label="Lorentzian Fit")
        plt.title(title)
        plt.xlabel("Frequency (Hz)")
        plt.ylabel("PSD $[um^2/Hz]$")
        plt.grid(True, which="both", ls="--")
        plt.legend()
        plt.tight_layout()
        plt.savefig(filepath, dpi=150)
        plt.close()

    def _render_drag_plot(self, data: dict, filepath: Path, title: str):
        plt.figure(figsize=(8, 5))
        plt.plot(data["t_s"], data["pos_um"], alpha=0.6, label="Displacement")
        plt.axhline(data["steady_offset_um"], color='r', linestyle='--', label=f"Steady Offset: {data['steady_offset_um']:.3g} µm")
        plt.axvspan(data["steady_t_start"], data["steady_t_end"], color='r', alpha=0.1, label="Steady state window")
        plt.title(title)
        plt.xlabel("Time (s)")
        plt.ylabel("Displacement (µm)")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(filepath, dpi=150)
        plt.close()
