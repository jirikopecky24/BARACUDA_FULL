from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDoubleSpinBox,
    QMessageBox,
)

from barakuda.shell.stage_service import get_stage_service


@dataclass(frozen=True)
class StageConsoleSnapshot:
    connected: bool
    state_text: str
    owner_text: str
    position_um: Optional[float] = None
    speed_um_s: Optional[float] = None
    speed_note: str = ""
    encoder: Optional[float] = None
    stage_state: str = ""


class _MoveWorker(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, fn: Callable[[], None]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class StageConsoleWindow(QMainWindow):
    """Standalone Stage Console window (UI shell only).

    Phase 5 scope: create the window + UI structure and safe display hooks.
    No stage connection ownership, no motion commands, no charts.
    """

    def __init__(
        self,
        *,
        snapshot_provider: Optional[Callable[[], StageConsoleSnapshot]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Stage Console")
        self.resize(720, 520)

        self._snapshot_provider = snapshot_provider
        self._service = get_stage_service()
        self._move_thread: QThread | None = None
        self._move_worker: _MoveWorker | None = None

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ---------------- Connection / ownership ----------------
        grp_state = QGroupBox("Connection / Ownership")
        state_form = QFormLayout(grp_state)

        self._lbl_connected = QLabel("Disconnected")
        self._lbl_state = QLabel("—")
        self._lbl_owner = QLabel("—")
        self._lbl_pos_um = QLabel("—")
        self._lbl_speed_um_s = QLabel("—")
        self._lbl_encoder = QLabel("—")
        self._lbl_stage_state = QLabel("—")
        self._lbl_pos_um.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_pos_um.setStyleSheet("font-size: 18px; font-weight: 600;")

        state_form.addRow("Connection:", self._lbl_connected)
        state_form.addRow("State:", self._lbl_state)
        state_form.addRow("Owner:", self._lbl_owner)
        state_form.addRow("Position (µm):", self._lbl_pos_um)
        state_form.addRow("Speed (µm/s):", self._lbl_speed_um_s)
        state_form.addRow("Encoder:", self._lbl_encoder)
        state_form.addRow("Stage state:", self._lbl_stage_state)

        row_lease = QHBoxLayout()
        self._btn_take_control = QPushButton("Take control")
        self._btn_release_control = QPushButton("Release control")
        self._btn_take_control.clicked.connect(self._on_take_control)
        self._btn_release_control.clicked.connect(self._on_release_control)
        row_lease.addWidget(self._btn_take_control)
        row_lease.addWidget(self._btn_release_control)
        row_lease.addStretch(1)
        state_form.addRow("Lease:", row_lease)

        layout.addWidget(grp_state)

        # ---------------- Manual control (UI only, disabled in Phase 5) ----------------
        grp_ctrl = QGroupBox("Manual control (MVP shell)")
        ctrl_layout = QVBoxLayout(grp_ctrl)

        row_jog = QHBoxLayout()
        self._btn_jog_minus = QPushButton("Jog −")
        self._btn_jog_plus = QPushButton("Jog +")
        self._spin_jog_step_um = QDoubleSpinBox()
        self._spin_jog_step_um.setRange(0.0, 1e9)
        self._spin_jog_step_um.setDecimals(3)
        self._spin_jog_step_um.setValue(5.0)
        self._spin_jog_step_um.setSuffix(" µm")
        row_jog.addWidget(self._btn_jog_minus)
        row_jog.addWidget(self._btn_jog_plus)
        row_jog.addStretch(1)
        row_jog.addWidget(QLabel("Step:"))
        row_jog.addWidget(self._spin_jog_step_um)
        ctrl_layout.addLayout(row_jog)

        row_move = QHBoxLayout()
        self._edit_move_step_um = QLineEdit()
        self._edit_move_step_um.setPlaceholderText("e.g. 10.0")
        self._btn_move_step = QPushButton("Move by step (µm)")
        self._edit_move_abs_um = QLineEdit()
        self._edit_move_abs_um.setPlaceholderText("e.g. 250.0")
        self._btn_move_abs = QPushButton("Move to absolute (µm)")
        row_move.addWidget(self._btn_move_step)
        row_move.addWidget(self._edit_move_step_um, 1)
        row_move.addSpacing(12)
        row_move.addWidget(self._btn_move_abs)
        row_move.addWidget(self._edit_move_abs_um, 1)
        ctrl_layout.addLayout(row_move)

        row_kin = QHBoxLayout()
        self._spin_speed_um_s = QDoubleSpinBox()
        self._spin_speed_um_s.setRange(0.0, 1e12)
        self._spin_speed_um_s.setDecimals(3)
        self._spin_speed_um_s.setSuffix(" µm/s")
        self._spin_speed_um_s.setValue(50.0)

        self._spin_accel_um_s2 = QDoubleSpinBox()
        self._spin_accel_um_s2.setRange(0.0, 1e12)
        self._spin_accel_um_s2.setDecimals(3)
        self._spin_accel_um_s2.setSuffix(" µm/s²")
        self._spin_accel_um_s2.setValue(100.0)

        self._spin_decel_um_s2 = QDoubleSpinBox()
        self._spin_decel_um_s2.setRange(0.0, 1e12)
        self._spin_decel_um_s2.setDecimals(3)
        self._spin_decel_um_s2.setSuffix(" µm/s²")
        self._spin_decel_um_s2.setValue(100.0)

        row_kin.addWidget(QLabel("Speed:"))
        row_kin.addWidget(self._spin_speed_um_s)
        row_kin.addWidget(QLabel("Accel:"))
        row_kin.addWidget(self._spin_accel_um_s2)
        row_kin.addWidget(QLabel("Decel:"))
        row_kin.addWidget(self._spin_decel_um_s2)
        ctrl_layout.addLayout(row_kin)

        row_stop = QHBoxLayout()
        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setToolTip("MVP safety policy: Stop only available to current lease owner.")
        row_stop.addWidget(self._btn_stop)
        row_stop.addStretch(1)
        ctrl_layout.addLayout(row_stop)

        layout.addWidget(grp_ctrl)

        # Respect Phase 3 policy by default: monitor-only shell.
        self._set_controls_enabled(False)

        # Manual control wiring (Phase 6)
        self._btn_jog_minus.clicked.connect(lambda: self._start_move_relative(-self._spin_jog_step_um.value()))
        self._btn_jog_plus.clicked.connect(lambda: self._start_move_relative(+self._spin_jog_step_um.value()))
        self._btn_move_step.clicked.connect(self._on_move_step_clicked)
        self._btn_move_abs.clicked.connect(self._on_move_abs_clicked)
        self._btn_stop.clicked.connect(self._on_stop_clicked)

        # Speed/accel/decel mapping is not implemented; keep disabled for MVP safety.
        self._spin_speed_um_s.setEnabled(False)
        self._spin_accel_um_s2.setEnabled(False)
        self._spin_decel_um_s2.setEnabled(False)

        # ---------------- Polling (minimal, no contention) ----------------
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)  # conservative shell default (4 Hz)
        self._poll_timer.timeout.connect(self._poll_snapshot)

    def set_snapshot_provider(self, provider: Optional[Callable[[], StageConsoleSnapshot]]) -> None:
        self._snapshot_provider = provider
        self._poll_snapshot()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._poll_timer.start()
        self._poll_snapshot()

    def closeEvent(self, event) -> None:
        try:
            self._poll_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (
            self._btn_jog_minus,
            self._btn_jog_plus,
            self._spin_jog_step_um,
            self._btn_move_step,
            self._edit_move_step_um,
            self._btn_move_abs,
            self._edit_move_abs_um,
            self._btn_stop,
        ):
            w.setEnabled(enabled)

    def _poll_snapshot(self) -> None:
        if self._snapshot_provider is None:
            self._apply_snapshot(StageConsoleSnapshot(
                connected=False,
                state_text="Monitor-only (not wired)",
                owner_text="—",
                position_um=None,
            ))
            return
        try:
            snap = self._snapshot_provider()
        except Exception:
            snap = StageConsoleSnapshot(
                connected=False,
                state_text="Error (snapshot unavailable)",
                owner_text="—",
                position_um=None,
            )
        self._apply_snapshot(snap)

    def _apply_snapshot(self, snap: StageConsoleSnapshot) -> None:
        self._lbl_connected.setText("Connected" if snap.connected else "Disconnected")
        self._lbl_state.setText(snap.state_text or "—")
        self._lbl_owner.setText(snap.owner_text or "—")
        self._lbl_pos_um.setText("—" if snap.position_um is None else f"{snap.position_um:.3f}")
        if snap.speed_um_s is None:
            self._lbl_speed_um_s.setText("—" if not snap.speed_note else f"—  ({snap.speed_note})")
        else:
            note = f" ({snap.speed_note})" if snap.speed_note else ""
            self._lbl_speed_um_s.setText(f"{snap.speed_um_s:.3f}{note}")
        self._lbl_encoder.setText("—" if snap.encoder is None else f"{snap.encoder}")
        self._lbl_stage_state.setText(snap.stage_state or "—")

        # Enable manual controls only when Stage Console owns the lease and stage is usable.
        lease = self._service.lease_state()
        controls_enabled = (
            lease.connected
            and lease.owner == "stage_console"
            and not lease.busy
            and not lease.run_active
            and lease.stage_um_per_unit is not None
            and lease.stage_um_per_unit > 0
            and self._move_thread is None
        )
        self._set_controls_enabled(controls_enabled)

        self._btn_take_control.setEnabled(lease.connected and lease.owner != "stage_console" and not lease.run_active)
        self._btn_release_control.setEnabled(lease.owner == "stage_console" and not lease.busy and not lease.run_active)

    def _on_take_control(self) -> None:
        ok, reason = self._service.request_lease("stage_console")
        if not ok:
            QMessageBox.information(self, "Stage Console", reason)
        self._poll_snapshot()

    def _on_release_control(self) -> None:
        self._service.release_lease("stage_console")
        self._poll_snapshot()

    def _on_stop_clicked(self) -> None:
        try:
            self._service.stop(owner="stage_console")
        except Exception as exc:
            QMessageBox.warning(self, "Stage Console", str(exc))
        self._poll_snapshot()

    def _on_move_step_clicked(self) -> None:
        try:
            v = float(self._edit_move_step_um.text().strip())
        except Exception:
            QMessageBox.information(self, "Stage Console", "Enter a numeric step in µm.")
            return
        self._start_move_relative(v)

    def _on_move_abs_clicked(self) -> None:
        try:
            v = float(self._edit_move_abs_um.text().strip())
        except Exception:
            QMessageBox.information(self, "Stage Console", "Enter a numeric absolute position in µm.")
            return
        self._start_move_absolute(v)

    def _start_move_relative(self, delta_um: float) -> None:
        if self._move_thread is not None:
            return
        fn = lambda: self._service.move_relative_um(owner="stage_console", delta_um=float(delta_um))
        self._start_worker(fn)

    def _start_move_absolute(self, target_um: float) -> None:
        if self._move_thread is not None:
            return
        fn = lambda: self._service.move_to_um(owner="stage_console", target_um=float(target_um))
        self._start_worker(fn)

    def _start_worker(self, fn: Callable[[], None]) -> None:
        self._set_controls_enabled(False)
        self._move_thread = QThread()
        self._move_worker = _MoveWorker(fn)
        self._move_worker.moveToThread(self._move_thread)
        self._move_thread.started.connect(self._move_worker.run)
        self._move_worker.finished.connect(self._move_thread.quit)
        self._move_worker.error.connect(self._move_thread.quit)
        self._move_worker.finished.connect(self._on_move_done)
        self._move_worker.error.connect(self._on_move_error)
        self._move_thread.finished.connect(self._move_worker.deleteLater)
        self._move_thread.finished.connect(self._move_thread.deleteLater)
        self._move_thread.start()

    def _on_move_done(self) -> None:
        self._move_thread = None
        self._move_worker = None
        self._poll_snapshot()

    def _on_move_error(self, err: str) -> None:
        self._move_thread = None
        self._move_worker = None
        QMessageBox.warning(self, "Stage Console", err)
        self._poll_snapshot()

