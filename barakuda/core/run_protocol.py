from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_FILENAME = "run_protocol.json"
PROTOCOL_VERSION = "1.0"

_TOP_LEVEL_SECTIONS = (
    "identity",
    "sample",
    "bead",
    "acquisition",
    "motion",
    "analysis",
    "provenance",
    "human_notes",
    "status",
)

# These sections are user-editable and are protected during automatic merges
# unless caller explicitly allows manual overwrite.
_MANUAL_SECTIONS = ("sample", "bead", "human_notes", "status")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_section_dict() -> dict[str, dict[str, Any]]:
    return {name: {} for name in _TOP_LEVEL_SECTIONS}


def _deep_merge_dict(base: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_dict(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def default_protocol() -> dict[str, Any]:
    now = _utc_now_iso()
    protocol: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        **_empty_section_dict(),
    }
    protocol["identity"] = {
        "created_at": now,
        "updated_at": now,
    }
    protocol["human_notes"] = {
        "experiment_goal": "",
        "pre_run_note": "",
        "during_run_note": "",
        "post_run_note": "",
        "interpretation_note": "",
    }
    protocol["status"] = {
        "trust_run": None,
        "repeat_needed": None,
        "keep_for_analysis": None,
        "rejected": None,
        "rejection_reason": "",
    }
    return protocol


def protocol_path_for_run(run_folder: str | Path) -> Path:
    return Path(run_folder).resolve() / PROTOCOL_FILENAME


def normalize_protocol(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = default_protocol()
    if payload:
        normalized = _deep_merge_dict(normalized, dict(payload))
    normalized.setdefault("protocol_version", PROTOCOL_VERSION)

    # Backward-safe fill for missing sections.
    for section_name in _TOP_LEVEL_SECTIONS:
        if not isinstance(normalized.get(section_name), dict):
            normalized[section_name] = {}

    identity = normalized["identity"]
    if not identity.get("created_at"):
        identity["created_at"] = _utc_now_iso()
    if not identity.get("updated_at"):
        identity["updated_at"] = identity["created_at"]
    return normalized


def create_protocol_from_context(context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    protocol = default_protocol()
    if context:
        protocol = merge_protocol(
            existing=protocol,
            updates=context,
            allow_manual_overwrite=True,
        )
    return protocol


def load_protocol(path_or_run_folder: str | Path) -> dict[str, Any]:
    path = Path(path_or_run_folder).resolve()
    if path.is_dir():
        path = path / PROTOCOL_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"Missing protocol file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid protocol payload at {path}: expected JSON object.")
    return normalize_protocol(payload)


def safe_merge_auto_fields(existing: Mapping[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    merged = normalize_protocol(existing)
    updates_dict = dict(updates)
    for manual_section in _MANUAL_SECTIONS:
        updates_dict.pop(manual_section, None)
    merged = _deep_merge_dict(merged, updates_dict)
    merged["identity"]["updated_at"] = _utc_now_iso()
    return merged


def merge_protocol(
    existing: Mapping[str, Any],
    updates: Mapping[str, Any],
    *,
    allow_manual_overwrite: bool = False,
) -> dict[str, Any]:
    existing_norm = normalize_protocol(existing)
    updates_dict = dict(updates)
    if allow_manual_overwrite:
        merged = _deep_merge_dict(existing_norm, updates_dict)
    else:
        merged = safe_merge_auto_fields(existing_norm, updates_dict)
    merged["identity"]["updated_at"] = _utc_now_iso()
    return merged


def save_protocol(protocol: Mapping[str, Any], path_or_run_folder: str | Path) -> Path:
    path = Path(path_or_run_folder).resolve()
    if path.is_dir():
        path = path / PROTOCOL_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_protocol(protocol)
    path.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
