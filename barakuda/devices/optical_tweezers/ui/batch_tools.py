from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import copy
from typing import Any, Callable


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
    """Brownian analysis folder (contains audit/ + csv/) and its pairing identity."""

    folder: Path
    family_key: str


def make_pair_key(path: Path | str) -> str:
    stem = Path(path).stem.lower()
    tokenized = [t for t in re.split(r"[^a-z0-9]+", stem) if t]
    if not tokenized:
        return stem
    return "|".join(tokenized)


# Tokens that distinguish Brownian vs Drag calibration runs but not bead/location identity.
_CALIBRATION_MODE_TOKENS = frozenset(
    {
        "brown",
        "brownian",
        "brow",
        "brn",
        "passive",
        "drag",
        "dragging",
        "constant",
        "velocity",
        "cv",
        "viscous",
    }
)


def _tokenize_name_stem(path: Path | str) -> list[str]:
    stem = Path(path).stem.lower()
    return [t for t in re.split(r"[^a-z0-9]+", stem) if t]


_OPTIONAL_TRAILING_VARIANT_TOKENS = frozenset(
    {
        "slow",
        "fast",
        "slower",
        "faster",
        "high",
        "low",
        "hi",
        "lo",
    }
)


def _strip_trailing_motion_variant_tokens(tokens: list[str]) -> list[str]:
    """Remove trailing motion/repeat tokens (e.g. r001, slow, fast) from a token list."""
    out = list(tokens)
    changed = True
    while out and changed:
        changed = False
        t = out[-1]
        if re.fullmatch(r"r\d+", t) or re.fullmatch(r"run\d+", t) or re.fullmatch(r"v\d+", t):
            out.pop()
            changed = True
            continue
        if t in _OPTIONAL_TRAILING_VARIANT_TOKENS:
            out.pop()
            changed = True
            continue
    return out


def make_family_pair_key(path: Path | str) -> str:
    """
    Shared pairing key for Brownian baselines and Drag inputs: same physical run / location
    (replicate, bead, sample id) while ignoring calibration mode (brown vs drag) and
    trailing motion-variant suffixes (e.g. r001 vs r002 on the same drag replicate).
    """
    tokens = _tokenize_name_stem(path)
    if not tokens:
        return make_pair_key(path)
    stripped_mode = [t for t in tokens if t not in _CALIBRATION_MODE_TOKENS]
    stripped_suffix = _strip_trailing_motion_variant_tokens(stripped_mode)
    core = stripped_suffix if stripped_suffix else stripped_mode
    if not core:
        core = tokens
    return "|".join(core)


def collect_brownian_baseline_candidates_from_roots(
    roots: list[Path],
    *,
    validate_folder: Callable[[Path], Any],
) -> list[PairingCandidate]:
    """
    Walk selected folders for analysis roots containing an audit/ directory and
    successful Brownian calibration import. Used by the OT baseline-root workflow.
    """
    seen: dict[str, PairingCandidate] = {}
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for audit_dir in root.rglob("audit"):
            folder = audit_dir.parent
            try:
                validate_folder(folder)
            except Exception:
                continue
            fk = make_family_pair_key(folder)
            seen[str(folder)] = PairingCandidate(folder=folder, family_key=fk)
    return sorted(seen.values(), key=lambda c: str(c.folder).lower())


def format_baseline_link_status(linked_folder: str, n_drag_items_sharing: int) -> str:
    """User-visible pairing label; multiple Drag rows may share one Brownian folder."""
    if n_drag_items_sharing <= 1:
        return "baseline linked"
    short = Path(linked_folder).name
    return f"baseline linked (shared {n_drag_items_sharing}×, {short})"


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
    """
    Map each Drag path to at most one Brownian analysis folder. Many Drag items may share
    the same folder (1 Brownian : N Drag). Ambiguous only when two *distinct* candidate
    folders share the same family key.
    """
    by_family: dict[str, set[Path]] = {}
    for c in candidates:
        by_family.setdefault(c.family_key, set()).add(c.folder)

    baseline_map: dict[str, str] = {}
    status_map: dict[str, str] = {}

    for p in drag_paths:
        fk = make_family_pair_key(p)
        folders = sorted(by_family.get(fk, set()), key=lambda x: str(x).lower())
        n = len(folders)
        if n == 0:
            status_map[str(p)] = "baseline missing"
        elif n > 1:
            status_map[str(p)] = "baseline ambiguous"
        else:
            baseline_map[str(p)] = str(folders[0])
            status_map[str(p)] = "baseline linked"
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
