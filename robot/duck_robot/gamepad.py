"""藍牙手把遙控（Xbox / PS 手把都可以，需要 pip install pygame）。

    左搖桿     前後、左右走
    右搖桿 X   原地轉向
    A / B / X / Y   點頭 / 搖頭 / 開心 / 跳舞
    Start      站好（跌倒後也用這個重新站起）
    Back       放鬆馬達
放開搖桿 0.5 秒後會自動停下來。
"""

from __future__ import annotations

import threading
import time

from .controller import CommandError, DuckController
from .policy import VX_RANGE, VY_RANGE, WZ_RANGE

DEADZONE = 0.15
BUTTON_ACTIONS = {
    0: {"action": "play", "name": "nod"},  # A
    1: {"action": "play", "name": "shake"},  # B
    2: {"action": "play", "name": "happy"},  # X
    3: {"action": "play", "name": "dance"},  # Y
    6: {"action": "torque", "enabled": False},  # Back
    7: {"action": "stand"},  # Start
}


def _axis(js, i: int) -> float:
    v = js.get_axis(i) if js.get_numaxes() > i else 0.0
    return 0.0 if abs(v) < DEADZONE else v


def start_gamepad(controller: DuckController, freq: float = 20.0) -> threading.Thread:
    import pygame

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        raise RuntimeError("找不到手把，請先用 bluetoothctl 配對")
    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"[gamepad] 已連線：{js.get_name()}")

    def loop():
        idle_since = None
        walking = False
        while True:
            for event in pygame.event.get():
                if event.type == pygame.JOYBUTTONDOWN and event.button in BUTTON_ACTIONS:
                    _try(controller, BUTTON_ACTIONS[event.button])
            vx = -_axis(js, 1) * VX_RANGE[1]
            vy = -_axis(js, 0) * VY_RANGE[1]
            wz = -_axis(js, 3) * WZ_RANGE[1]
            if vx or vy or wz:
                idle_since = None
                walking = _try(controller, {"action": "walk", "vx": vx, "vy": vy, "wz": wz}) or walking
            elif walking:
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since > 0.5:
                    _try(controller, {"action": "stop"})
                    walking = False
            time.sleep(1.0 / freq)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def _try(controller: DuckController, cmd: dict) -> bool:
    try:
        controller.submit(cmd)
        return True
    except CommandError as e:
        print(f"[gamepad] {e}")
        return False
