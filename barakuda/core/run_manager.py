from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_dir: Path


class RunManager:
    def __init__(self, runs_folder: Path) -> None:
        self.runs_folder = Path(runs_folder)
        self.runs_folder.mkdir(parents=True, exist_ok=True)

    def create_run(self, input_path: Path, config: Dict[str, Any]) -> RunResult:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + input_path.stem
        run_dir = self.runs_folder / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "input_path": str(input_path),
            "config": config,
        }
        (run_dir / "run.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return RunResult(run_id=run_id, run_dir=run_dir)

    def save_json(self, run_dir: Path, name: str, payload: Dict[str, Any]) -> Path:
        out = Path(run_dir) / name
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return out
