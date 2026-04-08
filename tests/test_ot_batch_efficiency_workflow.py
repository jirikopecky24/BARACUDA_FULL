from __future__ import annotations

from pathlib import Path
import sys
import types

from barakuda.devices.optical_tweezers.ui.batch_tools import (
    MODE_STRATEGIES,
    PairingCandidate,
    advanced_visibility,
    auto_pair_drag_items,
    build_pairing_tree_data,
    collect_brownian_baseline_candidates_from_roots,
    drag_action_visibility,
    format_baseline_link_status,
    format_batch_progress,
    format_current_file_progress,
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
    assert bl["folder_name"] == brown.name
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
    assert brown1.name in folder_names
    assert brown2.name in folder_names
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
    assert "Pairing map" in panel_src
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
