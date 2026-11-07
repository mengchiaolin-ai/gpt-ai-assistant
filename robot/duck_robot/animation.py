"""關鍵影格動畫：用 JSON 檔寫動作，不用碰 AI。

動畫檔格式（放在 duck_robot/animations/ 或用 --anim-dir 指定資料夾）：

    {
      "name": "nod",
      "description": "點頭",
      "keyframes": [
        {"t": 0.0, "pose": {}},
        {"t": 0.3, "pose": {"head_pitch": 0.35}},
        {"t": 0.6, "pose": {"head_pitch": -0.1}},
        {"t": 0.9, "pose": {}}
      ]
    }

- t：秒數，必須遞增
- pose：關節「相對站姿」的偏移量（弧度）。沒寫到的關節 = 0 = 站姿
- 特殊鍵 "crouch"：蹲下的深度（0~0.5），會自動換算成髖、膝、踝三個關節，
  讓兩腳保持踩平、重心不跑掉
影格之間用 smoothstep（緩入緩出）內插，動作比較自然。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np

from .config import JOINT_NAMES, NUM_JOINTS

BUILTIN_DIR = Path(__file__).parent / "animations"
_INDEX = {n: i for i, n in enumerate(JOINT_NAMES)}


def crouch_offsets(depth: float) -> Dict[str, float]:
    """蹲下：膝蓋多彎 2d、髖和踝各補 d，讓腳掌保持水平、重心留在腳上。

    注意左右髖 pitch 的方向是鏡像的。正負號是在 MuJoCo 模擬裡實測出來的：
    d = 0.3 時機身降低約 2 cm，而且保持直立。
    """
    d = float(np.clip(depth, 0.0, 0.5))
    return {
        "left_hip_pitch": d,
        "right_hip_pitch": -d,
        "left_knee": 2 * d,
        "right_knee": 2 * d,
        "left_ankle": -d,
        "right_ankle": -d,
    }


def pose_to_offsets(pose: Dict[str, float]) -> np.ndarray:
    out = np.zeros(NUM_JOINTS)
    for key, value in pose.items():
        if key == "crouch":
            for name, v in crouch_offsets(value).items():
                out[_INDEX[name]] += v
        elif key in _INDEX:
            out[_INDEX[key]] += float(value)
        else:
            raise ValueError(f"動畫裡有不認得的關節：{key}")
    return out


def smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


@dataclass
class Animation:
    name: str
    description: str
    times: List[float]
    offsets: List[np.ndarray]

    @property
    def duration(self) -> float:
        return self.times[-1]

    def sample(self, t: float) -> np.ndarray:
        """取得 t 秒時的關節偏移量。"""
        if t <= self.times[0]:
            return self.offsets[0].copy()
        if t >= self.times[-1]:
            return self.offsets[-1].copy()
        k = int(np.searchsorted(self.times, t, side="right")) - 1
        t0, t1 = self.times[k], self.times[k + 1]
        s = smoothstep((t - t0) / (t1 - t0))
        return self.offsets[k] + s * (self.offsets[k + 1] - self.offsets[k])

    @classmethod
    def from_dict(cls, data: dict) -> "Animation":
        frames = data.get("keyframes") or []
        if len(frames) < 2:
            raise ValueError(f"動畫 {data.get('name')} 至少要兩個影格")
        times = [float(f["t"]) for f in frames]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError(f"動畫 {data.get('name')} 的 t 必須嚴格遞增")
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            times=times,
            offsets=[pose_to_offsets(f.get("pose", {})) for f in frames],
        )

    @classmethod
    def load(cls, path: str | Path) -> "Animation":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_library(*dirs: str | Path) -> Dict[str, Animation]:
    """載入內建動畫，再載入使用者資料夾（同名會覆蓋內建）。"""
    library: Dict[str, Animation] = {}
    for d in (BUILTIN_DIR, *dirs):
        if d is None:
            continue
        for path in sorted(Path(d).glob("*.json")):
            anim = Animation.load(path)
            library[anim.name] = anim
    return library
