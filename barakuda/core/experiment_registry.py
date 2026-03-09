"""
Experiment registry: manage multiple datasets belonging to one experiment.

Operates on runs/experiments/. Does not change dataset schema or pipelines.
"""
from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


EXPERIMENTS_DIR = "experiments"
DATASETS_DIR = "datasets"
EXPERIMENT_JSON = "experiment.json"


def _experiments_root(runs_folder: Path) -> Path:
    return Path(runs_folder) / EXPERIMENTS_DIR


def create_experiment(runs_folder: Path, experiment_id: str) -> Path:
    """
    Create a new experiment folder and experiment.json under runs/experiments/.

    Returns the path to the experiment folder (runs/experiments/<experiment_id>/).
    """
    root = _experiments_root(runs_folder)
    root.mkdir(parents=True, exist_ok=True)
    exp_path = root / experiment_id
    exp_path.mkdir(parents=True, exist_ok=True)
    (exp_path / DATASETS_DIR).mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "description": "",
        "operator": "",
        "instrument": "BARAKUDA",
        "datasets": [],
    }
    (exp_path / EXPERIMENT_JSON).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return exp_path


def load_experiment(experiment_path: Path) -> dict[str, Any]:
    """
    Load experiment.json from an experiment folder.

    experiment_path: path to experiment folder (e.g. runs/experiments/hydrogel_test)
                    or directly to experiment.json.
    Returns the parsed experiment metadata dict.
    """
    path = Path(experiment_path).resolve()
    if path.is_file() and path.name == EXPERIMENT_JSON:
        json_path = path
    else:
        json_path = path / EXPERIMENT_JSON
    if not json_path.is_file():
        raise FileNotFoundError(f"No {EXPERIMENT_JSON} at {experiment_path}")
    return json.loads(json_path.read_text(encoding="utf-8"))


def list_experiments(runs_folder: Path) -> list[dict[str, Any]]:
    """
    List all experiments under runs/experiments/.

    Returns a list of experiment metadata dicts (from each experiment.json).
    Skips invalid or missing experiment.json.
    """
    root = _experiments_root(runs_folder)
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        json_path = d / EXPERIMENT_JSON
        if not json_path.is_file():
            continue
        try:
            result.append(load_experiment(d))
        except (json.JSONDecodeError, OSError):
            continue
    return result


def discover_experiments(runs_folder: Path) -> list[dict[str, Any]]:
    """
    Discover available experiments under runs/experiments/ for UI or listing.

    Scans runs/experiments/, loads each experiment.json, and returns a list of
    entries: experiment.json payload plus "experiment_path" (absolute Path) for
    each valid experiment. Skips invalid or missing experiment.json.
    """
    root = _experiments_root(runs_folder)
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        json_path = d / EXPERIMENT_JSON
        if not json_path.is_file():
            continue
        try:
            payload = load_experiment(d)
            payload = dict(payload)
            payload["experiment_path"] = d.resolve()
            result.append(payload)
        except (json.JSONDecodeError, OSError):
            continue
    return result


def list_datasets(experiment_path: Path) -> list[Path]:
    """
    List dataset roots under experiment_path/datasets/.

    Returns paths to each dataset directory (each containing item.json or
    acquisition/analysis/exports structure). Paths are absolute.
    """
    path = Path(experiment_path).resolve()
    datasets_dir = path / DATASETS_DIR
    if not datasets_dir.is_dir():
        return []
    return [p for p in sorted(datasets_dir.iterdir()) if p.is_dir()]


# Artifact file name -> summary key (for get_experiment_summary and get_dataset_artifacts)
_ANALYSIS_FILE_TO_ARTIFACT = {
    "trajectory.csv": "trajectory",
    "tracking.csv": "tracking",
    "psd.csv": "psd",
    "qc.json": "qc",
    "run.json": "run",
}


def get_dataset_artifacts(dataset_path: Path) -> list[str]:
    """
    Report available artifacts for a single dataset by inspecting dataset_root/analysis/
    and dataset_root/exports/.

    Returns a sorted list of artifact keys present, e.g. ["trajectory", "tracking", "psd", "qc", "run", "exports"].
    """
    path = Path(dataset_path).resolve()
    if not path.is_dir():
        return []

    out: set[str] = set()
    analysis_dir = path / "analysis"
    if analysis_dir.is_dir():
        for fname, artifact_key in _ANALYSIS_FILE_TO_ARTIFACT.items():
            if (analysis_dir / fname).is_file():
                out.add(artifact_key)

    exports_dir = path / "exports"
    if exports_dir.is_dir() and any(exports_dir.iterdir()):
        out.add("exports")

    return sorted(out)


def get_experiment_summary(experiment_path: Path) -> dict[str, Any]:
    """
    Build summary metadata for an experiment folder.

    Input: experiment folder (e.g. runs/experiments/hydrogel_test).
    Output: dict with datasets (count), modules (list), artifacts (list), date_range (min/max).
    """
    path = Path(experiment_path).resolve()
    payload = load_experiment(path)
    dataset_paths = list_datasets(path)

    modules_set: set[str] = set()
    artifacts_set: set[str] = set()
    dates: list[str] = []

    exp_created = payload.get("created_at")
    if exp_created:
        dates.append(exp_created)

    for ds_path in dataset_paths:
        item_json = ds_path / "item.json"
        if item_json.is_file():
            try:
                item = json.loads(item_json.read_text(encoding="utf-8"))
                mod = item.get("module")
                if mod:
                    modules_set.add(str(mod))
                for key in ("created_at", "updated_at"):
                    if item.get(key):
                        dates.append(item[key])
            except (json.JSONDecodeError, OSError):
                pass

        analysis_dir = ds_path / "analysis"
        if analysis_dir.is_dir():
            for fname, artifact_key in _ANALYSIS_FILE_TO_ARTIFACT.items():
                if (analysis_dir / fname).is_file():
                    artifacts_set.add(artifact_key)

    date_min = min(dates) if dates else None
    date_max = max(dates) if dates else None

    return {
        "datasets": len(dataset_paths),
        "modules": sorted(modules_set),
        "artifacts": sorted(artifacts_set),
        "date_range": {"min": date_min, "max": date_max} if (date_min and date_max) else {},
    }


def _read_trajectory_stats(analysis_dir: Path) -> dict[str, Any] | None:
    """Read trajectory.csv and return simple comparable stats. Returns None if missing/invalid."""
    traj_path = analysis_dir / "trajectory.csv"
    if not traj_path.is_file():
        return None
    try:
        with traj_path.open("r", encoding="utf-8", newline="") as f:
            lines = [ln for ln in f if not ln.strip().startswith("#")]
        if not lines:
            return None
        reader = csv.DictReader(lines)
        rows = list(reader)
    except (OSError, csv.Error):
        return None
    if not rows:
        return {"n_points": 0, "t_span_s": 0.0}

    def _col(name: str) -> list[float]:
        if not rows or name not in rows[0]:
            return []
        out = []
        for r in rows:
            try:
                out.append(float(r[name]))
            except (ValueError, TypeError):
                pass
        return out

    t_col = _col("t_s") or _col("t")
    n = len(rows)
    t_span = (max(t_col) - min(t_col)) if len(t_col) >= 2 else 0.0
    out: dict[str, Any] = {"n_points": n, "t_span_s": t_span}
    for xkey, ykey in [("x_um", "y_um"), ("x_px", "y_px")]:
        xv, yv = _col(xkey), _col(ykey)
        if xv:
            out[f"{xkey}_mean"] = sum(xv) / len(xv)
            out[f"{xkey}_std"] = (sum((x - out[f"{xkey}_mean"]) ** 2 for x in xv) / len(xv)) ** 0.5
        if yv:
            out[f"{ykey}_mean"] = sum(yv) / len(yv)
            out[f"{ykey}_std"] = (sum((y - out[f"{ykey}_mean"]) ** 2 for y in yv) / len(yv)) ** 0.5
    return out


def _read_psd_curves(analysis_dir: Path) -> dict[str, Any] | None:
    """Read psd.csv and return freq + psd columns for comparison. Returns None if missing/invalid."""
    psd_path = analysis_dir / "psd.csv"
    if not psd_path.is_file():
        return None
    try:
        with psd_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except (OSError, csv.Error):
        return None
    if not rows:
        return None
    # Prefer freq_hz / psd or freq / psd column names
    first = rows[0]
    freq_key = next((k for k in ("freq_hz", "freq", "frequency") if k in first), None)
    psd_key = next((k for k in ("psd", "psd_um2_hz", "P") if k in first), None)
    if not freq_key or not psd_key:
        return None
    try:
        freq = [float(r[freq_key]) for r in rows if r.get(freq_key)]
        psd = [float(r[psd_key]) for r in rows if r.get(psd_key)]
    except (ValueError, TypeError):
        return None
    if len(freq) != len(psd) or not freq:
        return None
    return {"freq_hz": freq, "psd_um2_hz": psd}


def _read_drift_stats(analysis_dir: Path) -> dict[str, Any] | None:
    """Read run.json and return drift-related fields for comparison. Returns None if missing/invalid."""
    run_path = analysis_dir / "run.json"
    if not run_path.is_file():
        return None
    try:
        payload = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    drift_keys = ("drift_enabled", "drift_window_s", "drift_mode")
    out = {k: payload[k] for k in drift_keys if k in payload}
    return out if out else None


def compare_datasets(dataset_paths: list[Path]) -> dict[str, Any]:
    """
    Extract comparable artifacts from multiple datasets for comparison (no plotting).

    Returns structured data: per-dataset trajectory stats, PSD curves, and drift stats
    when available. Used later for experiment comparison and plotting.
    """
    paths = [Path(p).resolve() for p in dataset_paths if Path(p).is_dir()]
    datasets: list[dict[str, Any]] = []
    for ds_path in paths:
        analysis_dir = ds_path / "analysis"
        entry: dict[str, Any] = {
            "dataset_path": str(ds_path),
            "dataset_name": ds_path.name,
            "trajectory_stats": _read_trajectory_stats(analysis_dir) if analysis_dir.is_dir() else None,
            "psd": _read_psd_curves(analysis_dir) if analysis_dir.is_dir() else None,
            "drift_stats": _read_drift_stats(analysis_dir) if analysis_dir.is_dir() else None,
        }
        datasets.append(entry)
    return {"datasets": datasets}


def export_experiment(
    experiment_path: Path,
    output_dir: Path | None = None,
    *,
    include_artifacts: bool = True,
) -> Path:
    """
    Export entire experiment: summary, dataset list, and selected artifacts.

    Writes to output_dir (default: experiment_path/exports/<timestamp>):
    - experiment_summary.json (from get_experiment_summary)
    - dataset_list.json (paths and names)
    - datasets/<name>/ with analysis/ and exports/ contents when include_artifacts is True.

    Returns the path to the export directory.
    """
    path = Path(experiment_path).resolve()
    if not (path / EXPERIMENT_JSON).is_file():
        raise FileNotFoundError(f"Not an experiment folder: {path}")

    if output_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = path / "exports" / f"export_{ts}"
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = get_experiment_summary(path)
    (output_dir / "experiment_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    dataset_paths = list_datasets(path)
    dataset_list = [{"name": p.name, "path": str(p)} for p in dataset_paths]
    (output_dir / "dataset_list.json").write_text(
        json.dumps({"datasets": dataset_list}, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if include_artifacts and dataset_paths:
        out_datasets = output_dir / "datasets"
        out_datasets.mkdir(parents=True, exist_ok=True)
        for ds_path in dataset_paths:
            dest = out_datasets / ds_path.name
            dest.mkdir(parents=True, exist_ok=True)
            for sub in ("analysis", "exports"):
                src = ds_path / sub
                if src.is_dir():
                    dest_sub = dest / sub
                    if dest_sub.exists():
                        shutil.rmtree(dest_sub)
                    shutil.copytree(src, dest_sub)

    return output_dir


def register_dataset_to_experiment(
    runs_folder: Path,
    dataset_path: Path,
    experiment_id: str,
    *,
    copy: bool = True,
) -> Path:
    """
    Attach a dataset to an experiment by copying (or moving) it under
    runs/experiments/<experiment_id>/datasets/ and updating experiment.json.

    dataset_path: path to the dataset root (folder containing item.json,
                  acquisition/, analysis/, etc.). Not modified.
    experiment_id: id of the experiment (must exist).
    copy: if True, copy the dataset; if False, move it.

    Returns the path to the dataset inside the experiment (experiment/datasets/<name>).
    Does not change dataset schema or any file inside the dataset.
    """
    dataset_path = Path(dataset_path).resolve()
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"Dataset path is not a directory: {dataset_path}")

    exp_path = _experiments_root(runs_folder) / experiment_id
    if not exp_path.is_dir():
        raise FileNotFoundError(f"Experiment not found: {exp_path}")

    json_path = exp_path / EXPERIMENT_JSON
    if not json_path.is_file():
        raise FileNotFoundError(f"No {EXPERIMENT_JSON} in experiment: {exp_path}")

    name = dataset_path.name
    dest = exp_path / DATASETS_DIR / name
    if dest.exists():
        raise FileExistsError(f"Dataset already registered at {dest}")

    if copy:
        shutil.copytree(dataset_path, dest)
    else:
        shutil.move(str(dataset_path), str(dest))

    payload = load_experiment(exp_path)
    datasets_list: list[str] = payload.get("datasets", [])
    rel_entry = f"{DATASETS_DIR}/{name}"
    if rel_entry not in datasets_list:
        datasets_list.append(rel_entry)
        payload["datasets"] = datasets_list
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return dest
