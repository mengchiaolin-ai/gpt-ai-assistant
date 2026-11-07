import math

import pytest

from duck_robot import feetech as ft


class FakeSerial:
    """記錄寫出的位元組，並依序回傳預先準備好的回覆。"""

    def __init__(self, replies=b""):
        self.written = bytearray()
        self.buffer = bytearray(replies)

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written += data

    def flush(self):
        pass

    def read(self, n):
        out, self.buffer = bytes(self.buffer[:n]), self.buffer[n:]
        return out

    def close(self):
        pass


def status(servo_id, params=b"", error=0):
    body = [servo_id, len(params) + 2, error, *params]
    return bytes([0xFF, 0xFF, *body, ft.checksum(body)])


def test_ping_packet_matches_datasheet():
    # Feetech 手冊範例：PING ID 1 → FF FF 01 02 01 FB
    assert ft.build_packet(1, ft.INST_PING) == bytes.fromhex("FFFF010201FB")


def test_ping_reads_reply():
    bus = ft.FeetechBus("x", serial_obj=FakeSerial(status(1)))
    assert bus.ping(1)
    assert not ft.FeetechBus("x", serial_obj=FakeSerial()).ping(1)


def test_rad_steps_roundtrip():
    assert ft.rad_to_steps(0.0) == 2048
    assert ft.rad_to_steps(math.pi / 2) == 3072
    assert ft.rad_to_steps(100) == 4095  # 夾在合法範圍內
    assert ft.steps_to_rad(1024) == pytest.approx(-math.pi / 2)


def test_decode_sign_magnitude():
    assert ft.decode_signed(100) == 100
    assert ft.decode_signed(0x8000 | 100) == -100


def test_sync_write_goal_positions():
    s = FakeSerial()
    ft.FeetechBus("x", serial_obj=s).set_goal_positions({10: 0.0, 11: math.pi / 2})
    # FF FF FE LEN 83 addr=42 size=2 | 10 00 08 | 11 00 0C | chk
    assert s.written[:7] == bytes([0xFF, 0xFF, 0xFE, 10, 0x83, 42, 2])
    assert s.written[7:13] == bytes([10, 0x00, 0x08, 11, 0x00, 0x0C])
    assert s.written[-1] == ft.checksum(s.written[2:-1])


def test_sync_read_positions_and_speeds():
    # 馬達 10：位置 3072（+π/2）、速度 -50 步/秒；馬達 11：位置 2048、速度 0
    replies = status(10, bytes([0x00, 0x0C, 50, 0x80])) + status(11, bytes([0x00, 0x08, 0, 0]))
    bus = ft.FeetechBus("x", serial_obj=FakeSerial(replies))
    pos, vel = bus.read_positions_and_speeds([10, 11])
    assert pos == pytest.approx([math.pi / 2, 0.0])
    assert vel == pytest.approx([-50 * ft.RAD_PER_STEP, 0.0])


def test_bad_checksum_rejected():
    bad = bytearray(status(1))
    bad[-1] ^= 0xFF
    with pytest.raises(ft.FeetechError):
        ft.parse_status(bytes(bad))


def test_resync_skips_garbage():
    bus = ft.FeetechBus("x", serial_obj=FakeSerial(b"\x00\x13" + status(5, bytes([7]))))
    assert bus._read_status(5) == (5, 0, bytes([7]))
