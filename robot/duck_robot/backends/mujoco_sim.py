"""MuJoCo 物理模擬身體。

需要 Open Duck Mini v2 的模擬模型（Apache-2.0），先下載：
    git clone https://github.com/apirrone/Open_Duck_Playground
然後把 scene 檔路徑傳給 --sim-xml，例如：
    Open_Duck_Playground/playground/open_duck_mini_v2/xmls/scene_flat_terrain.xml
"""

from __future__ import annotations

import numpy as np

from ..config import JOINT_NAMES, DuckConfig
from .base import Backend, RobotState


class MujocoBackend(Backend):
    SIM_DT = 0.002
    # 原專案的模擬推論在加速度計 x 軸加了 1.3 的偏移（對齊真實 IMU），這裡照做
    ACCEL_X_BIAS = 1.3

    def __init__(self, config: DuckConfig, xml_path: str, viewer: bool = False):
        super().__init__(config)
        import mujoco

        self.mj = mujoco
        self.model = mujoco.MjModel.from_xml_path(xml_path)
        self.model.opt.timestep = self.SIM_DT
        self.data = mujoco.MjData(self.model)

        names = [self.model.actuator(i).name for i in range(self.model.nu)]
        if names != JOINT_NAMES:
            raise ValueError(f"模擬模型的致動器順序不符：{names}")

        self.qpos_addr = [self.model.joint(n).qposadr[0] for n in JOINT_NAMES]
        self.qvel_addr = [self.model.joint(n).dofadr[0] for n in JOINT_NAMES]
        self._gyro = self._sensor_slice("gyro")
        self._acc = self._sensor_slice("accelerometer")
        self._floor = self.model.body("floor").id
        self._feet = [self.model.body("foot_assembly").id, self.model.body("foot_assembly_2").id]
        self._gain = self.model.actuator_gainprm[:, 0].copy()
        self._bias = self.model.actuator_biasprm[:, 1].copy()

        key = self.model.keyframe("home")
        self.data.qpos[:] = key.qpos
        self.data.ctrl[:] = key.ctrl
        mujoco.mj_forward(self.model, self.data)

        self.viewer = None
        if viewer:
            import mujoco.viewer

            self.viewer = mujoco.viewer.launch_passive(self.model, self.data)

    def _sensor_slice(self, name: str) -> slice:
        sid = self.model.sensor(name).id
        adr = self.model.sensor_adr[sid]
        return slice(adr, adr + self.model.sensor_dim[sid])

    def _foot_contacts(self) -> np.ndarray:
        out = np.zeros(2)
        for c in self.data.contact[: self.data.ncon]:
            bodies = {self.model.geom_bodyid[c.geom1], self.model.geom_bodyid[c.geom2]}
            if self._floor in bodies:
                for i, foot in enumerate(self._feet):
                    if foot in bodies:
                        out[i] = 1.0
        return out

    def read_state(self) -> RobotState:
        acc = self.data.sensordata[self._acc].copy()
        acc[0] += self.ACCEL_X_BIAS
        return RobotState(
            q=self.data.qpos[self.qpos_addr].copy(),
            dq=self.data.qvel[self.qvel_addr].copy(),
            gyro=self.data.sensordata[self._gyro].copy(),
            accel=acc,
            feet_contact=self._foot_contacts(),
        )

    def write_targets(self, targets: np.ndarray) -> None:
        self.data.ctrl[:] = targets

    def set_kps(self, kps: list[int]) -> None:
        pass  # 模擬模型的增益已經用 BAM 對真實 STS3215 辨識過，保持不變

    def set_torque(self, enabled: bool) -> None:
        scale = 1.0 if enabled else 0.0
        self.model.actuator_gainprm[:, 0] = self._gain * scale
        self.model.actuator_biasprm[:, 1] = self._bias * scale

    def step(self, dt: float) -> None:
        for _ in range(max(1, int(round(dt / self.SIM_DT)))):
            self.mj.mj_step(self.model, self.data)
        if self.viewer is not None:
            self.viewer.sync()

    def base_position(self) -> np.ndarray:
        return self.data.qpos[:3].copy()

    def close(self) -> None:
        if self.viewer is not None:
            self.viewer.close()
