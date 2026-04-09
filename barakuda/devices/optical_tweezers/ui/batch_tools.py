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
    """
    Brownian analysis folder (contains audit/) and its pairing identity.

    ``folder``       — the analysis folder passed to ``load_brownian_calibration_from_folder``
                       (typically ``<run_folder>/analysis``).
    ``family_key``   — derived from the *run* folder name, not the analysis sub-folder,
                       so it matches drag-path family keys correctly.
    ``display_name`` — human-readable name shown in the Pairing tab tree
                       (defaults to run-folder name, e.g. ``Gly20_brown_rep01``).
    """

    folder: Path
    family_key: str
    display_name: str = ""


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


def _run_folder_for_analysis(analysis_folder: Path) -> Path:
    """
    Return the meaningful *run* folder for a Brownian analysis path.

    BARAKUDA convention: ``<run>/analysis/audit``.  When the analysis folder is
    named ``"analysis"`` we step up one level to get the run folder whose name
    carries the sample identity (e.g. ``Gly20_brown_rep01``).  For any other
    folder name the folder itself is the run folder.
    """
    if analysis_folder.name.lower() == "analysis":
        return analysis_folder.parent
    return analysis_folder


def collect_brownian_baseline_candidates_from_roots(
    roots: list[Path],
    *,
    validate_folder: Callable[[Path], Any],
) -> list[PairingCandidate]:
    """
    Walk selected folders for analysis roots containing an audit/ directory and
    successful Brownian calibration import. Used by the OT baseline-root workflow.

    ``PairingCandidate.folder``       — the analysis folder (passed to
                                        ``load_brownian_calibration_from_folder``).
    ``PairingCandidate.family_key``   — derived from the *run* folder (parent of
                                        the analysis folder), NOT from ``analysis/``,
                                        so it matches drag-path family keys.
    ``PairingCandidate.display_name`` — run folder name (e.g. ``Gly20_brown_rep01``).
    """
    seen: dict[str, PairingCandidate] = {}
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for audit_dir in root.rglob("audit"):
            analysis_folder = audit_dir.parent
            try:
                validate_folder(analysis_folder)
            except Exception:
                continue
            run_folder = _run_folder_for_analysis(analysis_folder)
            fk = make_family_pair_key(run_folder)
            seen[str(analysis_folder)] = PairingCandidate(
                folder=analysis_folder,
                family_key=fk,
                display_name=run_folder.name,
            )
    return sorted(seen.values(), key=lambda c: str(c.folder).lower())


def format_baseline_link_status(linked_folder: str, n_drag_items_sharing: int) -> str:
    """User-visible pairing label; multiple Drag rows may share one Brownian folder."""
    if n_drag_items_sharing <= 1:
        return "baseline linked"
    # Show the run-folder name (not "analysis") in the shared-baseline label.
    p = Path(linked_folder)
    short = p.parent.name if p.name.lower() == "analysis" else p.name
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


def resolve_drag_preflight_pairing_context(path: Path) -> tuple[Path, Path] | None:
    """Resolve ``(current_drag_input_path, run_dir)`` for Drag pairing / preflight checks.

    - If ``path`` is a ``.raw`` file: run directory is its parent (matches batch_controller).
    - If ``path`` is a directory: use Drag discovery (item root, acquisition folder, etc.)
      to locate the single resolved RAW path and use ``path`` as ``run_dir`` when discovery
      succeeds from that folder.
    """
    p = Path(path).resolve()
    if p.is_file():
        if p.suffix.lower() != ".raw":
            return None
        return (p, p.parent)
    if not p.is_dir():
        return None
    from barakuda.devices.optical_tweezers.drag.io import discover_drag_run_paths

    try:
        drp = discover_drag_run_paths(
            p,
            trajectory_path=None,
            require_trajectory=False,
            include_trajectory_discovery=False,
        )
        return (drp.raw_path, p)
    except Exception:
        return None


def is_ot_drag_baseline_pairing_target(path: Path, item_params: dict | None) -> bool:
    """True if this dataset path should participate in Drag↔Brown baseline pairing.

    Recognizes (1) stored ``postprocess.calibration_mode == "Drag"`` (legacy / explicit),
    or (2) a valid Drag RAW + sidecar layout per ``evaluate_drag_preflight`` (thesis-safe
    default workflow without requiring a pre-existing trajectory or stored mode).
    """
    payload = item_params or {}
    pp = dict(payload.get("postprocess") or {})
    if str(pp.get("calibration_mode") or "Brownian") == "Drag":
        return True
    ctx = resolve_drag_preflight_pairing_context(path)
    if ctx is None:
        return False
    drag_input, run_dir = ctx
    from barakuda.devices.optical_tweezers.drag.io import evaluate_drag_preflight

    pre = evaluate_drag_preflight(
        current_drag_input_path=drag_input,
        run_dir=run_dir,
        brownian_baseline_folder=None,
    )
    return str(pre.get("drag_preflight_status") or "").startswith("ready_drag_sidecars")


def collect_ot_drag_baseline_pairing_paths(
    checked_paths: list[Path],
    params_by_path: dict[str, dict],
) -> list[Path]:
    """Filter ``checked_paths`` to Drag baseline pairing targets (stable order)."""
    out: list[Path] = []
    for p in checked_paths:
        if is_ot_drag_baseline_pairing_target(p, params_by_path.get(str(p))):
            out.append(p)
    return out


def merge_drag_auto_pair_postprocess(pp: dict) -> dict:
    """Ensure postprocess is Drag-mode for items linked by auto-pair; fix Brownian strategy leftovers."""
    out = dict(pp)
    prior_mode = str(out.get("calibration_mode") or "Brownian")
    out["calibration_mode"] = "Drag"
    if prior_mode != "Drag":
        strat = str(out.get("strategy") or "").strip()
        brown = set(MODE_STRATEGIES.get("Brownian", []))
        if not strat or strat in brown:
            out["strategy"] = MODE_STRATEGIES["Drag"][0]
    return out


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


def inherit_calibration_mode_for_new_item(
    load_params: dict,
    current_mode: str | None,
) -> dict:
    """
    Preserve the current panel calibration_mode when loading params for a new
    (not-yet-stored) dataset item.

    Without this, new items always inherit ``calibration_mode: Brownian`` from
    ``_ot_default_params`` even when the user is working in a Drag workflow,
    because ``_ot_default_params`` is captured right after ``apply_ot_defaults()``
    which always resets to Brownian.  The consequence: importing videos while in
    Drag mode silently calls ``set_calibration_mode("Brownian")`` and hides the
    Pairing tab.

    Only the ``calibration_mode`` field is overridden; all other defaults (tracking
    params, scale, gate thresholds …) are preserved unchanged.
    """
    if not current_mode or str(current_mode) == "Brownian":
        return load_params
    result = dict(load_params)
    pp = dict(result.get("postprocess") or {})
    if pp.get("calibration_mode") != current_mode:
        pp["calibration_mode"] = str(current_mode)
        result["postprocess"] = pp
    return result


def build_pairing_tree_data(
    drag_paths: list[Path],
    candidates: list[PairingCandidate],
    explicit_pairs: dict[str, str | None],
    pairing_origins: dict[str, str],
) -> dict:
    """
    Build tree data for the Pairing tab view.

    ``explicit_pairs`` maps drag_path_str → baseline_folder_str (or None/empty = unpaired).
    ``pairing_origins`` maps drag_path_str → "auto" | "manual" | "unset".

    Returns a dict with keys:
      - baselines: list[{folder, folder_name, drags: list[{path, name, origin, status}]}]
      - unpaired:  list[{path, name, origin, status}]
      - available_baseline_folders: sorted list of str (from candidates + manually-assigned)
    """
    known_folders: set[str] = {str(c.folder) for c in candidates}
    # Map folder_str → human-readable display name (run folder name, not "analysis").
    folder_display: dict[str, str] = {
        str(c.folder): (c.display_name or _run_folder_for_analysis(c.folder).name)
        for c in candidates
    }

    paired_by_baseline: dict[str, list[dict]] = {}
    unpaired: list[dict] = []

    for dp in drag_paths:
        dp_str = str(dp)
        folder_str = (explicit_pairs.get(dp_str) or "").strip()
        origin = pairing_origins.get(dp_str, "unset")
        entry: dict = {
            "path": dp_str,
            "name": Path(dp_str).name,
            "origin": origin,
            "status": "linked" if folder_str else "missing",
        }
        if folder_str:
            paired_by_baseline.setdefault(folder_str, []).append(entry)
        else:
            unpaired.append(entry)

    all_baseline_folders: set[str] = known_folders | set(paired_by_baseline.keys())

    def _display_name_for(f: str) -> str:
        if f in folder_display:
            return folder_display[f]
        p = Path(f)
        return p.parent.name if p.name.lower() == "analysis" else p.name

    baselines = [
        {
            "folder": f,
            "folder_name": _display_name_for(f),
            "drags": paired_by_baseline.get(f, []),
        }
        for f in sorted(all_baseline_folders, key=str.lower)
    ]

    return {
        "baselines": baselines,
        "unpaired": unpaired,
        "available_baseline_folders": sorted(all_baseline_folders, key=str.lower),
    }


def build_baseline_list_view_data(candidates: list[PairingCandidate]) -> dict:
    """
    Build Pairing tab view data for the *pre-auto-pair* phase.

    After the user imports Brownian baseline folders but before running
    ``Auto-pair Brownian baselines``, the Pairing tab should show a plain list
    of available baseline units — no drag items, no pairing links.

    ``PairingTreeWidget`` reads the ``"phase": "baseline_list"`` key and
    renders the list in a simplified flat view, making the CTA to run
    auto-pair clearly visible as the next step.

    Returns a dict with the same top-level keys as ``build_pairing_tree_data``
    so that ``refresh_pairing_view`` can consume either without branching.
    """
    return {
        "phase": "baseline_list",
        "baselines": [
            {
                "folder": str(c.folder),
                "folder_name": c.display_name or _run_folder_for_analysis(c.folder).name,
                "drags": [],
            }
            for c in candidates
        ],
        "unpaired": [],
        "available_baseline_folders": sorted(
            {str(c.folder) for c in candidates}, key=str.lower
        ),
    }


def validate_drag_baseline_batch(
    checked_paths: list[Path],
    params_by_path: dict[str, dict],
    validate_folder: Callable[[Path], tuple[bool, str]],
) -> tuple[bool, dict[str, str]]:
    issues: dict[str, str] = {}
    for p in checked_paths:
        payload = params_by_path.get(str(p)) or {}
        if not is_ot_drag_baseline_pairing_target(p, payload):
            continue
        pp = dict(payload.get("postprocess") or {})
        baseline = str(pp.get("brownian_baseline_folder") or "").strip()
        if not baseline:
            issues[str(p)] = "baseline missing"
            continue
        ok, msg = validate_folder(Path(baseline))
        if not ok:
            issues[str(p)] = msg or "baseline invalid"
    return (len(issues) == 0), issues
