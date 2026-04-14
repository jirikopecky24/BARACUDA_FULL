from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "offline_drag_reprocess_day05.py"
    spec = importlib.util.spec_from_file_location("offline_drag_reprocess_day05", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_sync_protocol_and_preview_sets_report_path_and_references(tmp_path, monkeypatch) -> None:
    mod = _load_script_module()
    analysis_dir = tmp_path / "item" / "analysis"
    base = "Gly40_drag_rep01"
    protocol_payload = {
        "analysis": {
            "summary_references": {
                "current_drag_report_path": "C:/old/stale.pdf",
            }
        },
        "provenance": {
            "current_drag_report_path": None,
        },
    }
    _write_json(analysis_dir / "run_protocol.json", protocol_payload)
    _write_json(analysis_dir / "audit" / f"{base}_drag_summary.json", {"final_drag_verdict": "fail"})
    _write_json(analysis_dir / "audit" / "run.json", {"config": {"tracking": {}, "postprocess": {}, "calibration": {}}})

    def _fake_build_ot_item_summary(**_kwargs):
        return {"diagnostics": {"final_drag_verdict": "fail"}, "artifacts": {}}

    monkeypatch.setattr(mod, "build_ot_item_summary", _fake_build_ot_item_summary)

    pdf_path = analysis_dir / "results" / f"2026-04-14-OT-{base}-report.pdf"
    summary_json_path = analysis_dir / "audit" / f"{base}_drag_summary.json"
    summary_csv_path = analysis_dir / "csv" / f"{base}_drag_summary.csv"
    windows_csv_path = analysis_dir / "csv" / f"{base}_drag_windows.csv"
    trace_csv_path = analysis_dir / "csv" / f"{base}_drag_trace_annotated.csv"
    trajectory_path = analysis_dir / "csv" / f"{base}_trajectory.csv"
    for p in (pdf_path, summary_csv_path, windows_csv_path, trace_csv_path, trajectory_path):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")

    mod._sync_protocol_and_preview(
        analysis_dir=analysis_dir,
        base=base,
        pdf_path=pdf_path,
        summary_json_path=summary_json_path,
        summary_csv_path=summary_csv_path,
        xlsx_path=analysis_dir / "results" / f"{base}_results.xlsx",
        diagnostic_png_path=str(analysis_dir / "results" / f"{base}_drag_diagnostic.png"),
        alignment_json_path=str(analysis_dir / "audit" / f"{base}_alignment_diagnostics.json"),
        windows_csv_path=windows_csv_path,
        trace_annotated_csv_path=trace_csv_path,
        trajectory_path=trajectory_path,
        source_input_path=str(tmp_path / "raw" / f"{base}.raw"),
    )

    protocol_after = json.loads((analysis_dir / "run_protocol.json").read_text(encoding="utf-8"))
    assert (
        protocol_after["provenance"]["current_drag_report_path"]
        == str(pdf_path)
    )
    assert (
        protocol_after["analysis"]["summary_references"]["current_drag_report_path"]
        == str(pdf_path)
    )
    preview_after = json.loads((analysis_dir / "audit" / "preview_report.json").read_text(encoding="utf-8"))
    assert preview_after["artifacts"]["current_drag_report_path"] == str(pdf_path)
