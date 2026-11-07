"""在 MuJoCo 裡實際走路的整合測試。需要：
    DUCK_SIM_XML=.../Open_Duck_Playground/playground/open_duck_mini_v2/xmls/scene_flat_terrain.xml
    DUCK_POLICY=.../BEST_WALK_ONNX_2.onnx
沒設定就自動略過。
"""

import os

import pytest

XML = os.environ.get("DUCK_SIM_XML")
POLICY = os.environ.get("DUCK_POLICY")
pytestmark = pytest.mark.skipif(not (XML and POLICY), reason="未設定 DUCK_SIM_XML / DUCK_POLICY")


def _make(with_policy=True):
    pytest.importorskip("mujoco")
    from duck_robot.animation import load_library
    from duck_robot.backends.mujoco_sim import MujocoBackend
    from duck_robot.config import DuckConfig
    from duck_robot.controller import DuckController
    from duck_robot.policy import OnnxPolicy, WalkController

    cfg = DuckConfig()
    be = MujocoBackend(cfg, XML)
    walk = WalkController(cfg, OnnxPolicy(POLICY)) if with_policy else None
    return DuckController(be, cfg, load_library(), walk), be


def _run(c, seconds):
    for _ in range(int(seconds * 50)):
        c.tick()


def test_walks_forward_without_falling():
    c, be = _make()
    c.submit({"action": "stand"})
    _run(c, 2)
    x0 = be.base_position()[0]
    c.submit({"action": "walk", "vx": 0.15, "duration": 6})
    _run(c, 7)
    assert c.mode == "stand", c.last_error
    assert be.base_position()[0] - x0 > 0.3


@pytest.mark.parametrize("name", ["nod", "shake", "look_around", "crouch", "happy", "dance"])
def test_animation_keeps_balance(name):
    c, be = _make(with_policy=False)
    c.submit({"action": "stand"})
    _run(c, 2)
    c.submit({"action": "play", "name": name})
    _run(c, c.animations[name].duration + 1)
    assert c.mode == "stand", c.last_error
