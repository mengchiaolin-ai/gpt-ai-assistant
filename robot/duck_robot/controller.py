"""主控制迴圈（50 Hz）：狀態機 + 安全保護。

狀態：
    off        馬達不出力（可以用手扳動）
    stand      站好不動，頭可以轉
    walk       AI 步行模型接手雙腳
    animation  播放關鍵影格動畫
    fallen     偵測到跌倒 → 馬達變軟，保護齒輪；送 "stand" 指令才會重新站起

所有外部輸入（HTTP、LINE、手把）都轉成同一種 dict 指令，呼叫 submit()：
    {"action": "walk", "vx": 0.1, "vy": 0, "wz": 0, "duration": 2}
    {"action": "stop"}
    {"action": "head", "head_yaw": 0.5, "neck_pitch": 0.2}
    {"action": "play", "name": "nod"}
    {"action": "stand"}
    {"action": "torque", "enabled": false}
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, Optional

import numpy as np

from .animation import Animation
from .backends.base import Backend, RobotState
from .config import HEAD_SLICE, JOINT_NAMES, DuckConfig
from .policy import WalkController, clamp_commands

HEAD_KEYS = ["neck_pitch", "head_pitch", "head_yaw", "head_roll"]
BLEND_TIME = 0.4  # 切換動作時的平滑過渡秒數
TURN_ON_TIME = 1.0


class CommandError(ValueError):
    pass


class DuckController:
    def __init__(
        self,
        backend: Backend,
        config: DuckConfig,
        animations: Dict[str, Animation],
        walk: Optional[WalkController] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.backend = backend
        self.config = config
        self.animations = animations
        self.walk = walk
        self.clock = clock
        self.dt = 1.0 / config.control_freq
        self.init_pose = np.array(config.init_pose_array)
        self.lower = np.array(config.lower_limits)
        self.upper = np.array(config.upper_limits)

        self._lock = threading.Lock()
        self.mode = "off"
        self.sim_time = 0.0
        self.velocity = np.zeros(3)  # vx, vy, wz
        self.head = np.zeros(4)
        self.walk_until: Optional[float] = None
        self.anim: Optional[Animation] = None
        self.anim_start = 0.0
        self.targets = self.init_pose.copy()
        self._blend_from: Optional[np.ndarray] = None
        self._blend_start = 0.0
        self._blend_len = BLEND_TIME
        self.state = RobotState(q=self.init_pose.copy())
        self.tilt_deg = 0.0
        self._kp_restore_at: Optional[float] = None
        self.loop_hz = 0.0
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------ 指令
    def submit(self, cmd: dict) -> dict:
        """執行一個指令（執行緒安全），回傳目前狀態。指令格式錯誤會丟 CommandError。"""
        action = cmd.get("action")
        with self._lock:
            if action == "walk":
                if self.walk is None:
                    raise CommandError("沒有載入步行模型，請用 --policy 指定 ONNX 檔")
                if self.mode in ("off", "fallen"):
                    raise CommandError(f"目前是 {self.mode} 狀態，請先送 stand")
                self.velocity = np.array(clamp_commands(
                    _num(cmd, "vx"), _num(cmd, "vy"), _num(cmd, "wz")))
                duration = cmd.get("duration")
                self.walk_until = self.sim_time + float(duration) if duration else None
                if self.mode != "walk":
                    self.walk.reset()
                    self.anim = None
                    self._set_mode("walk", blend=False)
            elif action == "stop":
                self.velocity[:] = 0.0
                if self.mode in ("walk", "animation"):
                    self._set_mode("stand")
            elif action == "head":
                for i, key in enumerate(HEAD_KEYS):
                    if key in cmd:
                        self.head[i] = _num(cmd, key)
            elif action == "play":
                name = cmd.get("name")
                if name not in self.animations:
                    raise CommandError(f"沒有這個動畫：{name}（可用：{', '.join(sorted(self.animations))}）")
                if self.mode in ("off", "fallen"):
                    raise CommandError(f"目前是 {self.mode} 狀態，請先送 stand")
                self.anim = self.animations[name]
                self.anim_start = self.sim_time
                self._set_mode("animation")
            elif action == "stand":
                self.velocity[:] = 0.0
                self.anim = None
                if self.mode in ("off", "fallen"):
                    self._turn_on()
                else:
                    self._set_mode("stand")
            elif action == "torque":
                if cmd.get("enabled", True):
                    self._turn_on()
                else:
                    self.backend.set_torque(False)
                    self.mode = "off"
            else:
                raise CommandError(f"不認得的指令：{action}")
            return self._status()

    def status(self) -> dict:
        with self._lock:
            return self._status()

    def _status(self) -> dict:
        return {
            "mode": self.mode,
            "velocity": {"vx": self.velocity[0], "vy": self.velocity[1], "wz": self.velocity[2]},
            "head": dict(zip(HEAD_KEYS, self.head.tolist())),
            "animation": self.anim.name if self.anim else None,
            "animations": sorted(self.animations),
            "walk_available": self.walk is not None,
            "tilt_deg": round(self.tilt_deg, 1),
            "feet_contact": self.state.feet_contact.tolist(),
            "loop_hz": round(self.loop_hz, 1),
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------ 狀態切換
    def _set_mode(self, mode: str, blend: bool = True) -> None:
        if blend:
            self._start_blend(BLEND_TIME)
        self.mode = mode

    def _start_blend(self, seconds: float) -> None:
        self._blend_from = self.targets.copy()
        self._blend_start = self.sim_time
        self._blend_len = seconds

    def _turn_on(self) -> None:
        """先用軟增益慢慢回到站姿，再切到正常增益，避免開機時猛然一抽。"""
        self.backend.set_kps([self.config.soft_kp] * len(JOINT_NAMES))
        self.backend.set_torque(True)
        self.targets = self.state.q.copy()
        self._start_blend(TURN_ON_TIME)
        self._kp_restore_at = self.sim_time + TURN_ON_TIME
        self.mode = "stand"

    # ------------------------------------------------------------ 主迴圈
    def tick(self) -> np.ndarray:
        """執行一個控制週期，回傳送出的目標角度。"""
        state = self.backend.read_state()
        with self._lock:
            if state.ok:
                self.state = state
            # 低通濾波：走路時腳落地的瞬間衝擊不會被誤判成跌倒
            self.tilt_deg += 0.2 * (tilt_from_accel(self.state.accel) - self.tilt_deg)
            if self._kp_restore_at is not None and self.sim_time >= self._kp_restore_at:
                self.backend.set_kps(self.config.kps())
                self._kp_restore_at = None

            if self.mode not in ("off", "fallen") and self.tilt_deg > self.config.fall_tilt_deg:
                self._on_fall()

            targets = self._compute_targets()
            if targets is not None:
                targets = np.clip(targets, self.lower, self.upper)
                self.targets = targets
                self.backend.write_targets(targets)

        self.backend.step(self.dt)
        self.sim_time += self.dt
        return self.targets

    def _compute_targets(self) -> Optional[np.ndarray]:
        if self.mode == "off":
            return None
        if self.mode == "fallen":
            return self.targets  # 維持原姿勢、軟增益

        if self.mode == "walk":
            if self.walk_until is not None and self.sim_time >= self.walk_until:
                self.velocity[:] = 0.0
                self.walk_until = None
                self._set_mode("stand")
                return self._stand_targets()
            commands = np.concatenate([self.velocity, self.head])
            t = self.walk.step(self.state, commands)
            t[HEAD_SLICE] += self.head
            return t

        if self.mode == "animation":
            elapsed = self.sim_time - self.anim_start
            if elapsed >= self.anim.duration:
                self.anim = None
                self.mode = "stand"
                return self._stand_targets()
            pose = self.init_pose + self.anim.sample(elapsed)
            pose[HEAD_SLICE] += self.head
            return self._blended(pose)

        return self._stand_targets()

    def _stand_targets(self) -> np.ndarray:
        pose = self.init_pose.copy()
        pose[HEAD_SLICE] += self.head
        return self._blended(pose)

    def _blended(self, goal: np.ndarray) -> np.ndarray:
        if self._blend_from is None:
            return goal
        s = (self.sim_time - self._blend_start) / self._blend_len
        if s >= 1.0:
            self._blend_from = None
            return goal
        s = s * s * (3 - 2 * s)
        return self._blend_from + s * (goal - self._blend_from)

    def _on_fall(self) -> None:
        self.backend.set_kps([self.config.soft_kp] * len(JOINT_NAMES))
        self.velocity[:] = 0.0
        self.anim = None
        self.mode = "fallen"
        self.last_error = f"偵測到跌倒（傾斜 {self.tilt_deg:.0f}°），馬達已放軟"

    def run(self, stop_event: Optional[threading.Event] = None, realtime: bool = True) -> None:
        stop_event = stop_event or threading.Event()
        next_t = self.clock()
        last_report, ticks = self.clock(), 0
        while not stop_event.is_set():
            self.tick()
            ticks += 1
            now = self.clock()
            if now - last_report >= 1.0:
                self.loop_hz = ticks / (now - last_report)
                last_report, ticks = now, 0
            if realtime:
                next_t += self.dt
                delay = next_t - self.clock()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = self.clock()  # 落後太多就不追了，避免連續爆衝


def tilt_from_accel(accel: np.ndarray) -> float:
    """機身傾斜角（度）：重力方向和機身 z 軸的夾角。"""
    norm = float(np.linalg.norm(accel))
    if norm < 1e-6:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, accel[2] / norm))))


def _num(cmd: dict, key: str) -> float:
    value = cmd.get(key, 0.0)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise CommandError(f"{key} 必須是數字") from None
    if not math.isfinite(value):
        raise CommandError(f"{key} 必須是有限的數字")
    return value
