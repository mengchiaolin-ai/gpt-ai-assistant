"""強化學習步行 AI（ONNX 模型）的推論。

AI 模型本身就是一個函式：輸入 101 個數字（觀測），輸出 14 個數字（動作）。
最重要的是：觀測的「排列方式」必須和訓練時一模一樣，否則鴨子會亂踢。

觀測向量（101 維），與 Open Duck Mini v2 的 BEST_WALK_ONNX_2.onnx 相容：
    gyro                     3   IMU 角速度
    accel                    3   IMU 加速度
    commands                 7   [vx, vy, wz, neck_pitch, head_pitch, head_yaw, head_roll]
    q - init_pose           14   關節角度（相對站姿）
    dq * 0.05               14   關節速度（縮放）
    last_action             14   上一步的動作
    last_last_action        14   上上步
    last_last_last_action   14   上上上步
    motor_targets           14   上一步送出的馬達目標角度
    feet_contact             2   左右腳是否踩地
    phase                    2   步態相位 [cos, sin]
動作（14 維）：馬達目標 = init_pose + action × 0.25
"""

from __future__ import annotations

import math

import numpy as np

from .backends.base import RobotState
from .config import NUM_JOINTS, DuckConfig

OBS_SIZE = 101
DOF_VEL_SCALE = 0.05

# 參考模型訓練時的指令範圍
VX_RANGE = (-0.15, 0.15)  # m/s
VY_RANGE = (-0.2, 0.2)  # m/s
WZ_RANGE = (-1.0, 1.0)  # rad/s


class OnnxPolicy:
    def __init__(self, path: str):
        import onnxruntime as ort

        self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        size = inp.shape[-1]
        if isinstance(size, int) and size != OBS_SIZE:
            raise ValueError(f"模型輸入是 {size} 維，但本程式產生 {OBS_SIZE} 維的觀測")

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        out = self.session.run(None, {self.input_name: obs.astype(np.float32)[None, :]})
        return np.asarray(out[0][0], dtype=float)


class WalkController:
    """把感測器資料組成觀測 → 丟給 AI → 把動作換算成馬達目標角度。"""

    def __init__(self, config: DuckConfig, policy):
        self.config = config
        self.policy = policy
        self.init_pose = np.array(config.init_pose_array)
        self.dt = 1.0 / config.control_freq
        self.reset()

    def reset(self) -> None:
        self.actions = [np.zeros(NUM_JOINTS) for _ in range(3)]  # [last, last_last, last_last_last]
        self.motor_targets = self.init_pose.copy()
        self.phase_i = 0.0
        self.phase_speed = 1.0

    def phase(self) -> np.ndarray:
        a = self.phase_i / self.config.phase_steps * 2 * math.pi
        return np.array([math.cos(a), math.sin(a)])

    def build_obs(self, state: RobotState, commands: np.ndarray) -> np.ndarray:
        obs = np.concatenate([
            state.gyro,
            state.accel,
            commands,
            state.q - self.init_pose,
            state.dq * DOF_VEL_SCALE,
            *self.actions,
            self.motor_targets,
            state.feet_contact,
            self.phase(),
        ])
        assert obs.shape == (OBS_SIZE,), obs.shape
        return obs

    def step(self, state: RobotState, commands: np.ndarray) -> np.ndarray:
        """執行一步（50 Hz），回傳 14 個馬達目標角度。"""
        self.phase_i = (self.phase_i + self.phase_speed) % self.config.phase_steps
        obs = self.build_obs(state, commands)
        action = self.policy(obs)
        self.actions = [action.copy(), self.actions[0], self.actions[1]]

        targets = self.init_pose + action * self.config.action_scale
        # 限制每一步最大轉速，保護馬達、也跟訓練時的條件一致
        max_step = self.config.max_motor_velocity * self.dt
        targets = np.clip(targets, self.motor_targets - max_step, self.motor_targets + max_step)
        self.motor_targets = targets.copy()
        return targets


def clamp_commands(vx: float, vy: float, wz: float) -> tuple[float, float, float]:
    return (
        float(np.clip(vx, *VX_RANGE)),
        float(np.clip(vy, *VY_RANGE)),
        float(np.clip(wz, *WZ_RANGE)),
    )
