"""假身體：關節會以一階低通的方式慢慢跟上目標角度，沒有物理、不會跌倒。

適合在還沒買到零件前，先把 API、動畫、遙控、LINE 串接都寫好、測好。
"""

from __future__ import annotations

import numpy as np

from ..config import DuckConfig
from .base import Backend, RobotState


class MockBackend(Backend):
    def __init__(self, config: DuckConfig, time_constant: float = 0.05):
        super().__init__(config)
        self.tau = time_constant
        self.q = np.array(config.init_pose_array, dtype=float)
        self.dq = np.zeros_like(self.q)
        self.targets = self.q.copy()
        self.torque = False
        self.kps = config.kps()
        self.tilt_accel = np.array([0.0, 0.0, 9.81])  # 測試可以改它來模擬跌倒
        self.writes = 0

    def read_state(self) -> RobotState:
        return RobotState(q=self.q.copy(), dq=self.dq.copy(), accel=self.tilt_accel.copy())

    def write_targets(self, targets: np.ndarray) -> None:
        self.targets = np.asarray(targets, dtype=float).copy()
        self.writes += 1

    def set_kps(self, kps: list[int]) -> None:
        self.kps = list(kps)

    def set_torque(self, enabled: bool) -> None:
        self.torque = enabled

    def step(self, dt: float) -> None:
        if not self.torque:
            self.dq[:] = 0.0
            return
        alpha = min(1.0, dt / self.tau)
        new_q = self.q + alpha * (self.targets - self.q)
        self.dq = (new_q - self.q) / dt
        self.q = new_q
