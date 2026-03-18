from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScaleInfo:
    um_per_px: float
    source: str  # "dataset_default" | "run_override" | "unset"
    path: Path | None = None
    stage_um_per_unit: float | None = None


def sidecar_scale_path(data_path: Path) -> Path:
    """
    Sidecar next to the data file:
      myvideo.avi.scale.json
      myimage.png.scale.json
    """
    data_path = Path(data_path)
    return data_path.with_suffix(data_path.suffix + ".scale.json")


def load_dataset_scale(data_path: Path) -> ScaleInfo | None:
    p = sidecar_scale_path(data_path)
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        um = float(obj["um_per_px"])
        stage_raw = obj.get("stage_um_per_unit")
        stage: float | None = float(stage_raw) if stage_raw is not None else None
        return ScaleInfo(um_per_px=um, source="dataset_default", path=p, stage_um_per_unit=stage)
    except Exception:
        return None


def save_dataset_scale(
    data_path: Path,
    um_per_px: float,
    stage_um_per_unit: float | None = None,
) -> ScaleInfo:
    p = sidecar_scale_path(data_path)
    payload: dict[str, Any] = {
        "um_per_px": float(um_per_px),
        "method": "manual",
        "source": "user",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if stage_um_per_unit is not None:
        payload["stage_um_per_unit"] = float(stage_um_per_unit)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return ScaleInfo(
        um_per_px=float(um_per_px),
        source="dataset_default",
        path=p,
        stage_um_per_unit=stage_um_per_unit,
    )
