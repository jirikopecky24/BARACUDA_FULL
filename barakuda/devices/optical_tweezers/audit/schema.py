from __future__ import annotations

from typing import Any


def build_ot_summary(
    camera_meta: dict[str, Any],
    drift_audit: dict[str, Any],
    qc_audit: dict[str, Any],
    strategy_name: str,
    strategy_params: dict[str, Any],
    result_dict: dict[str, Any],
    artifacts: dict[str, str],
    um_audit_note: str,
    header_cols: list[str]
) -> dict[str, Any]:
    """
    Build the final ot_summary.json structure per Bible v2.1.
    """
    
    return {
        "pipeline_version": "OT_v2.1",
        "camera_meta": camera_meta,
        "preprocess": drift_audit,
        "qc": qc_audit,
        "strategy": {
            "name": strategy_name,
            "parameters": strategy_params,
            "results": result_dict
        },
        "artifacts": artifacts,
        "trajectory": {
            "columns": header_cols,
            "um_columns": um_audit_note
        }
    }
