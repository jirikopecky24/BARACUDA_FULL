"""Minimal StageTraceRecorder.

Records orchestration events and optional sparse motion samples,
then writes the stage trace CSV.

Design constraints (see docs/acquisition_motion_drag_note.md):
- Stateless regarding physics — only records what happened, never interprets it.
- t_s values are relative to run_t0 (established by orchestration, NOT derived from
  video_timestamps.csv which is a separate clock axis).
- Must produce at minimum: columns t_s, event.
- Must include the 8 mandatory orchestration events (recording_start … recording_stop).
- Optional explicit motion anchor events:
  motion_command_issued, motion_running_confirmed.
- trace file is the DRAG loader's primary timing source.
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class _TraceRow:
    t_s: float
    event: str
    position_user: Optional[float] = None
    velocity_user_s: Optional[float] = None
    state: Optional[str] = None


class StageTraceRecorder:
    """Lightweight in-memory recorder for stage orchestration events.

    Usage:
        recorder = StageTraceRecorder(run_t0)
        recorder.log("recording_start")
        recorder.log("motion_start", position_user=1234.0, state="moving")
        ...
        recorder.write_csv(path)
    """

    def __init__(self, run_t0: float) -> None:
        """
        Args:
            run_t0: value of time.perf_counter() captured at the start of the run.
                    All logged times will be (perf_counter() - run_t0).
        """
        self._run_t0 = run_t0
        self._rows: list[_TraceRow] = []

    def log(
        self,
        event: str,
        *,
        t_override: Optional[float] = None,
        position_user: Optional[float] = None,
        velocity_user_s: Optional[float] = None,
        state: Optional[str] = None,
    ) -> float:
        """Log an event at the current (or overridden) run-clock time.

        Returns the t_s value used so the caller can store it in stage.json.
        """
        t_s = (t_override if t_override is not None
               else time.perf_counter() - self._run_t0)
        self._rows.append(_TraceRow(
            t_s=t_s,
            event=event,
            position_user=position_user,
            velocity_user_s=velocity_user_s,
            state=state,
        ))
        return t_s

    def write_csv(self, path: Path) -> None:
        """Write the recorded trace to a CSV file.

        Columns: t_s, event, position_user, velocity_user_s, state
        t_s is the mandatory DRAG-loader column (seconds from run_t0).
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["t_s", "event", "position_user", "velocity_user_s", "state"],
            )
            writer.writeheader()
            for row in self._rows:
                writer.writerow({
                    "t_s": f"{row.t_s:.6f}",
                    "event": row.event,
                    "position_user": (
                        f"{row.position_user:.4f}"
                        if row.position_user is not None else ""
                    ),
                    "velocity_user_s": (
                        f"{row.velocity_user_s:.4f}"
                        if row.velocity_user_s is not None else ""
                    ),
                    "state": row.state or "",
                })

    @property
    def rows(self) -> list[_TraceRow]:
        return list(self._rows)

    def get_event_time(self, event_name: str) -> Optional[float]:
        """Return t_s of the first occurrence of event_name, or None."""
        for row in self._rows:
            if row.event == event_name:
                return row.t_s
        return None
