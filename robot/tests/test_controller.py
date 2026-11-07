import numpy as np
import pytest

from duck_robot.animation import load_library
from duck_robot.backends.mock import MockBackend
from duck_robot.config import HEAD_SLICE, NUM_JOINTS, DuckConfig
from duck_robot.controller import CommandError, DuckController
from duck_robot.policy import WalkController


class ZeroPolicy:
    def __init__(self):
        self.calls = []

    def __call__(self, obs):
        self.calls.append(obs)
        return np.zeros(NUM_JOINTS)


def make(policy=None):
    cfg = DuckConfig()
    be = MockBackend(cfg)
    walk = WalkController(cfg, policy) if policy else None
    return DuckController(be, cfg, load_library(), walk), be, cfg


def run(c, seconds):
    for _ in range(int(seconds * 50)):
        c.tick()


def test_turn_on_ramps_to_stand():
    c, be, cfg = make()
    be.q[:] = 0.0  # 開機前關節在任意位置
    c.tick()
    c.submit({"action": "stand"})
    assert be.torque and be.kps == [cfg.soft_kp] * NUM_JOINTS
    run(c, 1.5)
    assert np.allclose(be.q, cfg.init_pose_array, atol=1e-3)
    assert be.kps == cfg.kps()  # 回到站姿後恢復正常增益


def test_animation_plays_and_returns_to_stand():
    c, be, cfg = make()
    c.submit({"action": "stand"})
    run(c, 1.5)
    c.submit({"action": "play", "name": "nod"})
    assert c.mode == "animation"
    run(c, 0.3)
    assert c.targets[HEAD_SLICE][1] > cfg.init_pose["head_pitch"]  # 頭有在動
    run(c, 1.5)
    assert c.mode == "stand"


def test_unknown_commands_rejected():
    c, _, _ = make()
    with pytest.raises(CommandError):
        c.submit({"action": "fly"})
    with pytest.raises(CommandError):
        c.submit({"action": "play", "name": "moonwalk"})
    c.submit({"action": "stand"})
    with pytest.raises(CommandError):
        c.submit({"action": "head", "head_yaw": float("nan")})
    with pytest.raises(CommandError):
        c.submit({"action": "walk", "vx": 0.1})  # 沒有步行模型


def test_walk_runs_policy_and_auto_stops():
    pol = ZeroPolicy()
    c, _, _ = make(pol)
    c.submit({"action": "stand"})
    run(c, 1.5)
    c.submit({"action": "walk", "vx": 9, "duration": 1})  # 9 m/s 會被夾到安全範圍
    assert c.velocity[0] == pytest.approx(0.15)
    run(c, 0.5)
    assert c.mode == "walk" and len(pol.calls) > 0
    assert pol.calls[-1][6] == pytest.approx(0.15)  # 觀測裡的 vx 指令
    run(c, 0.7)
    assert c.mode == "stand"


def test_fall_detection_softens_motors():
    c, be, cfg = make()
    c.submit({"action": "stand"})
    run(c, 1.5)
    be.tilt_accel = np.array([9.81, 0.0, 0.0])  # 躺平了
    run(c, 1)
    assert c.mode == "fallen" and be.kps == [cfg.soft_kp] * NUM_JOINTS
    with pytest.raises(CommandError):
        c.submit({"action": "play", "name": "nod"})
    be.tilt_accel = np.array([0.0, 0.0, 9.81])
    c.submit({"action": "stand"})
    assert c.mode == "stand"


def test_joint_limits_enforced():
    c, _, cfg = make()
    c.submit({"action": "stand"})
    c.submit({"action": "head", "head_yaw": 99})
    run(c, 1.5)
    assert c.targets[7] == pytest.approx(cfg.joint_limits["head_yaw"][1])


def test_torque_off():
    c, be, _ = make()
    c.submit({"action": "stand"})
    c.submit({"action": "torque", "enabled": False})
    writes = be.writes
    run(c, 0.2)
    assert not be.torque and c.mode == "off" and be.writes == writes
