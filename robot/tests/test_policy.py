import numpy as np
import pytest

from duck_robot.backends.base import RobotState
from duck_robot.config import NUM_JOINTS, DuckConfig
from duck_robot.policy import OBS_SIZE, WalkController


def test_observation_layout():
    cfg = DuckConfig()
    w = WalkController(cfg, lambda obs: np.ones(NUM_JOINTS))
    state = RobotState(q=np.array(cfg.init_pose_array) + 0.1, dq=np.full(NUM_JOINTS, 2.0),
                       gyro=np.array([1.0, 2.0, 3.0]), accel=np.array([4.0, 5.0, 6.0]),
                       feet_contact=np.array([1.0, 0.0]))
    cmds = np.array([0.1, 0.0, 0.5, 0, 0, 0, 0])
    obs = w.build_obs(state, cmds)
    assert obs.shape == (OBS_SIZE,)
    assert list(obs[:6]) == [1, 2, 3, 4, 5, 6]
    assert np.allclose(obs[6:13], cmds)
    assert np.allclose(obs[13:27], 0.1)
    assert np.allclose(obs[27:41], 0.1)  # 2.0 × 0.05
    assert np.allclose(obs[97:99], [1, 0])
    assert np.allclose(obs[99:101], [1, 0])  # 相位 0 → cos=1, sin=0


def test_action_history_and_velocity_limit():
    cfg = DuckConfig()
    w = WalkController(cfg, lambda obs: np.full(NUM_JOINTS, 10.0))  # 故意給超大動作
    state = RobotState(q=np.array(cfg.init_pose_array))
    t = w.step(state, np.zeros(7))
    max_step = cfg.max_motor_velocity / cfg.control_freq
    assert np.allclose(t - cfg.init_pose_array, max_step)
    w.step(state, np.zeros(7))
    obs = w.build_obs(state, np.zeros(7))
    assert np.allclose(obs[41:55], 10.0) and np.allclose(obs[55:69], 10.0)
    assert np.allclose(obs[69:83], 0.0)


def test_onnx_policy_shape(tmp_path):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    from duck_robot.policy import OnnxPolicy

    w = helper.make_tensor("w", TensorProto.FLOAT, [OBS_SIZE, NUM_JOINTS], [0.0] * (OBS_SIZE * NUM_JOINTS))
    graph = helper.make_graph(
        [helper.make_node("MatMul", ["obs", "w"], ["actions"])], "g",
        [helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, OBS_SIZE])],
        [helper.make_tensor_value_info("actions", TensorProto.FLOAT, [1, NUM_JOINTS])], [w])
    path = tmp_path / "p.onnx"
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8  # 讓舊版 onnxruntime 也讀得懂
    onnx.save(model, path)
    assert OnnxPolicy(str(path))(np.zeros(OBS_SIZE)).shape == (NUM_JOINTS,)
