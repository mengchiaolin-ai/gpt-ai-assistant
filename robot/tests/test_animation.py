import numpy as np
import pytest

from duck_robot.animation import Animation, crouch_offsets, load_library, pose_to_offsets
from duck_robot.config import JOINT_NAMES


def test_builtin_library_loads():
    lib = load_library()
    assert {"nod", "shake", "look_around", "crouch", "happy", "dance"} <= set(lib)
    for anim in lib.values():
        # 所有內建動畫都從站姿開始、回到站姿結束，才能和其他動作無縫銜接
        assert np.allclose(anim.sample(0.0), 0.0)
        assert np.allclose(anim.sample(anim.duration), 0.0)


def test_interpolation_hits_keyframes_and_eases():
    a = Animation.from_dict({"name": "t", "keyframes": [
        {"t": 0, "pose": {}}, {"t": 1, "pose": {"head_yaw": 1.0}}]})
    i = JOINT_NAMES.index("head_yaw")
    assert a.sample(0.5)[i] == pytest.approx(0.5)
    assert a.sample(0.25)[i] < 0.25  # 緩入：前段比線性慢
    assert a.sample(5)[i] == pytest.approx(1.0)


def test_crouch_expands_to_legs():
    off = pose_to_offsets({"crouch": 0.2})
    for name, v in crouch_offsets(0.2).items():
        assert off[JOINT_NAMES.index(name)] == pytest.approx(v)
    assert off[JOINT_NAMES.index("head_yaw")] == 0


def test_rejects_bad_files():
    with pytest.raises(ValueError):
        Animation.from_dict({"name": "x", "keyframes": [{"t": 0}, {"t": 0}]})
    with pytest.raises(ValueError):
        Animation.from_dict({"name": "x", "keyframes": [{"t": 0}, {"t": 1, "pose": {"tail": 1}}]})


def test_user_dir_overrides(tmp_path):
    (tmp_path / "nod.json").write_text(
        '{"name": "nod", "description": "mine", "keyframes": [{"t": 0}, {"t": 2}]}', encoding="utf-8")
    assert load_library(tmp_path)["nod"].description == "mine"
