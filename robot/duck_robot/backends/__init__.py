from __future__ import annotations

from ..config import DuckConfig
from .base import Backend, RobotState


def make_backend(kind: str, config: DuckConfig, sim_xml: str | None = None, viewer: bool = False) -> Backend:
    """依名稱建立後端：mock / sim / hw。需要的套件只在用到時才 import。"""
    if kind == "mock":
        from .mock import MockBackend

        return MockBackend(config)
    if kind == "sim":
        if not sim_xml:
            raise ValueError("sim 後端需要 --sim-xml（Open Duck Playground 的 scene_flat_terrain.xml）")
        from .mujoco_sim import MujocoBackend

        return MujocoBackend(config, sim_xml, viewer=viewer)
    if kind == "hw":
        from .hardware import HardwareBackend

        return HardwareBackend(config)
    raise ValueError(f"不認得的後端：{kind}（可用 mock / sim / hw）")


__all__ = ["Backend", "RobotState", "make_backend"]
