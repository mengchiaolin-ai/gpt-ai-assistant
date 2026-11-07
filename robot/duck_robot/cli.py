"""指令列工具：python -m duck_robot <子指令>

  run           啟動機器人（mock / sim / hw），可同時開 HTTP 遙控與手把
  scan          掃描匯流排上有哪些馬達 ID
  set-id        修改馬達 ID（一次只接一顆！）
  check-motors  檢查 14 顆馬達是否都在、電壓與溫度
  calibrate     量測每顆馬達的安裝偏移量，寫回設定檔
  animations    列出所有動畫
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

from .animation import load_library
from .config import JOINT_NAMES, DuckConfig


def cmd_run(args) -> int:
    from .backends import make_backend
    from .controller import DuckController

    if args.backend == "hw" and not args.config:
        print("真實硬體一定要用 --config 指定設定檔（裡面有校正偏移量），否則可能撞壞關節。")
        return 1
    config = DuckConfig.load(args.config)
    backend = make_backend(args.backend, config, sim_xml=args.sim_xml, viewer=args.viewer)
    walk = None
    if args.policy:
        from .policy import OnnxPolicy, WalkController

        walk = WalkController(config, OnnxPolicy(args.policy))
    controller = DuckController(backend, config, load_library(args.anim_dir), walk)

    token = args.token or os.environ.get("DUCK_TOKEN")
    if args.http:
        from .server import start_server

        host, _, port = args.http.rpartition(":")
        host = host or "0.0.0.0"
        if host not in ("127.0.0.1", "localhost") and not token:
            print("⚠️  HTTP 對外開放但沒有設定 token，同一個網路的人都能控制鴨子。建議加上 --token。")
        start_server(controller, host, int(port), token)
        print(f"🌐 遙控網頁：http://{host}:{port}/")
    if args.gamepad:
        from .gamepad import start_gamepad

        start_gamepad(controller)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    controller.submit({"action": "stand"})
    print(f"🦆 已啟動（後端：{args.backend}，步行模型：{'有' if walk else '無'}）。Ctrl+C 結束。")
    try:
        controller.run(stop, realtime=not args.fast)
    finally:
        backend.set_torque(False)
        backend.close()
        print("👋 馬達已放鬆，結束。")
    return 0


def _bus(args):
    from .feetech import FeetechBus

    return FeetechBus(args.port, args.baudrate)


def cmd_scan(args) -> int:
    bus = _bus(args)
    found = bus.scan(range(0, 254) if args.all else range(0, 40))
    print("找到的馬達 ID：", found or "（沒有，請檢查電源、接線、序列埠）")
    return 0 if found else 1


def cmd_set_id(args) -> int:
    bus = _bus(args)
    if not bus.ping(args.old):
        print(f"找不到 ID {args.old} 的馬達")
        return 1
    others = [i for i in bus.scan() if i != args.old]
    if others:
        print(f"匯流排上還有其他馬達 {others}，為了安全請一次只接一顆")
        return 1
    bus.change_id(args.old, args.new)
    ok = bus.ping(args.new)
    print(f"ID {args.old} → {args.new}：{'成功' if ok else '失敗'}")
    return 0 if ok else 1


def cmd_check_motors(args) -> int:
    config = DuckConfig.load(args.config)
    args.port = args.port or config.serial_port
    bus = _bus(args)
    bad = 0
    for name in JOINT_NAMES:
        mid = config.motor_ids[name]
        if bus.ping(mid):
            v, temp = bus.read_voltage(mid), bus.read_temperature(mid)
            warn = "  ⚠️ 電壓偏低" if v < 6.5 else ""
            print(f"✅ {name:16s} ID {mid:2d}  {v:4.1f} V  {temp:2d} °C{warn}")
        else:
            bad += 1
            print(f"❌ {name:16s} ID {mid:2d}  沒有回應")
    print("全部正常！" if not bad else f"{bad} 顆馬達沒有回應")
    return 1 if bad else 0


def cmd_calibrate(args) -> int:
    config = DuckConfig.load(args.config)
    args.port = args.port or config.serial_port
    bus = _bus(args)
    out = args.out or args.config
    if not out:
        print("請用 --config 或 --out 指定要寫入的設定檔")
        return 1
    joints = args.joint or JOINT_NAMES
    unknown = set(joints) - set(JOINT_NAMES)
    if unknown:
        print(f"不認得的關節：{sorted(unknown)}")
        return 1
    ids = {n: config.motor_ids[n] for n in JOINT_NAMES}

    def go_zero():
        # 每個關節都去「零點 + 目前的偏移量」；還沒校正的關節偏移量是 0
        bus.set_goal_positions({ids[n]: config.joint_offsets[n] for n in JOINT_NAMES})

    print("⚠️  鴨子會移動到零點姿勢，請把它吊起來或拿在手上，隨時可按 Ctrl+C 中止。")
    input("準備好按 Enter… ")
    bus.set_kp({i: config.leg_kp for i in ids.values()})
    go_zero()
    bus.set_torque(list(ids.values()), True)
    time.sleep(1.0)
    try:
        for name in joints:
            while True:
                ans = input(f"\n=== {name}（ID {ids[name]}）=== Enter 開始，s 跳過：").strip().lower()
                if ans == "s":
                    break
                config.joint_offsets[name] = 0.0
                go_zero()
                time.sleep(0.5)
                before, _ = bus.read_positions_and_speeds([ids[name]])
                bus.set_torque([ids[name]], False)
                input(f"{name} 已放鬆。用手把它轉到組裝指南的零點刻度，按 Enter… ")
                after, _ = bus.read_positions_and_speeds([ids[name]])
                offset = round(after[0] - before[0], 4)
                flag = "  ⚠️ 超過 0.3 rad，可能是舵盤裝錯一格" if abs(offset) > 0.3 else ""
                print(f"偏移量 {offset:+.3f} rad{flag}")
                config.joint_offsets[name] = offset
                bus.set_torque([ids[name]], True)
                go_zero()
                if input("馬達已移到校正後的零點，看起來對嗎？(Y/n)：").strip().lower() in ("", "y"):
                    break
                config.joint_offsets[name] = 0.0
    finally:
        bus.set_torque(list(ids.values()), False)
    config.save(out)
    print(f"已寫入 {out}")
    return 0


def cmd_animations(args) -> int:
    for name, anim in sorted(load_library(args.anim_dir).items()):
        print(f"{name:12s} {anim.duration:4.1f}s  {anim.description}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="duck_robot", description="DIY 雙足鴨子機器人控制程式")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="啟動機器人")
    r.add_argument("--backend", choices=["mock", "sim", "hw"], default="mock")
    r.add_argument("--config", help="設定檔 JSON（hw 必填，見 config/duck_config.example.json）")
    r.add_argument("--policy", help="步行 AI 模型（ONNX）")
    r.add_argument("--sim-xml", help="MuJoCo 場景檔（sim 後端用）")
    r.add_argument("--viewer", action="store_true", help="開啟 MuJoCo 3D 視窗")
    r.add_argument("--http", metavar="HOST:PORT", help="開啟 HTTP 遙控，例如 0.0.0.0:8000")
    r.add_argument("--token", help="HTTP 驗證 token（也可用環境變數 DUCK_TOKEN）")
    r.add_argument("--gamepad", action="store_true", help="啟用藍牙手把")
    r.add_argument("--anim-dir", help="自訂動畫資料夾")
    r.add_argument("--fast", action="store_true", help="模擬時不等待真實時間（跑得比較快）")
    r.set_defaults(func=cmd_run)

    def bus_args(sp, port_default="/dev/ttyACM0"):
        sp.add_argument("--port", default=port_default)
        sp.add_argument("--baudrate", type=int, default=1_000_000)

    s = sub.add_parser("scan", help="掃描馬達 ID")
    bus_args(s)
    s.add_argument("--all", action="store_true", help="掃 0~253（較慢）")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("set-id", help="修改馬達 ID")
    bus_args(s)
    s.add_argument("--old", type=int, default=1, help="目前的 ID（新馬達是 1）")
    s.add_argument("--new", type=int, required=True)
    s.set_defaults(func=cmd_set_id)

    s = sub.add_parser("check-motors", help="檢查所有馬達")
    bus_args(s, port_default=None)
    s.add_argument("--config")
    s.set_defaults(func=cmd_check_motors)

    s = sub.add_parser("calibrate", help="量測安裝偏移量")
    bus_args(s, port_default=None)
    s.add_argument("--config")
    s.add_argument("--out", help="輸出設定檔（預設覆蓋 --config）")
    s.add_argument("--joint", action="append", help="只校正這個關節（可重複）")
    s.set_defaults(func=cmd_calibrate)

    s = sub.add_parser("animations", help="列出動畫")
    s.add_argument("--anim-dir")
    s.set_defaults(func=cmd_animations)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
