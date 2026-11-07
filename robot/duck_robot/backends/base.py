"""後端介面：控制程式只透過這個介面跟「身體」溝通。

同一套控制程式可以接三種身體：
  - MockBackend：純軟體假身體，任何電腦都能跑（寫程式、測試用）
  - MujocoBackend：MuJoCo 物理模擬，會真的跌倒（驗證 AI 步行模型用）
  - HardwareBackend：真正的機器人（Feetech 馬達 + BNO055 IMU + 腳底開關）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from ..config import NUM_JOINTS, DuckConfig


@dataclass
class RobotState:
    q: np.ndarray = field(default_factory=lambda: np.zeros(NUM_JOINTS))  # 關節角度 rad
    dq: np.ndarray = field(default_factory=lambda: np.zeros(NUM_JOINTS))  # 關節速度 rad/s
    gyro: np.ndarray = field(default_factory=lambda: np.zeros(3))  # 角速度 rad/s
    accel: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 9.81]))  # 加速度 m/s²
    feet_contact: np.ndarray = field(default_factory=lambda: np.ones(2))  # [左, 右] 1 = 踩地
    ok: bool = True  # 這次讀取是否成功（序列埠偶爾會讀失敗）


class Backend(ABC):
    def __init__(self, config: DuckConfig):
        self.config = config

    @abstractmethod
    def read_state(self) -> RobotState: ...

    @abstractmethod
    def write_targets(self, targets: np.ndarray) -> None:
        """送出 14 個關節的目標角度（rad，JOINT_NAMES 的順序）。"""

    @abstractmethod
    def set_kps(self, kps: list[int]) -> None: ...

    @abstractmethod
    def set_torque(self, enabled: bool) -> None: ...

    def step(self, dt: float) -> None:
        """讓時間前進 dt 秒（只有模擬後端需要做事）。"""

    def close(self) -> None:
        pass
