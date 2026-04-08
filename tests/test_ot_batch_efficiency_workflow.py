from __future__ import annotations

from pathlib import Path
import sys
import types

from barakuda.devices.optical_tweezers.ui.batch_tools import (
    MODE_STRATEGIES,
    PairingCandidate,
    advanced_visibility,
    auto_pair_drag_items,
    build_baseline_list_view_data,
    build_pairing_tree_data,
    collect_brownian_baseline_candidates_from_roots,
    drag_action_visibility,
    format_baseline_link_status,
    format_batch_progress,
    format_current_file_progress,
    inherit_calibration_mode_for_new_item,
    make_family_pair_key,
    make_pair_key,
    merge_ot_params_for_checked,
    parse_ot_progress_message,
    resolve_frame_range_for_item,
    resolve_strategy_selection,
    resolve_ot_item_params_for_load,
    run_stop_enabled_state,
    validate_drag_baseline_batch,
)
from barakuda.devices.optical_tweezers.drag.calibration_import import (
    load_brownian_calibration_from_folder,
)


def test_apply_to_checked_copies_shared_params_but_keeps_protected_fields() -> None:
    source = {
        "tracking": {"roi_margin": 2.2},
        "scale": {"um_per_px": 0.05},
        "frame_range": (1, 100),
        "postprocess": {
            "calibration_mode": "Drag",
            "stage_speed_um_s": 12.0,
            "strategy": "PSD_Welch",
            "brownian_baseline_folder": "A",
            "drag_manual_offset_s": 1.23,
        },
    }
    target = {
        "postprocess": {
            "calibration_mode": "Drag",
            "brownian_baseline_folder": "B",
            "drag_manual_offset_s": 9.87,
        }
    }
    merged = merge_ot_params_for_checked(source, target)
    assert merged["tracking"]["roi_margin"] == 2.2
    assert merged["scale"]["um_per_px"] == 0.05
    assert merged["frame_range"] == (1, 100)
    assert merged["postprocess"]["stage_speed_um_s"] == 12.0
    assert merged["postprocess"]["strategy"] == "PSD_Welch"
    assert merged["postprocess"]["brownian_baseline_folder"] == "B"
    assert merged["postprocess"]["drag_manual_offset_s"] == 9.87


def test_resolve_item_params_prefers_stored_else_defaults() -> None:
    defaults = {"postprocess": {"strategy": "PSD_ProcFFT", "bead_diameter_um": 2.0}}
    stored = {"postprocess": {"strategy": "PSD_Welch", "bead_diameter_um": 3.0}}
    assert resolve_ot_item_params_for_load(stored, defaults)["postprocess"]["strategy"] == "PSD_Welch"
    loaded = resolve_ot_item_params_for_load(None, defaults)
    assert loaded["postprocess"]["bead_diameter_um"] == 2.0
    loaded["postprocess"]["bead_diameter_um"] = 9.0
    assert defaults["postprocess"]["bead_diameter_um"] == 2.0


def test_strategy_resolution_per_mode() -> None:
    assert resolve_strategy_selection("Brownian", "PSD_Welch") == "PSD_Welch"
    assert resolve_strategy_selection("Brownian", "Drag_ConstantVelocity") == "PSD_Welch"
    assert resolve_strategy_selection("Drag", "PSD_ProcFFT") == "Drag_ConstantVelocity"
    assert resolve_strategy_selection("Drag", "Drag_ConstantVelocity") == "Drag_ConstantVelocity"
    assert MODE_STRATEGIES["Brownian"] == ["PSD_Welch", "PSD_ProcFFT"]


def test_advanced_visibility_gating() -> None:
    vis_off_brown = advanced_visibility("Brownian", False)
    assert vis_off_brown["drift_window"] is False
    assert vis_off_brown["brownian_baseline"] is False
    vis_on_brown = advanced_visibility("Brownian", True)
    assert vis_on_brown["drift_window"] is True
    assert vis_on_brown["brownian_baseline"] is False
    vis_on_drag = advanced_visibility("Drag", True)
    assert vis_on_drag["drift_window"] is True
    assert vis_on_drag["brownian_baseline"] is True


def test_mode_specific_drag_action_visibility() -> None:
    brown = drag_action_visibility("Brownian")
    drag = drag_action_visibility("Drag")
    assert brown["add_baseline_roots"] is False
    assert brown["auto_pair_baselines"] is False
    assert drag["add_baseline_roots"] is True
    assert drag["auto_pair_baselines"] is True


def test_stop_button_state_model() -> None:
    run_enabled, stop_enabled = run_stop_enabled_state(False)
    assert run_enabled is True
    assert stop_enabled is False
    run_enabled, stop_enabled = run_stop_enabled_state(True)
    assert run_enabled is False
    assert stop_enabled is True


def test_progress_presentation_model_is_concise() -> None:
    batch_label, batch_pct = format_batch_progress(1, 3)
    current = format_current_file_progress("Water_brown_rep02.raw", 99)
    assert batch_label == "Batch progress: 1 / 3 completed (33%)"
    assert batch_pct == 33
    assert current == "Current file: Water_brown_rep02.raw — 99%"
    done, total, fname, fpct = parse_ot_progress_message("RUN: [1/3] Water_brown_rep02.raw (99%)", 99)
    assert (done, total, fname, fpct) == (1, 3, "Water_brown_rep02.raw", 99)


def test_report_action_removed_from_ot_ui_definition() -> None:
    panel_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/panel.py").read_text(encoding="utf-8")
    assert "btn_gate_report = QPushButton" not in panel_src


def test_ot_panel_drag_baseline_actions_use_folder_tree_and_auto_pair() -> None:
    panel_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/panel.py").read_text(encoding="utf-8")
    assert "Add baseline roots from folder tree" in panel_src
    assert "Auto-pair Brownian baselines" in panel_src


def test_frame_range_defaults_for_new_item() -> None:
    s, e = resolve_frame_range_for_item(start=0, end=0, last_frame=149, is_new_item=True)
    assert s == 0
    assert e == 149


def test_frame_range_persisted_valid_is_preserved() -> None:
    s, e = resolve_frame_range_for_item(start=5, end=70, last_frame=149, is_new_item=False)
    assert s == 5
    assert e == 70


def test_frame_range_clamps_only_when_invalid() -> None:
    s, e = resolve_frame_range_for_item(start=5, end=999, last_frame=149, is_new_item=False)
    assert s == 5
    assert e == 149


def test_frame_range_enforces_start_end_relation() -> None:
    s, e = resolve_frame_range_for_item(start=90, end=10, last_frame=149, is_new_item=False)
    assert s == 90
    assert e == 90


def test_end_frame_persisted_survives_item_switch() -> None:
    defaults = {"frame_range": (0, 149)}
    item_a = {"frame_range": (0, 77)}
    item_b = {"frame_range": (0, 120)}

    # switch to A
    loaded_a = resolve_ot_item_params_for_load(item_a, defaults)
    s_a, e_a = resolve_frame_range_for_item(
        start=int(loaded_a["frame_range"][0]),
        end=int(loaded_a["frame_range"][1]),
        last_frame=149,
        is_new_item=False,
    )
    assert (s_a, e_a) == (0, 77)

    # switch to B
    loaded_b = resolve_ot_item_params_for_load(item_b, defaults)
    s_b, e_b = resolve_frame_range_for_item(
        start=int(loaded_b["frame_range"][0]),
        end=int(loaded_b["frame_range"][1]),
        last_frame=149,
        is_new_item=False,
    )
    assert (s_b, e_b) == (0, 120)

    # switch back to A -> must still be A's persisted end
    loaded_a_back = resolve_ot_item_params_for_load(item_a, defaults)
    s_ab, e_ab = resolve_frame_range_for_item(
        start=int(loaded_a_back["frame_range"][0]),
        end=int(loaded_a_back["frame_range"][1]),
        last_frame=149,
        is_new_item=False,
    )
    assert (s_ab, e_ab) == (0, 77)


def test_valid_end_frame_survives_refresh() -> None:
    # Simulate metadata/preview refresh with same last frame; valid value must remain.
    s, e = resolve_frame_range_for_item(start=10, end=80, last_frame=149, is_new_item=False)
    assert (s, e) == (10, 80)


def test_invalid_stored_end_frame_gets_clamped() -> None:
    # Stored value above range must clamp to last valid frame.
    s, e = resolve_frame_range_for_item(start=3, end=300, last_frame=149, is_new_item=False)
    assert (s, e) == (3, 149)


def test_family_key_unifies_brownian_drag_and_motion_suffixes() -> None:
    assert make_family_pair_key("Gly40_brown_rep02") == make_family_pair_key("Gly40_drag_rep02.raw")
    assert make_family_pair_key("Gly40_drag_rep02") == make_family_pair_key("Gly40_drag_rep02_r001.raw")
    assert make_family_pair_key("Gly40_drag_rep02_slow.raw") == make_family_pair_key("Gly40_drag_rep02_fast.raw")


def test_auto_pair_many_drags_one_brownian_candidate() -> None:
    drags = [
        Path("Gly40_drag_rep02.raw"),
        Path("Gly40_drag_rep02_r002.raw"),
        Path("Gly40_drag_rep02_slow.raw"),
    ]
    fk = make_family_pair_key(drags[0])
    candidates = [PairingCandidate(Path("analysis/Gly40_brown_rep02"), fk)]
    baseline_map, status_map = auto_pair_drag_items(drags, candidates)
    for d in drags:
        assert status_map[str(d)] == "baseline linked"
        assert baseline_map[str(d)] == str(candidates[0].folder)


def test_auto_pair_ambiguous_when_two_distinct_folders_share_family_key() -> None:
    drags = [Path("Gly40_drag_rep02.raw")]
    fk = make_family_pair_key(drags[0])
    candidates = [
        PairingCandidate(Path("sessionA/Gly40_brown_rep02"), fk),
        PairingCandidate(Path("sessionB/Gly40_brown_rep02"), fk),
    ]
    baseline_map, status_map = auto_pair_drag_items(drags, candidates)
    assert status_map[str(drags[0])] == "baseline ambiguous"
    assert str(drags[0]) not in baseline_map


def test_format_baseline_link_status_shared_suffix() -> None:
    assert format_baseline_link_status("C:/x/B", 1) == "baseline linked"
    assert "shared 3×" in format_baseline_link_status("C:/x/B", 3)


def test_collect_baseline_candidates_from_roots_filters_by_validate(tmp_path: Path) -> None:
    good = tmp_path / "run1" / "analysis" / "Gly40_brown_rep02"
    (good / "audit").mkdir(parents=True)
    bad = tmp_path / "run_bad" / "analysis" / "x"
    (bad / "audit").mkdir(parents=True)

    def _validate(p: Path) -> None:
        if "run_bad" in str(p).replace("\\", "/"):
            raise ValueError("invalid")

    cands = collect_brownian_baseline_candidates_from_roots(
        [tmp_path / "run1", tmp_path / "run_bad"],
        validate_folder=_validate,
    )
    assert len(cands) == 1
    assert cands[0].folder == good


def test_auto_pair_unique_and_ambiguous_and_missing() -> None:
    drag = [
        Path("2026-04-01-sampleA-rep1-bead01.raw"),
        Path("2026-04-01-sampleB-rep1-bead01.raw"),
        Path("2026-04-01-sampleC-rep1-bead01.raw"),
    ]
    candidates = [
        PairingCandidate(Path("bA"), "2026|04|01|samplea|rep1|bead01"),
        PairingCandidate(Path("bB_1"), "2026|04|01|sampleb|rep1|bead01"),
        PairingCandidate(Path("bB_2"), "2026|04|01|sampleb|rep1|bead01"),
    ]
    baseline_map, status_map = auto_pair_drag_items(drag, candidates)
    assert baseline_map[str(drag[0])] == "bA"
    assert status_map[str(drag[0])] == "baseline linked"
    assert status_map[str(drag[1])] == "baseline ambiguous"
    assert status_map[str(drag[2])] == "baseline missing"


def test_drag_batch_guard_blocks_missing_and_invalid() -> None:
    checked = [Path("a.raw"), Path("b.raw"), Path("c.raw")]
    params = {
        "a.raw": {"postprocess": {"calibration_mode": "Drag", "brownian_baseline_folder": ""}},
        "b.raw": {"postprocess": {"calibration_mode": "Drag", "brownian_baseline_folder": "bad"}},
        "c.raw": {"postprocess": {"calibration_mode": "Brownian"}},
    }

    def _validate(folder: Path) -> tuple[bool, str]:
        if str(folder) == "bad":
            return False, "baseline invalid"
        return True, "baseline linked"

    ok, issues = validate_drag_baseline_batch(checked, params, _validate)
    assert ok is False
    assert issues["a.raw"] == "baseline missing"
    assert issues["b.raw"] == "baseline invalid"
    assert "c.raw" not in issues


def test_recursive_import_multi_folder_and_no_duplicates(tmp_path: Path) -> None:
    if "PyQt6" not in sys.modules:
        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.pyqtSignal = lambda *args, **kwargs: None
        qtcore.Qt = types.SimpleNamespace()
        qtcore.QDir = types.SimpleNamespace(Filter=types.SimpleNamespace(Dirs=1, NoDotAndDotDot=2))
        qtgui = types.ModuleType("PyQt6.QtGui")
        qtgui.QIcon = object
        qtwidgets = types.ModuleType("PyQt6.QtWidgets")
        for name in (
            "QWidget",
            "QVBoxLayout",
            "QHBoxLayout",
            "QPushButton",
            "QListWidget",
            "QListWidgetItem",
            "QFileDialog",
            "QLabel",
            "QStyle",
            "QSizePolicy",
            "QMessageBox",
            "QListView",
            "QTreeView",
            "QTreeWidget",
            "QTreeWidgetItem",
            "QAbstractItemView",
            "QDialog",
            "QDialogButtonBox",
            "QLineEdit",
            "QCheckBox",
        ):
            setattr(qtwidgets, name, object)
        pyqt6 = types.ModuleType("PyQt6")
        pyqt6.QtCore = qtcore
        pyqt6.QtGui = qtgui
        pyqt6.QtWidgets = qtwidgets
        sys.modules["PyQt6"] = pyqt6
        sys.modules["PyQt6.QtCore"] = qtcore
        sys.modules["PyQt6.QtGui"] = qtgui
        sys.modules["PyQt6.QtWidgets"] = qtwidgets

    from barakuda.shell.widgets.dataset_panel import (
        discover_importable_paths_from_roots,
        discover_subfolders,
        discover_from_parent_selected_subfolders,
        build_subfolder_preview,
        is_primary_dataset_input,
        detect_sidecar_status_for_input,
        summarize_master_check_state,
        remove_checked_state,
    )

    r1 = tmp_path / "root1"
    r2 = tmp_path / "root2"
    (r1 / "deep").mkdir(parents=True)
    (r2 / "deep").mkdir(parents=True)
    p1 = r1 / "deep" / "a.raw"
    p2 = r2 / "deep" / "b.mp4"
    p1.write_text("x", encoding="utf-8")
    p2.write_text("y", encoding="utf-8")
    out = discover_importable_paths_from_roots([r1, r2, r1])
    lowered = [str(p.resolve()).lower() for p in out]
    assert str(p1.resolve()).lower() in lowered
    assert str(p2.resolve()).lower() in lowered
    assert len(lowered) == len(set(lowered))
    ts_sidecar = r1 / "deep" / "a_timestamps.csv"
    ts_sidecar.write_text("frame,timestamp_s\n0,0.0\n", encoding="utf-8")
    assert is_primary_dataset_input(ts_sidecar) is False

    subs = discover_subfolders(tmp_path)
    assert str(r1.resolve()).lower() in [str(p.resolve()).lower() for p in subs]

    selected_out = discover_from_parent_selected_subfolders(
        tmp_path,
        [str(r1), str(r2), str(r1), str(tmp_path / "missing")],
    )
    selected_lowered = [str(p.resolve()).lower() for p in selected_out]
    assert str(p1.resolve()).lower() in selected_lowered
    assert str(p2.resolve()).lower() in selected_lowered
    assert len(selected_lowered) == len(set(selected_lowered))

    name, count, kind = build_subfolder_preview(r1)
    assert name == "root1"
    assert count >= 1
    assert kind == "unknown"
    status = detect_sidecar_status_for_input(p1)
    assert "timestamps ✓" in status
    assert summarize_master_check_state([]) == "unchecked"
    assert summarize_master_check_state([False, False]) == "unchecked"
    assert summarize_master_check_state([True, True]) == "checked"
    assert summarize_master_check_state([True, False]) == "partial"
    remaining, current = remove_checked_state(
        ["a", "b", "c"],
        {"a": True, "b": False, "c": True},
        "a",
    )
    assert remaining == ["b"]
    assert current == "b"


def test_remove_checked_state_no_checked_is_noop() -> None:
    from barakuda.shell.widgets.dataset_panel import remove_checked_state
    remaining, current = remove_checked_state(
        ["a", "b"],
        {"a": False, "b": False},
        "b",
    )
    assert remaining == ["a", "b"]
    assert current == "b"


def test_remove_checked_state_keeps_current_when_survives() -> None:
    from barakuda.shell.widgets.dataset_panel import remove_checked_state
    remaining, current = remove_checked_state(
        ["a", "b", "c"],
        {"a": True, "b": False, "c": False},
        "c",
    )
    assert remaining == ["b", "c"]
    assert current == "c"


def test_parent_selection_ignores_empty_subfolder(tmp_path: Path) -> None:
    if "PyQt6" not in sys.modules:
        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.pyqtSignal = lambda *args, **kwargs: None
        qtcore.Qt = types.SimpleNamespace()
        qtcore.QDir = types.SimpleNamespace(Filter=types.SimpleNamespace(Dirs=1, NoDotAndDotDot=2))
        qtgui = types.ModuleType("PyQt6.QtGui")
        qtgui.QIcon = object
        qtwidgets = types.ModuleType("PyQt6.QtWidgets")
        for name in (
            "QWidget", "QVBoxLayout", "QHBoxLayout", "QPushButton", "QListWidget", "QListWidgetItem",
            "QFileDialog", "QLabel", "QStyle", "QSizePolicy", "QMessageBox", "QListView", "QTreeView",
            "QTreeWidget", "QTreeWidgetItem",
            "QAbstractItemView", "QDialog", "QDialogButtonBox", "QLineEdit",
            "QCheckBox",
        ):
            setattr(qtwidgets, name, object)
        pyqt6 = types.ModuleType("PyQt6")
        pyqt6.QtCore = qtcore
        pyqt6.QtGui = qtgui
        pyqt6.QtWidgets = qtwidgets
        sys.modules["PyQt6"] = pyqt6
        sys.modules["PyQt6.QtCore"] = qtcore
        sys.modules["PyQt6.QtGui"] = qtgui
        sys.modules["PyQt6.QtWidgets"] = qtwidgets

    from barakuda.shell.widgets.dataset_panel import discover_from_parent_selected_subfolders

    parent = tmp_path / "wat"
    brown = parent / "Water_brown_rep01"
    empty = parent / "Water_drag_rep99"
    brown.mkdir(parents=True)
    empty.mkdir(parents=True)
    raw = brown / "capture.raw"
    raw.write_text("x", encoding="utf-8")
    (brown / "capture_timestamps.csv").write_text("frame,timestamp_s\n0,0.0\n", encoding="utf-8")

    out = discover_from_parent_selected_subfolders(parent, [str(brown), str(empty)])
    lowered = [str(p.resolve()).lower() for p in out]
    assert str(raw.resolve()).lower() in lowered
    assert len(lowered) == 1


def test_parent_import_attaches_sidecars_not_as_rows(tmp_path: Path) -> None:
    if "PyQt6" not in sys.modules:
        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.pyqtSignal = lambda *args, **kwargs: None
        qtcore.Qt = types.SimpleNamespace()
        qtcore.QDir = types.SimpleNamespace(Filter=types.SimpleNamespace(Dirs=1, NoDotAndDotDot=2))
        qtgui = types.ModuleType("PyQt6.QtGui")
        qtgui.QIcon = object
        qtwidgets = types.ModuleType("PyQt6.QtWidgets")
        for name in (
            "QWidget", "QVBoxLayout", "QHBoxLayout", "QPushButton", "QListWidget", "QListWidgetItem",
            "QFileDialog", "QLabel", "QStyle", "QSizePolicy", "QMessageBox", "QListView", "QTreeView",
            "QTreeWidget", "QTreeWidgetItem",
            "QAbstractItemView", "QDialog", "QDialogButtonBox", "QLineEdit",
            "QCheckBox",
        ):
            setattr(qtwidgets, name, object)
        pyqt6 = types.ModuleType("PyQt6")
        pyqt6.QtCore = qtcore
        pyqt6.QtGui = qtgui
        pyqt6.QtWidgets = qtwidgets
        sys.modules["PyQt6"] = pyqt6
        sys.modules["PyQt6.QtCore"] = qtcore
        sys.modules["PyQt6.QtGui"] = qtgui
        sys.modules["PyQt6.QtWidgets"] = qtwidgets

    from barakuda.shell.widgets.dataset_panel import (
        discover_from_parent_selected_subfolders,
        detect_sidecar_status_for_input,
    )

    parent = tmp_path / "wat"
    run = parent / "Water_drag_rep01"
    run.mkdir(parents=True)
    raw = run / "drag01.raw"
    raw.write_text("x", encoding="utf-8")
    (run / "drag01_timestamps.csv").write_text("frame,timestamp_s\n0,0.0\n", encoding="utf-8")
    (run / "drag01_meta.json").write_text("{}", encoding="utf-8")
    (run / "drag01_qc.json").write_text("{}", encoding="utf-8")
    (run / "drag01_stage.json").write_text("{}", encoding="utf-8")
    (run / "drag01_stage_trace.csv").write_text("t_s,event\n0,motion_start\n", encoding="utf-8")

    imported = discover_from_parent_selected_subfolders(parent, [str(run)])
    imported_lowered = [str(p.resolve()).lower() for p in imported]
    assert imported_lowered == [str(raw.resolve()).lower()]
    status = detect_sidecar_status_for_input(raw)
    assert "timestamps ✓" in status


def test_pair_key_is_route_normalized() -> None:
    key1 = make_pair_key(Path("C:/x/Sample_A-rep01 bead03.raw"))
    key2 = make_pair_key(Path("sample-a_rep01-bead03.mp4"))
    assert key1 == key2


# ── build_pairing_tree_data ──────────────────────────────────────────────────

def test_build_pairing_tree_data_basic() -> None:
    brown = Path("/data/day01/Gly20_brown_rep01/analysis")
    drag1 = Path("/data/day01/Gly20_drag_rep01_fast.raw")
    cands = [PairingCandidate(folder=brown, family_key="gly20|rep01")]
    pairs = {str(drag1): str(brown)}
    origins = {str(drag1): "auto"}

    data = build_pairing_tree_data([drag1], cands, pairs, origins)

    assert len(data["baselines"]) == 1
    bl = data["baselines"][0]
    assert bl["folder"] == str(brown)
    # folder_name must show the run folder (parent of "analysis"), not "analysis"
    assert bl["folder_name"] == brown.parent.name
    assert len(bl["drags"]) == 1
    assert bl["drags"][0]["path"] == str(drag1)
    assert bl["drags"][0]["origin"] == "auto"
    assert bl["drags"][0]["status"] == "linked"
    assert data["unpaired"] == []


def test_build_pairing_tree_data_unpaired_section() -> None:
    drag1 = Path("/data/Gly20_drag_rep01.raw")
    drag2 = Path("/data/Gly20_drag_rep02.raw")
    brown = Path("/data/Gly20_brown_rep01/analysis")
    cands = [PairingCandidate(folder=brown, family_key="gly20|rep01")]
    pairs: dict[str, str | None] = {str(drag1): str(brown), str(drag2): None}
    origins: dict[str, str] = {str(drag1): "auto", str(drag2): "unset"}

    data = build_pairing_tree_data([drag1, drag2], cands, pairs, origins)

    paired_names = [d["name"] for d in data["baselines"][0]["drags"]]
    assert drag1.name in paired_names
    assert len(data["unpaired"]) == 1
    assert data["unpaired"][0]["path"] == str(drag2)
    assert data["unpaired"][0]["status"] == "missing"


def test_build_pairing_tree_data_many_to_one() -> None:
    brown = Path("/data/Gly20_brown_rep01/analysis")
    drag_fast = Path("/data/Gly20_drag_rep01_fast.raw")
    drag_slow = Path("/data/Gly20_drag_rep01_slow.raw")
    cands = [PairingCandidate(folder=brown, family_key="gly20|rep01")]
    pairs = {str(drag_fast): str(brown), str(drag_slow): str(brown)}
    origins = {str(drag_fast): "auto", str(drag_slow): "auto"}

    data = build_pairing_tree_data([drag_fast, drag_slow], cands, pairs, origins)

    assert len(data["baselines"]) == 1
    drags = data["baselines"][0]["drags"]
    assert len(drags) == 2
    drag_names = {d["name"] for d in drags}
    assert drag_fast.name in drag_names
    assert drag_slow.name in drag_names
    assert data["unpaired"] == []


def test_build_pairing_tree_data_origin_auto_vs_manual() -> None:
    brown = Path("/data/Gly20_brown/analysis")
    drag_a = Path("/data/Gly20_drag_a.raw")
    drag_b = Path("/data/Gly20_drag_b.raw")
    cands = [PairingCandidate(folder=brown, family_key="gly20")]
    pairs = {str(drag_a): str(brown), str(drag_b): str(brown)}
    origins = {str(drag_a): "auto", str(drag_b): "manual"}

    data = build_pairing_tree_data([drag_a, drag_b], cands, pairs, origins)

    drags_by_name = {d["name"]: d for d in data["baselines"][0]["drags"]}
    assert drags_by_name[drag_a.name]["origin"] == "auto"
    assert drags_by_name[drag_b.name]["origin"] == "manual"


def test_build_pairing_tree_data_candidates_appear_without_drags() -> None:
    brown1 = Path("/data/Gly20_brown/analysis")
    brown2 = Path("/data/Gly40_brown/analysis")
    cands = [
        PairingCandidate(folder=brown1, family_key="gly20"),
        PairingCandidate(folder=brown2, family_key="gly40"),
    ]
    data = build_pairing_tree_data([], cands, {}, {})

    folder_names = {bl["folder_name"] for bl in data["baselines"]}
    # folder_name must be the run folder name (parent of "analysis"), not "analysis"
    assert brown1.parent.name in folder_names
    assert brown2.parent.name in folder_names
    assert all(len(bl["drags"]) == 0 for bl in data["baselines"])
    assert data["unpaired"] == []


def test_build_pairing_tree_data_available_baseline_folders() -> None:
    brown = Path("/data/Gly20_brown/analysis")
    drag1 = Path("/data/Gly20_drag.raw")
    cands = [PairingCandidate(folder=brown, family_key="gly20")]
    pairs = {str(drag1): str(brown)}

    data = build_pairing_tree_data([drag1], cands, pairs, {})

    assert str(brown) in data["available_baseline_folders"]


# ── Pairing tab panel source checks ─────────────────────────────────────────

def test_pairing_tab_visible_only_drag_described_in_panel_source() -> None:
    panel_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/panel.py").read_text(encoding="utf-8")
    assert "_pairing_tab_idx" in panel_src
    assert "setTabVisible" in panel_src
    assert 'str(mode) == "Drag"' in panel_src or "mode) == \"Drag\"" in panel_src


def test_pairing_tab_has_expected_ui_strings() -> None:
    panel_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/panel.py").read_text(encoding="utf-8")
    assert "Add Brownian folders from tree" in panel_src
    assert "Auto-pair Brownian baselines" in panel_src
    # Dynamic label: shows "Available Brownian baselines:" or "Pairing results:" based on phase.
    assert "Available Brownian baselines" in panel_src or "Pairing results" in panel_src
    assert "Manual reassign" in panel_src
    assert "Move to:" in panel_src
    assert "Assign" in panel_src


def test_pairing_tab_tree_widget_class_defined() -> None:
    panel_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/panel.py").read_text(encoding="utf-8")
    assert "class PairingTreeWidget" in panel_src
    assert "refresh_tree" in panel_src
    assert "drag_item_selected" in panel_src


def test_pairing_manual_assign_signal_defined_in_panel() -> None:
    panel_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/panel.py").read_text(encoding="utf-8")
    assert "pairing_manual_assign_requested" in panel_src
    assert "refresh_pairing_view" in panel_src


# ── manual pairing logic ─────────────────────────────────────────────────────

def test_manual_assign_overrides_auto_pair_result() -> None:
    """Manual reassign to a different Brownian baseline must override auto-pair."""
    brown_a = Path("/data/Gly20_brown_a_analysis")
    brown_b = Path("/data/Gly20_brown_b_analysis")
    drag = Path("/data/Gly20_drag.raw")

    cands = [
        PairingCandidate(folder=brown_a, family_key="gly20|a"),
        PairingCandidate(folder=brown_b, family_key="gly20|b"),
    ]
    # auto-pair would link drag → brown_a
    pairs_auto = {str(drag): str(brown_a)}
    origins_auto = {str(drag): "auto"}
    tree_auto = build_pairing_tree_data([drag], cands, pairs_auto, origins_auto)
    assert tree_auto["baselines"][0]["drags"][0]["origin"] == "auto"

    # manual override: link drag → brown_b
    pairs_manual = {str(drag): str(brown_b)}
    origins_manual = {str(drag): "manual"}
    tree_manual = build_pairing_tree_data([drag], cands, pairs_manual, origins_manual)

    # bl_by_name keyed on folder_name (last path component)
    bl_by_name = {bl["folder_name"]: bl for bl in tree_manual["baselines"]}
    assert len(bl_by_name[brown_b.name]["drags"]) == 1
    assert bl_by_name[brown_b.name]["drags"][0]["origin"] == "manual"
    assert len(bl_by_name[brown_a.name]["drags"]) == 0


def test_manual_unpair_moves_drag_to_unpaired() -> None:
    brown = Path("/data/Gly20_brown_analysis")
    drag = Path("/data/Gly20_drag.raw")
    cands = [PairingCandidate(folder=brown, family_key="gly20")]
    pairs: dict[str, str | None] = {str(drag): None}
    origins = {str(drag): "manual"}

    data = build_pairing_tree_data([drag], cands, pairs, origins)

    assert data["baselines"][0]["drags"] == []
    assert len(data["unpaired"]) == 1
    assert data["unpaired"][0]["origin"] == "manual"


# ── run preflight still uses explicit pairing map (stored params) ────────────

def test_preflight_blocks_drag_without_baseline(tmp_path: Path) -> None:
    drag_raw = tmp_path / "Gly20_drag.raw"
    drag_raw.write_text("x")
    params = {
        str(drag_raw): {
            "postprocess": {"calibration_mode": "Drag", "brownian_baseline_folder": ""}
        }
    }

    def _validate(_folder: Path) -> tuple[bool, str]:
        return True, "baseline linked"

    ok, issues = validate_drag_baseline_batch([drag_raw], params, _validate)
    assert not ok
    assert "baseline missing" in issues[str(drag_raw)]


def test_preflight_passes_drag_with_valid_baseline(tmp_path: Path) -> None:
    drag_raw = tmp_path / "Gly20_drag.raw"
    drag_raw.write_text("x")
    baseline = tmp_path / "brown_analysis"
    baseline.mkdir()
    params = {
        str(drag_raw): {
            "postprocess": {
                "calibration_mode": "Drag",
                "brownian_baseline_folder": str(baseline),
            }
        }
    }

    def _validate(_folder: Path) -> tuple[bool, str]:
        return True, "baseline linked"

    ok, issues = validate_drag_baseline_batch([drag_raw], params, _validate)
    assert ok
    assert issues == {}


# ── inherit_calibration_mode_for_new_item (Pairing tab visibility fix) ───────

def test_new_drag_item_inherits_drag_mode_not_brownian_default() -> None:
    """New item loaded with Brownian defaults must have mode overridden to Drag."""
    brownian_defaults = {
        "postprocess": {"calibration_mode": "Brownian", "strategy": "PSD_Welch"},
        "tracking": {"roi_margin": 1.8},
    }
    result = inherit_calibration_mode_for_new_item(brownian_defaults, "Drag")
    assert result["postprocess"]["calibration_mode"] == "Drag"
    # Other fields untouched
    assert result["postprocess"]["strategy"] == "PSD_Welch"
    assert result["tracking"]["roi_margin"] == 1.8


def test_new_item_in_brownian_workflow_stays_brownian() -> None:
    """When panel is in Brownian mode, new item must stay Brownian (no override)."""
    brownian_defaults = {
        "postprocess": {"calibration_mode": "Brownian", "strategy": "PSD_Welch"},
    }
    result = inherit_calibration_mode_for_new_item(brownian_defaults, "Brownian")
    assert result["postprocess"]["calibration_mode"] == "Brownian"
    # Should return the same object (no unnecessary copy)
    assert result is brownian_defaults


def test_new_item_with_none_current_mode_stays_brownian() -> None:
    """None current_mode means panel state unknown — keep Brownian default."""
    brownian_defaults = {"postprocess": {"calibration_mode": "Brownian"}}
    result = inherit_calibration_mode_for_new_item(brownian_defaults, None)
    assert result["postprocess"]["calibration_mode"] == "Brownian"


def test_stored_item_params_not_affected_by_inherit() -> None:
    """
    The fix only applies to new items (pms is None path in _on_item_selected).
    Test that the helper does not change Drag params when the item has stored
    params that explicitly say Drag (already correct — no-op expected).
    """
    stored_drag = {
        "postprocess": {"calibration_mode": "Drag", "stage_speed_um_s": 5.0},
    }
    result = inherit_calibration_mode_for_new_item(stored_drag, "Drag")
    assert result["postprocess"]["calibration_mode"] == "Drag"
    assert result["postprocess"]["stage_speed_um_s"] == 5.0


def test_inherit_does_not_mutate_original_dict() -> None:
    """Original load_params dict must not be mutated."""
    original = {"postprocess": {"calibration_mode": "Brownian"}}
    result = inherit_calibration_mode_for_new_item(original, "Drag")
    assert original["postprocess"]["calibration_mode"] == "Brownian"
    assert result["postprocess"]["calibration_mode"] == "Drag"
    assert result is not original


def test_pairing_tab_visibility_source_uses_setTabVisible() -> None:
    """Confirm panel uses Qt setTabVisible for Pairing tab, not workarounds."""
    panel_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/panel.py").read_text(encoding="utf-8")
    assert "setTabVisible" in panel_src
    assert "_pairing_tab_idx" in panel_src


def test_inherit_helper_documented_in_batch_tools() -> None:
    """Confirm the fix is present as a named, importable function."""
    bt_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/batch_tools.py").read_text(encoding="utf-8")
    assert "inherit_calibration_mode_for_new_item" in bt_src
    assert "_ot_default_params" in bt_src or "new_item" in bt_src


def test_main_window_uses_inherit_for_new_item() -> None:
    """Confirm main_window applies inherit_calibration_mode_for_new_item when pms is None."""
    mw_src = Path("C:/Work/BARAKUDA_FULL/barakuda/shell/main_window.py").read_text(encoding="utf-8")
    assert "inherit_calibration_mode_for_new_item" in mw_src
    assert "pms is None" in mw_src


def test_preflight_passes_brownian_items_unconditionally(tmp_path: Path) -> None:
    brown_raw = tmp_path / "Gly20_brown.raw"
    brown_raw.write_text("x")
    params = {
        str(brown_raw): {
            "postprocess": {"calibration_mode": "Brownian", "brownian_baseline_folder": ""}
        }
    }

    def _validate(_folder: Path) -> tuple[bool, str]:
        return False, "baseline invalid"

    ok, issues = validate_drag_baseline_batch([brown_raw], params, _validate)
    assert ok
    assert issues == {}


# ── Run-level selection model (block 3 new tests) ────────────────────────────

def test_collect_candidates_standard_barakuda_structure(tmp_path: Path) -> None:
    """
    Standard BARAKUDA layout: <run_folder>/analysis/audit/<calibration>.json
    collect_brownian_baseline_candidates_from_roots must find the run folder
    when given the run folder as a root.
    """
    run_folder = tmp_path / "Gly20_brown_rep01"
    analysis = run_folder / "analysis"
    audit = analysis / "audit"
    audit.mkdir(parents=True)
    (audit / "Gly20_brown_rep01_calibration.json").write_text(
        '{"kappa": {"kappa_x_n_per_m": 0.001, "kappa_y_n_per_m": 0.001}}',
        encoding="utf-8",
    )

    cands = collect_brownian_baseline_candidates_from_roots(
        [run_folder],
        validate_folder=load_brownian_calibration_from_folder,
    )

    assert len(cands) == 1
    # folder stored = analysis path (for loading)
    assert cands[0].folder == analysis
    # family_key uses the RUN folder name, not "analysis"
    assert "analysis" not in cands[0].family_key
    assert "gly20" in cands[0].family_key.lower() or "brown" in cands[0].family_key.lower()
    # display_name is the run folder name, not "analysis"
    assert cands[0].display_name == "Gly20_brown_rep01"


def test_collect_candidates_family_key_from_run_folder_not_analysis(tmp_path: Path) -> None:
    """
    family_key must be derived from the run folder (Gly20_brown_rep01),
    NOT from 'analysis' — otherwise auto-pair never matches drag paths.
    """
    run_folder = tmp_path / "Gly20_brown_rep01"
    audit = run_folder / "analysis" / "audit"
    audit.mkdir(parents=True)
    (audit / "cal_calibration.json").write_text(
        '{"kappa": {"kappa_x_n_per_m": 0.002, "kappa_y_n_per_m": 0.002}}',
        encoding="utf-8",
    )

    cands = collect_brownian_baseline_candidates_from_roots(
        [run_folder],
        validate_folder=load_brownian_calibration_from_folder,
    )

    assert len(cands) == 1
    # Generic "analysis" must NOT be the family key (it would block every match)
    assert cands[0].family_key != "analysis"
    # The key must derive from Gly20_brown_rep01 tokens
    fk = cands[0].family_key
    assert any(token in fk for token in ("gly20", "brown", "rep01", "rep")), (
        f"Expected run-folder tokens in family_key, got: {fk!r}"
    )


def test_collect_candidates_display_name_is_run_folder(tmp_path: Path) -> None:
    """display_name must be the run folder name shown in the Pairing tab."""
    for name in ("Water_brown_rep01", "Gly40_brown_rep02"):
        run = tmp_path / name
        audit = run / "analysis" / "audit"
        audit.mkdir(parents=True)
        (audit / f"{name}_calibration.json").write_text(
            '{"kappa": {"kappa_x_n_per_m": 0.001, "kappa_y_n_per_m": 0.001}}',
            encoding="utf-8",
        )

    cands = collect_brownian_baseline_candidates_from_roots(
        [tmp_path / "Water_brown_rep01", tmp_path / "Gly40_brown_rep02"],
        validate_folder=load_brownian_calibration_from_folder,
    )

    display_names = {c.display_name for c in cands}
    assert "Water_brown_rep01" in display_names
    assert "Gly40_brown_rep02" in display_names
    assert "analysis" not in display_names


def test_build_pairing_tree_uses_display_name_not_analysis() -> None:
    """folder_name in Pairing tree must show the run folder, never 'analysis'."""
    brown = Path("/data/day01/Gly20_brown_rep01/analysis")
    drag1 = Path("/data/day01/Gly20_drag_fast.raw")
    # Candidate with explicit display_name
    cands = [PairingCandidate(folder=brown, family_key="gly20|brown|rep01", display_name="Gly20_brown_rep01")]
    pairs = {str(drag1): str(brown)}

    data = build_pairing_tree_data([drag1], cands, pairs, {})

    assert data["baselines"][0]["folder_name"] == "Gly20_brown_rep01"
    assert data["baselines"][0]["folder_name"] != "analysis"


def test_build_pairing_tree_fallback_when_no_display_name() -> None:
    """When display_name is empty, folder_name falls back to parent.name if folder is 'analysis'."""
    brown = Path("/data/SampleA/Gly20_brown_rep01/analysis")
    cands = [PairingCandidate(folder=brown, family_key="gly20|rep01", display_name="")]
    data = build_pairing_tree_data([], cands, {}, {})

    # Fallback: parent.name of "analysis" = "Gly20_brown_rep01"
    assert data["baselines"][0]["folder_name"] == "Gly20_brown_rep01"


def test_auto_pair_succeeds_with_standard_barakuda_structure(tmp_path: Path) -> None:
    """
    Full round-trip: standard layout, collect candidates from run folder,
    then auto-pair against a drag path with matching family key.
    """
    run_folder = tmp_path / "Gly20_brown_rep01"
    audit = run_folder / "analysis" / "audit"
    audit.mkdir(parents=True)
    (audit / "Gly20_brown_rep01_calibration.json").write_text(
        '{"kappa": {"kappa_x_n_per_m": 0.001, "kappa_y_n_per_m": 0.001}}',
        encoding="utf-8",
    )

    cands = collect_brownian_baseline_candidates_from_roots(
        [run_folder],
        validate_folder=load_brownian_calibration_from_folder,
    )
    assert len(cands) == 1

    # A drag path whose family key overlaps with the run folder
    drag_path = tmp_path / "Gly20_drag_rep01_fast.raw"
    baseline_map, status_map = auto_pair_drag_items([drag_path], cands)

    # Because both have "gly20" in their tokens the pair should succeed
    assert str(drag_path) in baseline_map, (
        f"Expected pairing but got status: {status_map.get(str(drag_path))!r}\n"
        f"candidate family_key={cands[0].family_key!r}"
    )


def test_invalid_run_folder_ignored(tmp_path: Path) -> None:
    """A run folder without a valid audit/*_calibration.json is silently skipped."""
    bad_run = tmp_path / "EmptyRun"
    (bad_run / "analysis" / "audit").mkdir(parents=True)
    # no calibration JSON → load_brownian_calibration_from_folder raises

    cands = collect_brownian_baseline_candidates_from_roots(
        [bad_run],
        validate_folder=load_brownian_calibration_from_folder,
    )
    assert cands == []


def test_dialog_skip_folder_names_present_in_source() -> None:
    """dataset_panel.py must expose skip_folder_names on HierarchicalFolderImportDialog."""
    src = Path("C:/Work/BARAKUDA_FULL/barakuda/shell/widgets/dataset_panel.py").read_text(encoding="utf-8")
    assert "skip_folder_names" in src
    assert "_skip_names" in src


def test_main_window_passes_baseline_skip_to_dialog() -> None:
    """_on_ot_add_baseline_roots must pass skip_folder_names to the dialog."""
    mw_src = Path("C:/Work/BARAKUDA_FULL/barakuda/shell/main_window.py").read_text(encoding="utf-8")
    assert "skip_folder_names" in mw_src
    assert "analysis" in mw_src   # "analysis" must be in the skip set
    assert "raw" in mw_src        # "raw" must be in the skip set


def test_format_baseline_link_status_uses_run_folder_name() -> None:
    """format_baseline_link_status must show run folder name, not 'analysis'."""
    # When the path ends in 'analysis', parent name should be used
    status = format_baseline_link_status("/data/Gly20_brown_rep01/analysis", 3)
    assert "analysis" not in status
    assert "Gly20_brown_rep01" in status
    assert "shared 3×" in status


# ── Scenario tests: Pairing workflow phase model (zadání requirements I–G) ──


def test_scenario1_import_baseline_folders_returns_candidate_list() -> None:
    """
    Scenario 1: importing Brownian baseline folders loads available candidates.
    build_baseline_list_view_data() must return a list of all candidates with no drag children.
    """
    candidates = [
        PairingCandidate(Path("/data/Gly20_brown_rep01/analysis"), "gly20|rep01", "Gly20_brown_rep01"),
        PairingCandidate(Path("/data/Gly20_brown_rep02/analysis"), "gly20|rep02", "Gly20_brown_rep02"),
        PairingCandidate(Path("/data/Water_brown_rep01/analysis"), "water|rep01", "Water_brown_rep01"),
    ]
    view = build_baseline_list_view_data(candidates)

    assert view["phase"] == "baseline_list"
    assert len(view["baselines"]) == 3
    names = [bl["folder_name"] for bl in view["baselines"]]
    assert "Gly20_brown_rep01" in names
    assert "Gly20_brown_rep02" in names
    assert "Water_brown_rep01" in names


def test_scenario2_import_baselines_does_not_create_pairing_links() -> None:
    """
    Scenario 2: importing baselines alone must NOT create any pairing between drag items
    and Brownian baselines.  build_baseline_list_view_data() must return empty drag lists
    even when drag paths exist in the dataset.
    """
    candidates = [
        PairingCandidate(Path("/data/Gly20_brown_rep01/analysis"), "gly20|rep01", "Gly20_brown_rep01"),
    ]
    view = build_baseline_list_view_data(candidates)

    # No drag items appear — the tree is purely a list of available baselines.
    assert view["unpaired"] == []
    for bl in view["baselines"]:
        assert bl["drags"] == [], f"Expected no drag children after import, got {bl['drags']}"


def test_scenario3_auto_pair_creates_links_between_drag_and_baselines() -> None:
    """
    Scenario 3: auto-pair (run after import) links drag items to their Brownian baselines.
    The result tree must show paired drag items as children of the correct baseline node.
    """
    fk = make_family_pair_key("Gly20_brown_rep01")
    candidates = [
        PairingCandidate(Path("/data/Gly20_brown_rep01/analysis"), fk, "Gly20_brown_rep01"),
    ]
    drag_paths = [
        Path("/runs/Gly20_drag_rep01_slow.raw"),
        Path("/runs/Gly20_drag_rep01_fast.raw"),
    ]
    baseline_map, status_map = auto_pair_drag_items(drag_paths, candidates)

    # Both drag paths must be linked — not missing or ambiguous.
    for dp in drag_paths:
        assert status_map[str(dp)] == "baseline linked", (
            f"Expected linked, got {status_map[str(dp)]!r}"
        )
        assert str(dp) in baseline_map

    # Build the pairing_result tree and verify structure.
    explicit_pairs = {str(dp): baseline_map[str(dp)] for dp in drag_paths}
    tree_data = build_pairing_tree_data(
        drag_paths=drag_paths,
        candidates=candidates,
        explicit_pairs=explicit_pairs,
        pairing_origins={str(dp): "auto" for dp in drag_paths},
    )
    assert tree_data.get("phase", "pairing_result") != "baseline_list"
    assert len(tree_data["baselines"]) == 1
    baseline_node = tree_data["baselines"][0]
    assert baseline_node["folder_name"] == "Gly20_brown_rep01"
    assert len(baseline_node["drags"]) == 2
    assert tree_data["unpaired"] == []


def test_scenario4_manual_assign_overrides_auto_pair() -> None:
    """
    Scenario 4: manual assign is an override applied after (or instead of) auto-pair.
    It must produce origin="manual" and supersede any previous auto-pairing.
    """
    fk = make_family_pair_key("Gly20_brown_rep01")
    candidate_a = PairingCandidate(Path("/data/Gly20_brown_rep01/analysis"), fk, "Gly20_brown_rep01")
    candidate_b = PairingCandidate(Path("/data/Gly20_brown_rep02/analysis"), "gly20|rep02", "Gly20_brown_rep02")

    drag = Path("/runs/Gly20_drag_rep01.raw")

    # Simulate auto-pair result.
    explicit_pairs = {str(drag): str(candidate_a.folder)}
    origins_auto = {str(drag): "auto"}

    # User overrides — moves drag under candidate_b.
    explicit_pairs_override = {str(drag): str(candidate_b.folder)}
    origins_manual = {str(drag): "manual"}

    tree_auto = build_pairing_tree_data(
        drag_paths=[drag],
        candidates=[candidate_a, candidate_b],
        explicit_pairs=explicit_pairs,
        pairing_origins=origins_auto,
    )
    tree_manual = build_pairing_tree_data(
        drag_paths=[drag],
        candidates=[candidate_a, candidate_b],
        explicit_pairs=explicit_pairs_override,
        pairing_origins=origins_manual,
    )

    # After auto: drag is under candidate_a with origin "auto".
    auto_bl = next(bl for bl in tree_auto["baselines"] if bl["drags"])
    assert auto_bl["folder_name"] == "Gly20_brown_rep01"
    assert auto_bl["drags"][0]["origin"] == "auto"

    # After manual override: drag is under candidate_b with origin "manual".
    manual_bl = next(bl for bl in tree_manual["baselines"] if bl["drags"])
    assert manual_bl["folder_name"] == "Gly20_brown_rep02"
    assert manual_bl["drags"][0]["origin"] == "manual"
    assert tree_manual["unpaired"] == []


def test_scenario5_run_level_selection_model_preserved() -> None:
    """
    Scenario 5: the run-level picker model is preserved.
    PairingCandidate.display_name and family_key are derived from the run folder,
    not from the internal 'analysis' subfolder name.
    """
    fk_run = make_family_pair_key(Path("/data/Gly20_brown_rep01"))
    fk_analysis = make_family_pair_key(Path("/data/Gly20_brown_rep01/analysis"))

    # display_name must be the run folder name
    candidate = PairingCandidate(
        folder=Path("/data/Gly20_brown_rep01/analysis"),
        family_key=fk_run,
        display_name="Gly20_brown_rep01",
    )
    assert candidate.display_name == "Gly20_brown_rep01"
    assert candidate.family_key == fk_run

    # family_key from run folder must match drag items (which have no /analysis segment)
    drag_fk = make_family_pair_key(Path("/runs/Gly20_drag_rep01.raw"))
    assert fk_run == drag_fk, (
        f"Run folder family_key {fk_run!r} must match drag family_key {drag_fk!r}"
    )


def test_scenario6_family_key_from_run_folder_not_analysis() -> None:
    """
    Scenario 6: family_key must be derived from the run folder name, not from 'analysis/'.
    The 'analysis' token itself must never drive the family key.
    """
    # Direct check via collect_brownian_baseline_candidates_from_roots logic:
    # _run_folder_for_analysis() must step up from 'analysis' to the parent run folder.
    from barakuda.devices.optical_tweezers.ui.batch_tools import _run_folder_for_analysis

    analysis_path = Path("/data/experiment/Gly20_brown_rep01/analysis")
    run_folder = _run_folder_for_analysis(analysis_path)
    assert run_folder.name == "Gly20_brown_rep01", (
        f"Expected run folder name, got {run_folder.name!r}"
    )
    assert run_folder.name != "analysis"

    fk = make_family_pair_key(run_folder)
    assert "analysis" not in fk.split("|"), (
        f"'analysis' must not appear in family_key tokens: {fk!r}"
    )


def test_scenario7_one_brownian_to_n_drag_supported() -> None:
    """
    Scenario 7: one Brownian baseline : multiple Drag runs (same place, different speeds).
    All drag items sharing the same family key must successfully link to the single baseline.
    """
    fk = make_family_pair_key("Gly40_brown_rep01")
    candidate = PairingCandidate(Path("/data/Gly40_brown_rep01/analysis"), fk, "Gly40_brown_rep01")
    drag_paths = [
        Path("/runs/Gly40_drag_rep01_slow.raw"),
        Path("/runs/Gly40_drag_rep01_fast.raw"),
        Path("/runs/Gly40_drag_rep01_r001.raw"),
        Path("/runs/Gly40_drag_rep01_r002.raw"),
    ]
    baseline_map, status_map = auto_pair_drag_items(drag_paths, [candidate])

    assert len(baseline_map) == 4, "All 4 drag items should link to the one baseline"
    for dp in drag_paths:
        assert status_map[str(dp)] == "baseline linked", (
            f"{dp.name}: expected linked, got {status_map[str(dp)]!r}"
        )
        assert baseline_map[str(dp)] == str(candidate.folder)

    # Pairing tree must show all 4 drags as children of the single baseline.
    explicit_pairs = {str(dp): str(candidate.folder) for dp in drag_paths}
    tree_data = build_pairing_tree_data(
        drag_paths=drag_paths,
        candidates=[candidate],
        explicit_pairs=explicit_pairs,
        pairing_origins={str(dp): "auto" for dp in drag_paths},
    )
    assert len(tree_data["baselines"]) == 1
    assert len(tree_data["baselines"][0]["drags"]) == 4
    assert tree_data["unpaired"] == []


def test_pairing_phase_state_model_in_main_window_source() -> None:
    """
    Verify that the three-phase model (idle / baseline_list / pairing_result)
    is implemented in main_window.py with correct phase transitions.
    """
    src = Path("C:/Work/BARAKUDA_FULL/barakuda/shell/main_window.py").read_text(encoding="utf-8")
    assert "_ot_pairing_phase" in src
    assert '"idle"' in src
    assert '"baseline_list"' in src
    assert '"pairing_result"' in src
    # auto-pair must transition to pairing_result
    assert "pairing_result" in src
    # build_baseline_list_view_data must be imported and used
    assert "build_baseline_list_view_data" in src


def test_build_baseline_list_view_data_has_correct_phase_key() -> None:
    """build_baseline_list_view_data() must return phase='baseline_list'."""
    candidates = [
        PairingCandidate(Path("/x/Brown_rep01/analysis"), "brown|rep01", "Brown_rep01"),
    ]
    view = build_baseline_list_view_data(candidates)
    assert view["phase"] == "baseline_list"
    assert len(view["baselines"]) == 1
    assert view["baselines"][0]["folder_name"] == "Brown_rep01"
    assert view["baselines"][0]["drags"] == []
    assert view["unpaired"] == []
    assert str(Path("/x/Brown_rep01/analysis")) in view["available_baseline_folders"]


def test_pairing_tab_phase_label_in_panel_source() -> None:
    """Panel must update its tree label based on phase (baseline_list vs pairing_result)."""
    panel_src = Path("C:/Work/BARAKUDA_FULL/barakuda/devices/optical_tweezers/ui/panel.py").read_text(encoding="utf-8")
    assert "baseline_list" in panel_src
    assert "Available Brownian baselines" in panel_src
    assert "Pairing results" in panel_src
    assert "_pairing_tree_label" in panel_src
