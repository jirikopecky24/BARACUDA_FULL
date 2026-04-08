from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import copy
from typing import Callable


FILE_SPECIFIC_PROTECTED_FIELDS = {
    "brownian_baseline_folder",
    "drag_manual_offset_s",
}

MODE_STRATEGIES: dict[str, list[str]] = {
    "Brownian": ["PSD_Welch", "PSD_ProcFFT"],
    "Drag": ["Drag_ConstantVelocity"],
}


@dataclass(frozen=True)
class PairingCandidate:
    key: str
    folder: Path


def make_pair_key(path: Path | str) -> str:
    stem = Path(path).stem.lower()
    tokenized = [t for t in re.split(r"[^a-z0-9]+", stem) if t]
    if not tokenized:
        return stem
    return "|".join(tokenized)


def merge_ot_params_for_checked(
    source_params: dict,
    target_params: dict | None,
    protected_fields: set[str] | None = None,
) -> dict:
    protected = protected_fields or FILE_SPECIFIC_PROTECTED_FIELDS
    src_tracking = dict((source_params or {}).get("tracking") or {})
    src_post = dict((source_params or {}).get("postprocess") or {})
    src_scale = dict((source_params or {}).get("scale") or {})
    src_frame = (source_params or {}).get("frame_range")

    out = dict(target_params or {})
    out["tracking"] = src_tracking
    out["scale"] = src_scale
    if src_frame is not None:
        out["frame_range"] = src_frame

    dst_post = dict((out.get("postprocess") or {}))
    for key, value in src_post.items():
        if key in protected:
            continue
        dst_post[key] = value
    out["postprocess"] = dst_post
    return out


def resolve_ot_item_params_for_load(stored_params: dict | None, default_params: dict) -> dict:
    if stored_params is not None:
        return copy.deepcopy(stored_params)
    return copy.deepcopy(default_params)


def resolve_strategy_selection(mode: str, requested: str | None) -> str:
    allowed = MODE_STRATEGIES.get(str(mode), [])
    if requested and requested in allowed:
        return requested
    if allowed:
        return allowed[0]
    return str(requested or "")


def advanced_visibility(mode: str, advanced_on: bool) -> dict[str, bool]:
    return {
        "drift_window": bool(advanced_on),
        "brownian_baseline": bool(advanced_on) and str(mode) == "Drag",
    }


def parse_ot_progress_message(msg: str, fallback_pct: int) -> tuple[int, int, str, int]:
    done = 0
    total = 0
    filename = ""
    file_pct = int(fallback_pct)
    m = re.search(r"RUN:\s*\[(\d+)/(\d+)\]\s*(.*)", str(msg))
    if m:
        done = int(m.group(1))
        total = int(m.group(2))
        rest = str(m.group(3) or "").strip()
        m_pct = re.search(r"\((\d+)%\)\s*$", rest)
        if m_pct:
            file_pct = int(m_pct.group(1))
            filename = rest[: m_pct.start()].strip()
        else:
            filename = rest
    return done, total, filename, file_pct


def format_batch_progress(done: int, total: int) -> tuple[str, int]:
    total_i = max(1, int(total))
    done_i = max(0, min(int(done), total_i))
    pct = int(round((done_i / float(total_i)) * 100.0))
    return f"Batch progress: {done_i} / {total_i} completed ({pct}%)", pct


def format_current_file_progress(filename: str, pct: int) -> str:
    name = str(filename or "").strip() or "—"
    return f"Current file: {name} — {int(pct)}%"


def drag_action_visibility(mode: str) -> dict[str, bool]:
    is_drag = str(mode) == "Drag"
    return {
        "add_baseline_roots": is_drag,
        "auto_pair_baselines": is_drag,
    }


def run_stop_enabled_state(running: bool) -> tuple[bool, bool]:
    return (not bool(running), bool(running))


def resolve_frame_range_for_item(
    *,
    start: int,
    end: int,
    last_frame: int,
    is_new_item: bool,
) -> tuple[int, int]:
    if last_frame < 0:
        return max(0, int(start)), max(0, int(end))
    if is_new_item:
        return 0, int(last_frame)

    s = max(0, min(int(start), int(last_frame)))
    e = max(0, min(int(end), int(last_frame)))
    if e < s:
        e = s
    return s, e


def auto_pair_drag_items(
    drag_paths: list[Path],
    candidates: list[PairingCandidate],
) -> tuple[dict[str, str], dict[str, str]]:
    by_key: dict[str, list[Path]] = {}
    for c in candidates:
        by_key.setdefault(c.key, []).append(c.folder)

    baseline_map: dict[str, str] = {}
    status_map: dict[str, str] = {}

    for p in drag_paths:
        p_key = make_pair_key(p)
        hits = by_key.get(p_key, [])
        if len(hits) == 1:
            baseline_map[str(p)] = str(hits[0])
            status_map[str(p)] = "baseline linked"
        elif len(hits) > 1:
            status_map[str(p)] = "baseline ambiguous"
        else:
            status_map[str(p)] = "baseline missing"
    return baseline_map, status_map


def validate_drag_baseline_batch(
    checked_paths: list[Path],
    params_by_path: dict[str, dict],
    validate_folder: Callable[[Path], tuple[bool, str]],
) -> tuple[bool, dict[str, str]]:
    issues: dict[str, str] = {}
    for p in checked_paths:
        payload = params_by_path.get(str(p)) or {}
        pp = dict(payload.get("postprocess") or {})
        mode = str(pp.get("calibration_mode") or "Brownian")
        if mode != "Drag":
            continue
        baseline = str(pp.get("brownian_baseline_folder") or "").strip()
        if not baseline:
            issues[str(p)] = "baseline missing"
            continue
        ok, msg = validate_folder(Path(baseline))
        if not ok:
            issues[str(p)] = msg or "baseline invalid"
    return (len(issues) == 0), issues
