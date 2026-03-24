from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..analysis import analyze_drag_run
from ..schema import DragAnalysisConfig
from .protocols.oscillatory import OscillatoryProtocolConfig, OscillatoryAnalysisResult
from .protocols.step_response import StepResponseProtocolConfig, StepResponseAnalysisResult

ActiveUmbrellaProtocolType = Literal["constant_velocity", "oscillatory", "step_response"]


@dataclass(frozen=True)
class ActiveUmbrellaConfig:
    """Active umbrella (active drag) protocol selection.

    The common stage-aware foundation is still derived from DRAG v1 (tracking + alignment).
    Protocol-specific analysis lives in `active_umbrella/protocols/`.
    """

    protocol_type: ActiveUmbrellaProtocolType
    drag_config: DragAnalysisConfig
    oscillatory: OscillatoryProtocolConfig | None = None
    step_response: StepResponseProtocolConfig | None = None


def analyze_active_umbrella_run(
    run_dir,
    config: ActiveUmbrellaConfig,
    trajectory_path=None,
):
    """Analyze an active OT drag run using the selected active protocol.

    For NOW:
    - `constant_velocity` delegates to DRAG v1 (stage-aware).
    - `oscillatory` is scaffolded for offline verification on synthetic runs.
    - `step_response` provides basic transient validation metrics (scaffold).
    """

    protocol_type = config.protocol_type

    if protocol_type == "constant_velocity":
        return analyze_drag_run(run_dir, config.drag_config, trajectory_path=trajectory_path)

    if protocol_type == "oscillatory":
        if config.oscillatory is None:
            raise ValueError("oscillatory protocol_type requires config.oscillatory")
        from .protocols.oscillatory import analyze_oscillatory_drag_run

        return analyze_oscillatory_drag_run(
            run_dir=run_dir,
            drag_config=config.drag_config,
            osc_config=config.oscillatory,
            trajectory_path=trajectory_path,
        )

    if protocol_type == "step_response":
        if config.step_response is None:
            raise ValueError("step_response protocol_type requires config.step_response")
        from .protocols.step_response import analyze_step_response_drag_run

        return analyze_step_response_drag_run(
            run_dir=run_dir,
            drag_config=config.drag_config,
            step_config=config.step_response,
            trajectory_path=trajectory_path,
        )

    raise ValueError(f"Unknown protocol_type: {protocol_type}")

