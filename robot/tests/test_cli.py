import json

import pytest

from duck_robot import cli
from duck_robot.config import JOINT_NAMES, DuckConfig


class FakeBus:
    """模擬 14 顆馬達：設定目標就立刻到位；放鬆時可以被「手」轉動。"""

    def __init__(self):
        self.pos = {}
        self.torque = set()
        self.hand = {}  # 放鬆時手把馬達轉到的位置

    def set_kp(self, ids_kps):
        pass

    def set_goal_positions(self, ids_rads):
        for i, r in ids_rads.items():
            if i in self.torque or not self.torque:
                self.pos[i] = r

    def set_torque(self, ids, enable):
        for i in ids:
            if enable:
                self.torque.add(i)
            else:
                self.torque.discard(i)
                if i in self.hand:
                    self.pos[i] = self.hand[i]

    def read_positions_and_speeds(self, ids):
        return [self.pos.get(i, 0.0) for i in ids], [0.0] * len(ids)


def test_calibrate_measures_offset(tmp_path, monkeypatch):
    cfg_path = tmp_path / "duck.json"
    DuckConfig().save(cfg_path)
    bus = FakeBus()
    knee_id = DuckConfig().motor_ids["left_knee"]
    bus.hand[knee_id] = 0.12  # 使用者把膝蓋轉到 0.12 rad 才對準零點刻度
    monkeypatch.setattr(cli, "_bus", lambda args: bus)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    assert cli.main(["calibrate", "--config", str(cfg_path), "--joint", "left_knee"]) == 0
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert saved["joint_offsets"]["left_knee"] == pytest.approx(0.12)
    assert all(v == 0 for k, v in saved["joint_offsets"].items() if k != "left_knee")
    assert not bus.torque  # 結束後馬達放鬆
    assert DuckConfig.load(cfg_path).joint_offsets["left_knee"] == pytest.approx(0.12)


def test_run_hw_requires_config(capsys):
    assert cli.main(["run", "--backend", "hw"]) == 1
    assert "--config" in capsys.readouterr().out


def test_animations_listing(capsys):
    assert cli.main(["animations"]) == 0
    out = capsys.readouterr().out
    assert "dance" in out and "nod" in out


def test_config_rejects_unknown_joint(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"joint_offsets": {"tail": 1}}), encoding="utf-8")
    with pytest.raises(ValueError):
        DuckConfig.load(p)
    assert len(JOINT_NAMES) == 14
