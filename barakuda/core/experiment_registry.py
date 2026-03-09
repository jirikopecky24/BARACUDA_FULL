"""
Experiment registry: manage multiple datasets belonging to one experiment.

Operates on runs/experiments/. Does not change dataset schema or pipelines.
"""
from __future__ import annotations

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


# Artifact file name -> summary key (for get_experiment_summary)
_ANALYSIS_FILE_TO_ARTIFACT = {
    "trajectory.csv": "trajectory",
    "tracking.csv": "tracking",
    "psd.csv": "psd",
    "qc.json": "qc",
    "run.json": "run",
}


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
