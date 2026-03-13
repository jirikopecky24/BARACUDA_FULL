from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class AFMItemManifest:
    item_root: Path
    item_json_path: Path
    image_path: Optional[Path] = None
    analysis_dir: Optional[Path] = None
    exports_dir: Optional[Path] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AFMInputResolution:
    original_path: Path
    resolved_input_path: Path
    item_json_path: Optional[Path] = None
    item_root: Optional[Path] = None
    image_path: Optional[Path] = None


_IMAGE_EXTENSIONS = {".spm", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def load_item_manifest(item_json_path: Path) -> AFMItemManifest:
    item_json_path = Path(item_json_path).resolve()
    item_root = item_json_path.parent
    raw = json.loads(item_json_path.read_text(encoding="utf-8"))

    acquisition_image = raw.get("acquisition", {}).get("image")
    image_path = None
    if acquisition_image:
        candidate = item_root / acquisition_image
        if candidate.exists():
            image_path = candidate
    if image_path is None:
        acquisition_dir = item_root / "acquisition"
        if acquisition_dir.is_dir():
            for ext in _IMAGE_EXTENSIONS:
                hit = next(iter(sorted(acquisition_dir.glob(f"*{ext}"))), None)
                if hit is not None:
                    image_path = hit
                    break
    analysis_dir = None
    analysis_rel = raw.get("analysis", {}).get("dir")
    if analysis_rel:
        candidate = item_root / analysis_rel
        if candidate.exists():
            analysis_dir = candidate
    if analysis_dir is None:
        candidate = item_root / "analysis"
        if candidate.exists():
            analysis_dir = candidate

    exports_dir = item_root / "exports"
    if not exports_dir.is_dir():
        exports_dir = None

    return AFMItemManifest(
        item_root=item_root,
        item_json_path=item_json_path,
        image_path=image_path,
        analysis_dir=analysis_dir,
        exports_dir=exports_dir,
        raw=raw,
    )


def resolve_afm_input_path(path: Path | str) -> AFMInputResolution:
    original_path = Path(path)
    resolved_input_path = original_path.resolve()
    item_json_path = _resolve_item_json_from_input(resolved_input_path)
    if item_json_path is not None and item_json_path.is_file():
        manifest = load_item_manifest(item_json_path)
        image_path = manifest.image_path
        return AFMInputResolution(
            original_path=original_path,
            resolved_input_path=(image_path or item_json_path),
            item_json_path=item_json_path,
            item_root=manifest.item_root,
            image_path=image_path,
        )

    item_root = _detect_item_root_from_image_path(resolved_input_path)
    return AFMInputResolution(
        original_path=original_path,
        resolved_input_path=resolved_input_path,
        item_json_path=(item_root / "item.json") if item_root is not None else None,
        item_root=item_root,
        image_path=resolved_input_path if resolved_input_path.exists() else None,
    )


def build_item_manifest_payload(
    *,
    item_root: Path,
    item_id: str,
    batch_id: str,
    source_input_path: str,
    acquisition_image: Path | None = None,
    analysis_dir: Path | None = None,
    roi: list[int] | None = None,
    afm_um_per_px: float | None = None,
    afm_um_per_px_source: str | None = None,
    selected_channel: str | None = None,
    params: dict[str, Any] | None = None,
    status: str = "analyzed",
    existing_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item_root = Path(item_root).resolve()
    payload = dict(existing_payload or {})
    payload["schema_version"] = 1
    payload["module"] = "afm"
    payload["item_id"] = item_id
    payload["batch_id"] = batch_id
    payload["created_at"] = payload.get("created_at") or datetime.now().isoformat(timespec="seconds")
    payload["source_input_path"] = source_input_path
    payload["status"] = status

    acquisition = dict(payload.get("acquisition") or {})
    if acquisition_image is not None:
        acquisition["image"] = _safe_relpath(Path(acquisition_image), item_root)
    payload["acquisition"] = acquisition

    analysis = dict(payload.get("analysis") or {})
    if analysis_dir is not None:
        analysis["dir"] = _safe_relpath(Path(analysis_dir), item_root)
    payload["analysis"] = analysis

    afm = dict(payload.get("afm") or {})
    if roi is not None:
        afm["roi_rect"] = list(roi)
    if afm_um_per_px is not None:
        afm["um_per_px"] = float(afm_um_per_px)
    if afm_um_per_px_source:
        afm["um_per_px_source"] = afm_um_per_px_source
    if selected_channel:
        afm["selected_channel"] = selected_channel
    if params is not None:
        afm["params"] = params
    payload["afm"] = afm
    return payload


def _resolve_item_json_from_input(path: Path) -> Optional[Path]:
    if path.is_file() and path.name.lower() == "item.json":
        return path
    if path.is_dir() and (path / "item.json").is_file():
        return path / "item.json"
    if path.is_file():
        item_root = _detect_item_root_from_image_path(path)
        if item_root is not None and (item_root / "item.json").is_file():
            return item_root / "item.json"
    return None


def _detect_item_root_from_image_path(path: Path) -> Optional[Path]:
    try:
        resolved = path.resolve()
    except Exception:
        return None
    if resolved.parent.name == "acquisition":
        return resolved.parent.parent
    return None


def _safe_relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")
