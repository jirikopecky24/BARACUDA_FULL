from __future__ import annotations

from pathlib import Path

from barakuda.shell.widgets.dataset_panel import (
    discover_from_hierarchical_folder_selection,
    discover_importable_paths_from_roots,
    is_primary_dataset_input,
    minimal_import_roots,
)


def test_minimal_import_roots_keeps_parent_not_children_when_both_selected(tmp_path: Path) -> None:
    parent = tmp_path / "water"
    child = parent / "Water_brown_rep01"
    parent.mkdir()
    child.mkdir()
    roots = minimal_import_roots([parent, child])
    assert len(roots) == 1
    assert roots[0] == parent.resolve()


def test_minimal_import_roots_keeps_siblings(tmp_path: Path) -> None:
    a = tmp_path / "water" / "Water_brown_rep01"
    b = tmp_path / "water" / "Water_drag_rep01"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    roots = minimal_import_roots([a, b])
    assert len(roots) == 2


def test_discover_multi_level_day_structure(tmp_path: Path) -> None:
    """DAY / sample / run / raw — discovery from intermediate roots."""
    raw = (
        tmp_path
        / "DAY03"
        / "water"
        / "Water_brown_rep01"
        / "wb.raw"
    )
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"x")
    (raw.parent / "wb_timestamps.csv").write_text("f,t\n0,0\n", encoding="utf-8")

    day = tmp_path / "DAY03"
    roots = minimal_import_roots([day / "water"])
    paths = discover_from_hierarchical_folder_selection(roots)
    assert len(paths) == 1
    assert paths[0].resolve() == raw.resolve()


def test_discover_partial_sample_branch_only(tmp_path: Path) -> None:
    gly = tmp_path / "DAY" / "Gly_40" / "Gly40_drag_rep01" / "d.raw"
    gly.parent.mkdir(parents=True)
    gly.write_bytes(b"y")
    (gly.parent / "d_timestamps.csv").write_text("f,t\n0,0\n", encoding="utf-8")

    w = tmp_path / "DAY" / "water" / "Water_brown_rep01" / "w.raw"
    w.parent.mkdir(parents=True)
    w.write_bytes(b"z")
    (w.parent / "w_timestamps.csv").write_text("f,t\n0,0\n", encoding="utf-8")

    roots = minimal_import_roots([tmp_path / "DAY" / "Gly_40"])
    paths = discover_from_hierarchical_folder_selection(roots)
    assert len(paths) == 1
    assert paths[0].name == "d.raw"


def test_discover_dedupes_duplicate_roots_in_list(tmp_path: Path) -> None:
    f = tmp_path / "x.raw"
    f.write_bytes(b"1")
    out = discover_importable_paths_from_roots([tmp_path, tmp_path])
    assert len(out) == 1


def test_sidecar_files_not_primary_imports(tmp_path: Path) -> None:
    f = tmp_path / "run.raw"
    f.write_bytes(b"1")
    (tmp_path / "run_timestamps.csv").write_text("a,b\n", encoding="utf-8")
    out = discover_importable_paths_from_roots([tmp_path])
    assert [p.name for p in out] == ["run.raw"]
    assert not any("timestamps" in p.name for p in out)


def test_empty_folder_imports_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "empty_branch"
    empty.mkdir(parents=True)
    assert discover_importable_paths_from_roots([empty]) == []


def test_is_primary_dataset_input_rejects_sidecar_name() -> None:
    p = Path("C:/x/run_timestamps.csv")
    assert is_primary_dataset_input(p) is False
