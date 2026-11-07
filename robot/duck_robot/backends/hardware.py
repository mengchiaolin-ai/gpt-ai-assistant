"""真實機器人：Feetech STS3215 ×14 + BNO055 IMU + 兩個腳底微動開關。

只在 Raspberry Pi 上執行。需要的套件：
    pip install pyserial adafruit-circuitpython-bno055 adafruit-blinka
"""

from __future__ import annotations

import threading
import time

import numpy as np

from ..config import JOINT_NAMES, DuckConfig
from ..feetech import FeetechBus, FeetechError
from .base import Backend, RobotState


class Bno055Reader:
    """在背景執行緒以固定頻率讀 IMU，主迴圈拿最新一筆就好，不會被 I²C 卡住。"""

    def __init__(self, upside_down: bool, freq: float = 50.0):
        import adafruit_bno055
        import board
        import busio

        i2c = busio.I2C(board.SCL, board.SDA)
        self.imu = adafruit_bno055.BNO055_I2C(i2c)
        self.imu.mode = adafruit_bno055.NDOF_MODE
        neg, pos = adafruit_bno055.AXIS_REMAP_NEGATIVE, adafruit_bno055.AXIS_REMAP_POSITIVE
        x, y, z = adafruit_bno055.AXIS_REMAP_X, adafruit_bno055.AXIS_REMAP_Y, adafruit_bno055.AXIS_REMAP_Z
        # 軸向重新對應，讓 IMU 座標和模擬模型一致（跟 Open Duck Mini 的安裝方向相同）
        self.imu.axis_remap = (y, x, z, neg, neg, neg) if upside_down else (y, x, z, neg, pos, pos)

        self.period = 1.0 / freq
        self.gyro = np.zeros(3)
        self.accel = np.array([0.0, 0.0, 9.81])
        self._lock = threading.Lock()
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while self._running:
            t0 = time.monotonic()
            try:
                gyro, accel = self.imu.gyro, self.imu.acceleration
                if None not in gyro and None not in accel:
                    with self._lock:
                        self.gyro = np.array(gyro, dtype=float)
                        self.accel = np.array(accel, dtype=float)
            except (OSError, RuntimeError):
                pass  # I²C 偶爾出錯，跳過這一筆
            time.sleep(max(0.0, self.period - (time.monotonic() - t0)))

    def latest(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            return self.gyro.copy(), self.accel.copy()

    def stop(self) -> None:
        self._running = False


class FeetSwitches:
    def __init__(self, left_pin: int, right_pin: int):
        import board
        import digitalio

        self.pins = []
        for pin in (left_pin, right_pin):
            io = digitalio.DigitalInOut(getattr(board, f"D{pin}"))
            io.direction = digitalio.Direction.INPUT
            io.pull = digitalio.Pull.UP  # 開關另一端接 GND，踩下 = 低電位
            self.pins.append(io)

    def read(self) -> np.ndarray:
        return np.array([0.0 if p.value else 1.0 for p in self.pins])


class HardwareBackend(Backend):

    def __init__(self, config: DuckConfig, bus: FeetechBus | None = None, imu=None, feet=None):
        super().__init__(config)
        self.bus = bus or FeetechBus(config.serial_port, config.baudrate)
        self.ids = [config.motor_ids[n] for n in JOINT_NAMES]
        self.offsets = np.array([config.joint_offsets[n] for n in JOINT_NAMES])
        self.imu = imu if imu is not None else Bno055Reader(config.imu_upside_down, config.control_freq)
        self.feet = feet if feet is not None else FeetSwitches(config.left_foot_pin, config.right_foot_pin)
        self._last = RobotState(q=np.array(config.init_pose_array))

    def read_state(self) -> RobotState:
        gyro, accel = self.imu.latest()
        try:
            q, dq = self.bus.read_positions_and_speeds(self.ids)
        except FeetechError:
            # 讀失敗就沿用上一筆，並標記 ok=False，讓控制迴圈決定要不要略過
            stale = self._last
            return RobotState(q=stale.q, dq=stale.dq, gyro=gyro, accel=accel,
                              feet_contact=self.feet.read(), ok=False)
        state = RobotState(
            q=np.array(q) - self.offsets,
            dq=np.array(dq),
            gyro=gyro,
            accel=accel,
            feet_contact=self.feet.read(),
        )
        self._last = state
        return state

    def write_targets(self, targets: np.ndarray) -> None:
        raw = np.asarray(targets) + self.offsets
        self.bus.set_goal_positions(dict(zip(self.ids, raw.tolist())))

    def set_kps(self, kps: list[int]) -> None:
        self.bus.set_kp(dict(zip(self.ids, kps)))

    def set_torque(self, enabled: bool) -> None:
        self.bus.set_torque(self.ids, enabled)

    def close(self) -> None:
        try:
            self.set_torque(False)
        finally:
            if hasattr(self.imu, "stop"):
                self.imu.stop()
            self.bus.close()
