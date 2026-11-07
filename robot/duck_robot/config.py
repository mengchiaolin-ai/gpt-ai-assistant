"""機器人設定：關節名稱、馬達 ID、站立姿勢、校正偏移量。

關節順序（共 14 個）必須和步行 AI 模型（ONNX）訓練時的順序完全一樣，
這裡沿用 Open Duck Mini v2 的順序，所以可以直接使用它公開的步行模型。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# 順序很重要！不要隨意調整。
JOINT_NAMES: List[str] = [
    "left_hip_yaw",
    "left_hip_roll",
    "left_hip_pitch",
    "left_knee",
    "left_ankle",
    "neck_pitch",
    "head_pitch",
    "head_yaw",
    "head_roll",
    "right_hip_yaw",
    "right_hip_roll",
    "right_hip_pitch",
    "right_knee",
    "right_ankle",
]

NUM_JOINTS = len(JOINT_NAMES)
HEAD_SLICE = slice(5, 9)  # neck_pitch, head_pitch, head_yaw, head_roll
LEG_INDICES = [0, 1, 2, 3, 4, 9, 10, 11, 12, 13]

# 馬達 ID：十位數 1 = 右腳、2 = 左腳、3 = 頭。
DEFAULT_MOTOR_IDS: Dict[str, int] = {
    "left_hip_yaw": 20,
    "left_hip_roll": 21,
    "left_hip_pitch": 22,
    "left_knee": 23,
    "left_ankle": 24,
    "neck_pitch": 30,
    "head_pitch": 31,
    "head_yaw": 32,
    "head_roll": 33,
    "right_hip_yaw": 10,
    "right_hip_roll": 11,
    "right_hip_pitch": 12,
    "right_knee": 13,
    "right_ankle": 14,
}

# 站立姿勢（弧度），也是 AI 模型的「零點」。
DEFAULT_INIT_POSE: Dict[str, float] = {
    "left_hip_yaw": 0.002,
    "left_hip_roll": 0.053,
    "left_hip_pitch": -0.63,
    "left_knee": 1.368,
    "left_ankle": -0.784,
    "neck_pitch": 0.0,
    "head_pitch": 0.0,
    "head_yaw": 0.0,
    "head_roll": 0.0,
    "right_hip_yaw": -0.003,
    "right_hip_roll": -0.065,
    "right_hip_pitch": 0.635,
    "right_knee": 1.379,
    "right_ankle": -0.796,
}

# 關節安全範圍（弧度），取自模擬模型的 ctrlrange，避免撞壞零件。
DEFAULT_JOINT_LIMITS: Dict[str, List[float]] = {
    "left_hip_yaw": [-0.524, 0.524],
    "left_hip_roll": [-0.436, 0.436],
    "left_hip_pitch": [-1.222, 0.524],
    "left_knee": [-1.571, 1.571],
    "left_ankle": [-1.571, 1.571],
    "neck_pitch": [-0.349, 1.134],
    "head_pitch": [-0.785, 0.785],
    "head_yaw": [-2.793, 2.793],
    "head_roll": [-0.524, 0.524],
    "right_hip_yaw": [-0.524, 0.524],
    "right_hip_roll": [-0.436, 0.436],
    "right_hip_pitch": [-0.524, 1.222],
    "right_knee": [-1.571, 1.571],
    "right_ankle": [-1.571, 1.571],
}


@dataclass
class DuckConfig:
    serial_port: str = "/dev/ttyACM0"
    baudrate: int = 1_000_000
    control_freq: float = 50.0
    motor_ids: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_MOTOR_IDS))
    init_pose: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_INIT_POSE))
    joint_offsets: Dict[str, float] = field(default_factory=lambda: {n: 0.0 for n in JOINT_NAMES})
    joint_limits: Dict[str, List[float]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_JOINT_LIMITS.items()})
    # 馬達 P 增益（Feetech 內部 PID 的 P）。腿要硬、頭要軟。
    leg_kp: int = 30
    head_kp: int = 8
    soft_kp: int = 2  # 開機/跌倒時用的「軟」增益，保護馬達
    max_motor_velocity: float = 5.24  # rad/s，STS3215 約 50 rpm
    imu_upside_down: bool = False
    left_foot_pin: int = 22  # BCM GPIO
    right_foot_pin: int = 27
    fall_tilt_deg: float = 55.0  # 傾斜超過這個角度視為跌倒
    phase_steps: int = 27  # 步態週期 = 0.54 s × 50 Hz（與參考模型相同）
    action_scale: float = 0.25

    @property
    def init_pose_array(self) -> List[float]:
        return [self.init_pose[n] for n in JOINT_NAMES]

    @property
    def lower_limits(self) -> List[float]:
        return [self.joint_limits[n][0] for n in JOINT_NAMES]

    @property
    def upper_limits(self) -> List[float]:
        return [self.joint_limits[n][1] for n in JOINT_NAMES]

    def kps(self) -> List[int]:
        return [self.head_kp if 5 <= i <= 8 else self.leg_kp for i in range(NUM_JOINTS)]

    @classmethod
    def load(cls, path: Optional[str | Path]) -> "DuckConfig":
        cfg = cls()
        if path is None:
            return cfg
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for key, value in data.items():
            if key.startswith("_"):
                continue  # 允許 "_comment" 這種註解欄位
            if not hasattr(cfg, key):
                raise ValueError(f"設定檔有不認得的欄位：{key}")
            current = getattr(cfg, key)
            if isinstance(current, dict):
                unknown = set(value) - set(JOINT_NAMES)
                if unknown:
                    raise ValueError(f"{key} 裡有不認得的關節名稱：{sorted(unknown)}")
                current.update(value)
            else:
                setattr(cfg, key, value)
        return cfg

    def save(self, path: str | Path) -> None:
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
