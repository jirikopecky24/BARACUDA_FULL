from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from barakuda.core.export_xlsx import export_ot_results_xlsx
from barakuda.core.ot_report import build_ot_item_summary, export_ot_item_pdf
from barakuda.core.run_protocol import load_protocol, merge_protocol, save_protocol
from barakuda.devices.optical_tweezers.drag.export import (
    export_drag_summary_csv,
    export_drag_summary_json,
)
from barakuda.devices.optical_tweezers.drag.pipeline import finalize_drag_run_from_trajectory
from barakuda.devices.optical_tweezers.drag.schema import DragAnalysisConfig


ITEMS_ROOT = Path(
    "C:/BARAKUDA_THESIS_2026/runs/2026-04-08_DAY05/analysis/2026-04-14_090043/items"
)
ACQ_ROOT = Path("C:/BARAKUDA_THESIS_2026/runs/2026-04-08_DAY05/acquisition/drag")
OVERRIDE_SOURCE = "visual_stage_stability_by_concentration"
OVERRIDE_RULES = {
    "Gly20": {"start": None, "end": 9.0},
    "Gly40": {"start": None, "end": 12.0},
    "Gly60": {"start": 8.0, "end": 23.0},
    "Gly80": {"start": 8.0, "end": 24.0},
}


def _build_config(run_payload: dict, old_summary: dict, rule: dict) -> DragAnalysisConfig:
    cfg_post = ((run_payload.get("config") or {}).get("postprocess") or {})
    cfg_cal = ((run_payload.get("config") or {}).get("calibration") or {})
    return DragAnalysisConfig(
        analysis_axis=str(cfg_post.get("drag_axis") or old_summary.get("analysis_axis") or "x"),
        um_per_px=float(cfg_cal.get("um_per_px") or 0.0) or None,
        stage_um_per_unit=float(cfg_cal.get("stage_um_per_unit") or 0.0) or None,
        bead_radius_um=float(cfg_post.get("bead_radius_um") or 1.0),
        bead_diameter_um=float(cfg_post.get("bead_diameter_um") or 2.0),
        kappa_n_per_m=float(old_summary.get("kappa_n_per_m") or 0.0) or None,
        eta_pa_s=float(old_summary.get("eta_pa_s") or cfg_post.get("viscosity_pa_s") or 0.001),
        drag_anchor_mode="auto",
        steady_window_override_start_rel_s=rule["start"],
        steady_window_override_end_rel_s=rule["end"],
        steady_window_override_source=OVERRIDE_SOURCE,
    )


def _sync_protocol_and_preview(
    *,
    analysis_dir: Path,
    base: str,
    pdf_path: Path,
    summary_json_path: Path,
    summary_csv_path: Path,
    xlsx_path: Path,
    diagnostic_png_path: str | None,
    alignment_json_path: str | None,
    windows_csv_path: Path,
    trace_annotated_csv_path: Path,
    trajectory_path: Path,
    source_input_path: str,
) -> dict:
    protocol_path = analysis_dir / "run_protocol.json"
    existing = load_protocol(protocol_path)
    updates = {
        "analysis": {
            "report_source_kind": "drag_summary",
            "report_source_path": str(summary_json_path),
            "summary_references": {
                "trajectory": str(trajectory_path),
                "summary_json": str(summary_json_path),
                "summary_csv": str(summary_csv_path),
                "windows_csv": str(windows_csv_path),
                "trace_annotated_csv": str(trace_annotated_csv_path),
                "diagnostic_png": diagnostic_png_path,
                "alignment_diagnostics_json": alignment_json_path,
                "current_drag_report_path": str(pdf_path),
            },
        },
        "provenance": {
            "report_source_kind": "drag_summary",
            "report_source_path": str(summary_json_path),
            "current_drag_output_root": str(analysis_dir),
            "current_drag_report_path": str(pdf_path),
            "current_drag_summary_json_path": str(summary_json_path),
            "current_drag_summary_csv_path": str(summary_csv_path),
            "current_drag_diagnostic_png_path": diagnostic_png_path,
            "current_drag_alignment_json_path": alignment_json_path,
        },
    }
    merged = merge_protocol(existing, updates, allow_manual_overwrite=True)
    saved_protocol = save_protocol(merged, protocol_path)
    audit_protocol = analysis_dir / "audit" / "run_protocol.json"
    audit_protocol.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(saved_protocol, audit_protocol)

    item_summary = build_ot_item_summary(
        run_dir=analysis_dir,
        base_name=base,
        item_id=base,
        source_input_path=source_input_path,
        status="success",
    )
    item_summary.setdefault("artifacts", {})["xlsx"] = str(xlsx_path)
    item_summary.setdefault("artifacts", {})["current_drag_report_path"] = str(pdf_path)
    (analysis_dir / "audit" / "preview_report.json").write_text(
        json.dumps(item_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return item_summary


def main() -> int:
    backup_tag = datetime.now().strftime("backup_pre_offline_override_%Y%m%d_%H%M%S")
    report_date = datetime.now().strftime("%Y-%m-%d")
    processed: list[dict] = []

    for item_dir in sorted(
        p for p in ITEMS_ROOT.iterdir() if p.is_dir() and "_drag_" in p.name
    ):
        base = item_dir.name
        conc = base.split("_")[0]
        if conc not in OVERRIDE_RULES:
            continue
        analysis_dir = item_dir / "analysis"
        audit_dir = analysis_dir / "audit"
        csv_dir = analysis_dir / "csv"
        results_dir = analysis_dir / "results"
        run_json_path = audit_dir / "run.json"
        summary_path = audit_dir / f"{base}_drag_summary.json"
        traj_path = csv_dir / f"{base}_trajectory.csv"
        if not run_json_path.exists() or not summary_path.exists() or not traj_path.exists():
            continue

        old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        run_payload = json.loads(run_json_path.read_text(encoding="utf-8"))
        cfg = _build_config(run_payload, old_summary, OVERRIDE_RULES[conc])

        backup_dir = analysis_dir / backup_tag
        backup_dir.mkdir(parents=True, exist_ok=True)
        for folder in (audit_dir, csv_dir, results_dir):
            if not folder.exists():
                continue
            for f in folder.glob(f"{base}*"):
                if f.is_file():
                    target = backup_dir / f.name
                    if not target.exists():
                        shutil.copy2(f, target)
        for f in (
            audit_dir / "run_protocol.json",
            analysis_dir / "run_protocol.json",
            audit_dir / "preview_report.json",
        ):
            if f.exists():
                target = backup_dir / f.name
                if not target.exists():
                    shutil.copy2(f, target)

        acq_run_dir = ACQ_ROOT / base
        if not acq_run_dir.exists():
            continue
        result, outputs = finalize_drag_run_from_trajectory(
            run_dir=acq_run_dir,
            trajectory_path=traj_path,
            drag_config=cfg,
            output_root=analysis_dir,
        )
        pdf_path = results_dir / f"{report_date}-OT-{base}-report.pdf"
        item_summary_for_pdf = build_ot_item_summary(
            run_dir=analysis_dir,
            base_name=base,
            item_id=base,
            source_input_path=str(acq_run_dir / f"{base}.raw"),
            status="success",
        )
        export_ot_item_pdf(pdf_path, item_summary_for_pdf)
        xlsx_path = export_ot_results_xlsx(
            output_dir=results_dir,
            base_name=base,
            trajectory_csv_path=csv_dir / f"{base}_trajectory.csv",
        )
        result = replace(result, current_drag_report_path=str(pdf_path))
        summary_json = export_drag_summary_json(result, audit_dir)
        summary_csv = export_drag_summary_csv(result, csv_dir)
        item_summary = _sync_protocol_and_preview(
            analysis_dir=analysis_dir,
            base=base,
            pdf_path=pdf_path,
            summary_json_path=summary_json,
            summary_csv_path=summary_csv,
            xlsx_path=xlsx_path,
            diagnostic_png_path=result.current_drag_diagnostic_png_path,
            alignment_json_path=result.current_drag_alignment_json_path,
            windows_csv_path=Path(outputs["windows_csv"]),
            trace_annotated_csv_path=Path(outputs["trace_annotated_csv"]),
            trajectory_path=Path(outputs["trajectory"]),
            source_input_path=str(acq_run_dir / f"{base}.raw"),
        )
        new_summary = json.loads(summary_json.read_text(encoding="utf-8"))
        processed.append(
            {
                "item": base,
                "override": OVERRIDE_RULES[conc],
                "old_verdict": old_summary.get("final_drag_verdict"),
                "new_verdict": new_summary.get("final_drag_verdict"),
                "old_reason": old_summary.get("final_drag_reason"),
                "new_reason": new_summary.get("final_drag_reason"),
                "steady_start": new_summary.get("steady_start_s"),
                "steady_end": new_summary.get("steady_end_s"),
                "steady_window_mode": new_summary.get("steady_window_mode"),
                "steady_window_override_source": new_summary.get(
                    "steady_window_override_source"
                ),
                "summary_json": str(summary_json),
                "summary_csv": str(summary_csv),
                "pdf": str(pdf_path),
                "xlsx": str(xlsx_path),
                "backup_dir": str(backup_dir),
            }
        )

    log_path = ITEMS_ROOT.parent / "offline_drag_reprocess_log.json"
    log_path.write_text(
        json.dumps({"processed": processed}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"processed_items={len(processed)}")
    print(f"log={log_path}")
    for item in processed:
        print(
            f"{item['item']}: {item['old_verdict']} -> {item['new_verdict']} "
            f"| mode={item['steady_window_mode']} | end={item['steady_end']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
