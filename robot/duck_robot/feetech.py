"""Feetech STS3215 匯流排伺服馬達驅動程式（純 Python + pyserial）。

刻意從零寫起，讓你看懂「匯流排馬達」怎麼運作：
所有馬達串在同一條 3 線匯流排上（V+、GND、DATA），每顆有自己的 ID。
我們送出一個小小的二進位封包，馬達再回一個封包。

封包格式（Feetech SCS/STS 協定）：

    0xFF 0xFF  ID  LENGTH  INSTRUCTION  PARAM_1 ... PARAM_N  CHECKSUM

    LENGTH   = N + 2
    CHECKSUM = ~(ID + LENGTH + INSTRUCTION + PARAM_1 + ... + PARAM_N) & 0xFF

STS 系列的 2 位元組數值是 little-endian（低位元組在前）。
位置：一圈 4096 步，2048 = 正中間 = 本程式的 0 弧度。
"""

from __future__ import annotations

import math
import time
from typing import Dict, Iterable, List, Optional, Sequence

# ---- Instructions ----
INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03
INST_SYNC_READ = 0x82
INST_SYNC_WRITE = 0x83

BROADCAST_ID = 0xFE

# ---- STS3215 記憶體表（本專案用到的位址）----
ADDR_ID = 5
ADDR_BAUD_RATE = 6
ADDR_P_COEF = 21
ADDR_D_COEF = 22
ADDR_I_COEF = 23
ADDR_TORQUE_ENABLE = 40
ADDR_ACCELERATION = 41
ADDR_GOAL_POSITION = 42
ADDR_GOAL_SPEED = 46
ADDR_LOCK = 55  # 0 = EEPROM writable, 1 = locked
ADDR_PRESENT_POSITION = 56
ADDR_PRESENT_SPEED = 58
ADDR_PRESENT_LOAD = 60
ADDR_PRESENT_VOLTAGE = 62
ADDR_PRESENT_TEMPERATURE = 63

STEPS_PER_TURN = 4096
CENTER_STEP = 2048
RAD_PER_STEP = 2 * math.pi / STEPS_PER_TURN


class FeetechError(IOError):
    pass


# ---------------------------------------------------------------- helpers
def checksum(body: Iterable[int]) -> int:
    return (~sum(body)) & 0xFF


def build_packet(servo_id: int, instruction: int, params: Sequence[int] = ()) -> bytes:
    length = len(params) + 2
    body = [servo_id, length, instruction, *params]
    return bytes([0xFF, 0xFF, *body, checksum(body)])


def rad_to_steps(rad: float) -> int:
    steps = int(round(rad / RAD_PER_STEP)) + CENTER_STEP
    return max(0, min(STEPS_PER_TURN - 1, steps))


def steps_to_rad(steps: int) -> float:
    return (steps - CENTER_STEP) * RAD_PER_STEP


def decode_signed(raw: int, sign_bit: int = 15) -> int:
    """STS 用「符號-大小」表示法：第 15 位元是正負號，其餘是數值大小。"""
    magnitude = raw & ((1 << sign_bit) - 1)
    return -magnitude if raw & (1 << sign_bit) else magnitude


def u16_le(value: int) -> List[int]:
    return [value & 0xFF, (value >> 8) & 0xFF]


def parse_status(data: bytes, expected_id: Optional[int] = None) -> tuple[int, int, bytes]:
    """解析一個回覆封包，回傳 (id, 錯誤旗標, 參數)。"""
    if len(data) < 6 or data[0] != 0xFF or data[1] != 0xFF:
        raise FeetechError(f"bad header: {data.hex(' ')}")
    servo_id, length, error = data[2], data[3], data[4]
    if length < 2 or len(data) < 4 + length:
        raise FeetechError(f"short packet: {data.hex(' ')}")
    params = data[5:5 + length - 2]
    if checksum(data[2:4 + length - 1]) != data[3 + length]:
        raise FeetechError(f"bad checksum: {data.hex(' ')}")
    if expected_id is not None and servo_id != expected_id:
        raise FeetechError(f"expected id {expected_id}, got {servo_id}")
    return servo_id, error, bytes(params)


# ---------------------------------------------------------------- bus
class FeetechBus:
    """透過 USB 轉序列埠的轉接板（例如 Waveshare「Bus Servo Adapter (A)」）
    和一串 STS3215 馬達溝通。"""

    def __init__(self, port: str, baudrate: int = 1_000_000, timeout: float = 0.02, serial_obj=None):
        if serial_obj is None:
            import serial  # pyserial

            serial_obj = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        self.ser = serial_obj

    def close(self) -> None:
        self.ser.close()

    # -- low level --
    def _write(self, packet: bytes) -> None:
        self.ser.reset_input_buffer()
        self.ser.write(packet)
        self.ser.flush()

    def _read_status(self, expected_id: Optional[int]) -> tuple[int, int, bytes]:
        header = self._read_exact(4)
        # 如果 0xFF 0xFF 前面有雜訊，逐位元組往後找
        while header[:2] != b"\xff\xff":
            header = header[1:] + self._read_exact(1)
        rest = self._read_exact(header[3])
        return parse_status(header + rest, expected_id)

    def _read_exact(self, n: int) -> bytes:
        data = self.ser.read(n)
        if len(data) != n:
            raise FeetechError(f"timeout: wanted {n} bytes, got {len(data)}")
        return data

    # -- 基本指令 --
    def ping(self, servo_id: int) -> bool:
        self._write(build_packet(servo_id, INST_PING))
        try:
            self._read_status(servo_id)
            return True
        except FeetechError:
            return False

    def scan(self, ids: Iterable[int] = range(0, 40)) -> List[int]:
        return [i for i in ids if self.ping(i)]

    def read(self, servo_id: int, address: int, size: int) -> bytes:
        self._write(build_packet(servo_id, INST_READ, [address, size]))
        _, error, params = self._read_status(servo_id)
        if error:
            raise FeetechError(f"servo {servo_id} error flags 0x{error:02x}")
        return params

    def write(self, servo_id: int, address: int, data: Sequence[int], wait_reply: bool = True) -> None:
        self._write(build_packet(servo_id, INST_WRITE, [address, *data]))
        if wait_reply and servo_id != BROADCAST_ID:
            self._read_status(servo_id)

    def sync_write(self, address: int, size: int, values: Dict[int, Sequence[int]]) -> None:
        """用一個封包同時寫很多顆馬達的同一個暫存器（馬達不回覆）。"""
        params: List[int] = [address, size]
        for servo_id, data in values.items():
            if len(data) != size:
                raise ValueError("data size mismatch")
            params += [servo_id, *data]
        self._write(build_packet(BROADCAST_ID, INST_SYNC_WRITE, params))

    def sync_read(self, address: int, size: int, ids: Sequence[int]) -> Dict[int, bytes]:
        """一次請求讀很多顆馬達的同一個暫存器，每顆馬達依序回覆。"""
        self._write(build_packet(BROADCAST_ID, INST_SYNC_READ, [address, size, *ids]))
        out: Dict[int, bytes] = {}
        for servo_id in ids:
            sid, _, params = self._read_status(servo_id)
            out[sid] = params
        return out

    # -- 高階函式（單位：弧度）--
    def set_torque(self, ids: Sequence[int], enable: bool) -> None:
        self.sync_write(ADDR_TORQUE_ENABLE, 1, {i: [1 if enable else 0] for i in ids})

    def set_kp(self, ids_kps: Dict[int, int]) -> None:
        self.sync_write(ADDR_P_COEF, 1, {i: [int(kp) & 0xFF] for i, kp in ids_kps.items()})

    def set_goal_positions(self, ids_rads: Dict[int, float]) -> None:
        self.sync_write(ADDR_GOAL_POSITION, 2, {i: u16_le(rad_to_steps(r)) for i, r in ids_rads.items()})

    def read_positions_and_speeds(self, ids: Sequence[int]) -> tuple[List[float], List[float]]:
        """一次讀回目前位置（rad）和速度（rad/s）。"""
        raw = self.sync_read(ADDR_PRESENT_POSITION, 4, ids)
        pos, vel = [], []
        for i in ids:
            b = raw[i]
            pos.append(steps_to_rad(b[0] | (b[1] << 8)))
            vel.append(decode_signed(b[2] | (b[3] << 8)) * RAD_PER_STEP)
        return pos, vel

    def read_voltage(self, servo_id: int) -> float:
        return self.read(servo_id, ADDR_PRESENT_VOLTAGE, 1)[0] / 10.0

    def read_temperature(self, servo_id: int) -> int:
        return self.read(servo_id, ADDR_PRESENT_TEMPERATURE, 1)[0]

    def change_id(self, old_id: int, new_id: int) -> None:
        """新的 STS3215 出廠 ID 都是 1。一次只接「一顆」馬達再呼叫這個函式。"""
        if not 0 <= new_id < BROADCAST_ID:
            raise ValueError("id must be in 0..253")
        self.write(old_id, ADDR_LOCK, [0])
        self.write(old_id, ADDR_ID, [new_id])
        time.sleep(0.05)
        self.write(new_id, ADDR_LOCK, [1])
