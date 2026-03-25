from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrownianCalibration:
    """Minimal Brownian calibration payload needed by DRAG."""

    base_name: str | None
    kappa_x_n_per_m: float | None
    kappa_y_n_per_m: float | None
    um_per_px: float | None
    # Selected calibration file path (for provenance).
    calibration_path: str | None = None


def _to_float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        if not (f == f):  # NaN check without importing math
            return None
        return f
    except Exception:  # noqa: BLE001
        return None


def load_brownian_calibration_from_folder(folder: Path | str) -> BrownianCalibration:
    """Load Brownian kappa and um_per_px from an OT analysis folder.

    Expected layout (analysis dir):
      analysis/
        audit/
          run.json
          <stem>_calibration.json

    The function is intentionally tolerant:
      - picks the first *_calibration.json in audit/
      - treats missing fields as None
    """
    analysis_dir = Path(folder).resolve()
    if not analysis_dir.is_dir():
        raise FileNotFoundError(f"Brownian analysis folder does not exist: {analysis_dir}")

    audit_dir = analysis_dir / "audit"
    if not audit_dir.is_dir():
        raise FileNotFoundError(f"Brownian audit subfolder not found: {audit_dir}")

    # Choose a representative calibration file
    cal_files = sorted(audit_dir.glob("*_calibration.json"))
    if not cal_files:
        raise FileNotFoundError(f"No *_calibration.json found in {audit_dir}")

    cal_path = cal_files[0]
    base_name = cal_path.stem.replace("_calibration", "")

    payload = json.loads(cal_path.read_text(encoding="utf-8"))
    kappa_payload = payload.get("kappa") or {}

    kappa_x = _to_float_or_none(kappa_payload.get("kappa_x_n_per_m"))
    kappa_y = _to_float_or_none(kappa_payload.get("kappa_y_n_per_m"))

    # Optional um_per_px from audit/run.json → config.calibration.um_per_px
    um_per_px: float | None = None
    run_json_path = audit_dir / "run.json"
    if run_json_path.is_file():
        try:
            run_payload = json.loads(run_json_path.read_text(encoding="utf-8"))
            calib_cfg = (run_payload.get("config") or {}).get("calibration") or {}
            um_per_px = _to_float_or_none(calib_cfg.get("um_per_px"))
        except Exception:  # noqa: BLE001
            # Best-effort only; missing um_per_px is allowed.
            um_per_px = None

    return BrownianCalibration(
        base_name=base_name,
        kappa_x_n_per_m=kappa_x,
        kappa_y_n_per_m=kappa_y,
        um_per_px=um_per_px,
        calibration_path=str(cal_path),
    )

