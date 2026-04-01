from __future__ import annotations

from barakuda.devices.acquisition.ui.stage_scan_lifecycle import StageScanLifecycleGuard


def test_stage_scan_guard_normal_completion() -> None:
    guard = StageScanLifecycleGuard()
    token = guard.start_request()
    assert token is not None
    ok, reason = guard.should_publish(token)
    assert ok is True
    assert reason == "accepted"


def test_stage_scan_guard_panel_destroyed_before_completion() -> None:
    guard = StageScanLifecycleGuard()
    token = guard.start_request()
    assert token is not None
    guard.cancel_all()
    ok, reason = guard.should_publish(token)
    assert ok is False
    assert reason in {"panel_closing", "generation_mismatch"}


def test_stage_scan_guard_repeated_rescan_discards_stale_result() -> None:
    guard = StageScanLifecycleGuard()
    token1 = guard.start_request()
    token2 = guard.start_request()
    assert token1 is not None and token2 is not None

    ok1, reason1 = guard.should_publish(token1)
    ok2, reason2 = guard.should_publish(token2)

    assert ok1 is False
    assert reason1 == "stale_request"
    assert ok2 is True
    assert reason2 == "accepted"


def test_stage_scan_guard_cancellation_path() -> None:
    guard = StageScanLifecycleGuard()
    token = guard.start_request()
    assert token is not None
    guard.cancel_all()
    ok, reason = guard.should_publish(token)
    assert ok is False
    assert reason == "panel_closing"
