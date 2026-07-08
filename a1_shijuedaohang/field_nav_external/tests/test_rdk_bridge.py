"""Unit tests for RDK X5 UART bridge protocol.

Covers three critical layers:
  - A1 nav frame parsing:     parse_nav_frames()
  - RDK control frame packing: make_command_frame()
  - Safety control logic:     compute_control()

These tests run offline with no hardware dependency.
"""

from __future__ import annotations

import struct
import sys
import os as _os

import pytest

# ---------------------------------------------------------------------------
# Path setup: import the bridge module from the scripts directory
# ---------------------------------------------------------------------------
_SCRIPTS = _os.path.join(_os.path.dirname(__file__), "..", "scripts")
_SCRIPTS = _os.path.normpath(_os.path.abspath(_SCRIPTS))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import rdk_x5_nav_bridge as br  # noqa: E402


# ---------------------------------------------------------------------------
# Frame construction helpers (mirror A1 main.cpp for golden-value tests)
# ---------------------------------------------------------------------------

def _checksum15(data: bytes) -> int:
    """Sum of first 15 bytes, & 0xFF -- matches protocol spec."""
    return sum(data[:15]) & 0xFF


def _build_a1_nav_frame(
    seq=1,
    valid=True,
    deviation_px=0.0,
    angle_deg=0.0,
    confidence_pct=80,
    point_count=20,
    bottom_x=320,
    status=0,
):
    """Construct a well-formed 16-byte A1 nav frame for test injection."""
    packet = bytearray(16)
    packet[0] = 0xA5
    packet[1] = 0x5A
    packet[2] = 0x01  # version
    packet[3] = 0x01 if valid else 0x00
    struct.pack_into("<H", packet, 4, seq & 0xFFFF)
    struct.pack_into("<h", packet, 6, int(round(deviation_px * 10.0)))
    struct.pack_into("<h", packet, 8, int(round(angle_deg * 100.0)))
    packet[10] = confidence_pct & 0xFF
    packet[11] = point_count & 0xFF
    struct.pack_into("<H", packet, 12, bottom_x & 0xFFFF)
    packet[14] = status & 0xFF
    packet[15] = _checksum15(packet)
    return bytes(packet)


# ===========================================================================
# make_command_frame -- RDK -> lower-controller control frame packing
# ===========================================================================

class TestMakeCommandFrame:
    """Every control frame must have correct header, checksum, and byte layout."""

    def test_track_command_fields(self):
        """Normal track command encodes all fields correctly."""
        frame = br.make_command_frame(
            seq=42, enable=True, valid_nav=True,
            linear_v_mm_s=150, angular_w_mrad_s=-200,
            deviation_px=30.7, mode=1,
        )
        assert len(frame) == 16
        assert frame[:2] == br.CMD_HEADER
        assert frame[2] == 0x01  # version
        assert frame[3] == 0x03  # enable(0x01) | valid_nav(0x02)
        assert struct.unpack_from("<H", frame, 4)[0] == 42
        assert struct.unpack_from("<h", frame, 6)[0] == 150
        assert struct.unpack_from("<h", frame, 8)[0] == -200
        # deviation_px * 10 -> 307 -> int16
        assert struct.unpack_from("<h", frame, 10)[0] == 307
        assert frame[12] == 1  # mode
        assert frame[15] == _checksum15(frame)

    def test_stop_command(self):
        """Stop frame: enable=False, valid_nav=False, speeds=0, mode=0."""
        frame = br.make_command_frame(0, False, False, 0, 0, 0.0, 0)
        assert frame[3] == 0x00
        assert struct.unpack_from("<h", frame, 6)[0] == 0
        assert struct.unpack_from("<h", frame, 8)[0] == 0
        assert frame[12] == 0
        assert frame[15] == _checksum15(frame)

    def test_enable_without_valid_nav(self):
        """enable=True but valid_nav=False (e.g. low confidence)."""
        frame = br.make_command_frame(1, True, False, 150, 0, 0.0, 2)
        assert frame[3] == 0x01  # enable bit set, valid_nav bit clear

    def test_enable_false_with_valid_nav(self):
        """edge case: valid_nav set but enable off."""
        frame = br.make_command_frame(1, False, True, 0, 0, 0.0, 0)
        assert frame[3] == 0x02

    def test_clamp_linear_positive_overflow(self):
        """linear > 32767 clamped to 32767."""
        frame = br.make_command_frame(0, True, True, 100000, 0, 0.0, 1)
        assert struct.unpack_from("<h", frame, 6)[0] == 32767

    def test_clamp_linear_negative_underflow(self):
        """linear < -32768 clamped to -32768."""
        frame = br.make_command_frame(0, True, True, -100000, 0, 0.0, 1)
        assert struct.unpack_from("<h", frame, 6)[0] == -32768

    def test_clamp_angular_overflow(self):
        frame = br.make_command_frame(0, True, True, 0, 50000, 0.0, 1)
        assert struct.unpack_from("<h", frame, 8)[0] == 32767

    def test_clamp_angular_underflow(self):
        frame = br.make_command_frame(0, True, True, 0, -50000, 0.0, 1)
        assert struct.unpack_from("<h", frame, 8)[0] == -32768

    def test_clamp_deviation_overflow(self):
        """deviation_px so large that px*10 overflows int16."""
        frame = br.make_command_frame(0, True, True, 0, 0, 5000.0, 1)
        assert struct.unpack_from("<h", frame, 10)[0] == 32767

    def test_seq_wraps_at_16bit(self):
        """seq 65535 wraps to 0 on next frame."""
        f1 = br.make_command_frame(65535, True, True, 0, 0, 0.0, 1)
        f2 = br.make_command_frame(0, True, True, 0, 0, 0.0, 1)
        assert struct.unpack_from("<H", f1, 4)[0] == 65535
        assert struct.unpack_from("<H", f2, 4)[0] == 0
        assert _checksum15(f1) == f1[15]
        assert _checksum15(f2) == f2[15]

    def test_checksum_independent_of_last_byte(self):
        """Changing byte 15 (checksum) does not affect the computed checksum."""
        frame = br.make_command_frame(0, True, True, 100, 50, 10.0, 1)
        cs_before = _checksum15(frame)
        assert frame[15] == cs_before
        corrupted = bytearray(frame)
        corrupted[15] = 0x00
        assert _checksum15(corrupted) == cs_before

    def test_mode_byte_encoding(self):
        """Mode occupies byte 12; reserved bytes 13-14 are zero."""
        frame = br.make_command_frame(0, True, True, 0, 0, 0.0, 5)
        assert frame[12] == 5
        assert frame[13] == 0
        assert frame[14] == 0

    def test_all_zeros_except_header(self):
        """Full-stop frame should be all zeros except header and checksum."""
        frame = br.make_command_frame(0, False, False, 0, 0, 0.0, 0)
        assert frame[:2] == br.CMD_HEADER
        assert frame[3] == 0
        for off in (4, 6, 8, 10):
            assert struct.unpack_from("<H", frame, off)[0] == 0
        assert frame[12] == 0
        assert frame[13] == 0
        assert frame[14] == 0
        assert frame[15] == _checksum15(frame)

    def test_deviation_zero(self):
        """deviation_px=0.0 encodes correctly."""
        frame = br.make_command_frame(0, True, True, 0, 0, 0.0, 1)
        assert struct.unpack_from("<h", frame, 10)[0] == 0

    def test_deviation_negative(self):
        """Negative deviation encodes correctly."""
        frame = br.make_command_frame(0, True, True, 0, 0, -12.5, 1)
        assert struct.unpack_from("<h", frame, 10)[0] == -125


# ===========================================================================
# parse_nav_frames -- A1 nav frame byte-stream parsing
# ===========================================================================

class TestParseNavFrames:
    """Test the frame synchroniser against valid, partial, and corrupted streams."""

    def test_valid_frame_all_fields(self):
        buf = bytearray(_build_a1_nav_frame(
            seq=7, valid=True, deviation_px=-12.3, angle_deg=5.67,
            confidence_pct=88, point_count=30, bottom_x=400, status=0,
        ))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1
        f = frames[0]
        assert f.seq == 7
        assert f.valid is True
        assert f.deviation_px == pytest.approx(-12.3)
        assert f.angle_deg == pytest.approx(5.67)
        assert f.confidence_pct == 88
        assert f.point_count == 30
        assert f.bottom_x_px == 400
        assert f.status == 0

    def test_valid_frame_consumes_buffer(self):
        buf = bytearray(_build_a1_nav_frame(seq=0))
        br.parse_nav_frames(buf)
        assert len(buf) == 0  # consumed

    def test_valid_zero_frame(self):
        """valid=0 frame: deviation/angle/confidence fields may be zero."""
        buf = bytearray(_build_a1_nav_frame(
            seq=1, valid=False, deviation_px=0.0, angle_deg=0.0,
            confidence_pct=0, point_count=0, bottom_x=0, status=0,
        ))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1
        assert frames[0].valid is False
        assert frames[0].status == 0

    def test_two_frames_in_one_buffer(self):
        buf = bytearray()
        buf.extend(_build_a1_nav_frame(seq=1))
        buf.extend(_build_a1_nav_frame(seq=2, deviation_px=100.0))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 2
        assert frames[0].seq == 1
        assert frames[1].seq == 2
        assert frames[1].deviation_px == pytest.approx(100.0)
        assert len(buf) == 0

    def test_three_frames_sequential(self):
        buf = bytearray()
        for i in range(3):
            buf.extend(_build_a1_nav_frame(seq=i, deviation_px=float(i)))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 3
        assert [f.seq for f in frames] == [0, 1, 2]

    def test_partial_frame_waiting(self):
        """Only 14 bytes: should return empty and keep buffer intact."""
        full = _build_a1_nav_frame(seq=0)
        buf = bytearray(full[:14])
        frames = br.parse_nav_frames(buf)
        assert frames == []
        assert len(buf) == 14  # untouched -- waiting for more bytes

    def test_empty_buffer(self):
        buf = bytearray()
        frames = br.parse_nav_frames(buf)
        assert frames == []

    def test_partial_then_complete_across_reads(self):
        """Simulate two reads: first 14 bytes, then the remaining 2."""
        full = _build_a1_nav_frame(seq=99, deviation_px=1.0)
        buf = bytearray(full[:14])
        frames = br.parse_nav_frames(buf)
        assert frames == []
        assert len(buf) == 14
        buf.extend(full[14:])
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1
        assert frames[0].seq == 99

    def test_garbage_before_header(self):
        """Random bytes before a valid frame are discarded."""
        buf = bytearray(b"\x00\xFF\x00\xFF")
        buf.extend(_build_a1_nav_frame(seq=3))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1
        assert frames[0].seq == 3
        assert len(buf) == 0

    def test_garbage_only_no_header(self):
        """Buffer with no A5 5A anywhere: emptied except last byte."""
        buf = bytearray(b"\x00\x01\x02\x03\x04")
        frames = br.parse_nav_frames(buf)
        assert frames == []
        assert buf == bytearray(b"\x04")

    def test_garbage_only_single_byte(self):
        """Single non-header byte kept."""
        buf = bytearray(b"\xCC")
        frames = br.parse_nav_frames(buf)
        assert frames == []
        assert buf == bytearray(b"\xCC")

    def test_garbage_only_two_bytes(self):
        """Two non-header bytes: only last kept."""
        buf = bytearray(b"\xCC\xDD")
        frames = br.parse_nav_frames(buf)
        assert frames == []
        assert buf == bytearray(b"\xDD")

    def test_lone_a5_then_valid_header(self):
        """A single 0xA5 before the real A5 5A header is treated as garbage."""
        buf = bytearray(b"\xA5")
        buf.extend(_build_a1_nav_frame(seq=10))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1
        assert frames[0].seq == 10
        assert len(buf) == 0

    def test_bad_checksum_skipped(self):
        """Frame with wrong checksum is discarded; next valid frame consumed."""
        bad = bytearray(_build_a1_nav_frame(seq=1))
        bad[15] = (bad[15] + 1) & 0xFF  # corrupt checksum
        buf = bytearray(bad)
        buf.extend(_build_a1_nav_frame(seq=2))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1
        assert frames[0].seq == 2

    def test_bad_header_then_valid(self):
        """A block without A5 5A header, followed by valid frame."""
        buf = bytearray(bytes(32))
        buf.extend(_build_a1_nav_frame(seq=5))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1
        assert frames[0].seq == 5

    def test_max_seq(self):
        buf = bytearray(_build_a1_nav_frame(seq=65535))
        frames = br.parse_nav_frames(buf)
        assert frames[0].seq == 65535

    def test_deviation_int16_extremes(self):
        """deviation_px * 10 fits in [-32768, 32767]."""
        buf = bytearray(_build_a1_nav_frame(deviation_px=-3276.8))
        frames = br.parse_nav_frames(buf)
        assert frames[0].deviation_px == pytest.approx(-3276.8)

        buf = bytearray(_build_a1_nav_frame(deviation_px=3276.7))
        frames = br.parse_nav_frames(buf)
        assert frames[0].deviation_px == pytest.approx(3276.7)

    def test_confidence_boundaries(self):
        buf = bytearray(_build_a1_nav_frame(confidence_pct=0))
        assert br.parse_nav_frames(buf)[0].confidence_pct == 0

        buf = bytearray(_build_a1_nav_frame(confidence_pct=100))
        assert br.parse_nav_frames(buf)[0].confidence_pct == 100

    def test_status_field_preserved(self):
        buf = bytearray(_build_a1_nav_frame(status=7))
        assert br.parse_nav_frames(buf)[0].status == 7


# ===========================================================================
# compute_control -- safety-aware control logic
# ===========================================================================

class TestComputeControl:
    """Tests for safety stop: timeout, low confidence, status errors,
    and normal tracking mode with speed modulation."""

    @staticmethod
    def _args(**overrides):
        """Build a simple argparse-like namespace for compute_control()."""
        defaults = {
            "linear": 150,
            "kp_dev": -2.0,
            "kp_ang": -20.0,
            "max_angular": 800,
            "min_confidence": 30,
            "timeout": 0.3,
            "slow_dev": 180.0,
            "slow_angle": 15.0,
            "rate": 10.0,
            "port": "/dev/ttyS1",
            "baud": 115200,
        }
        defaults.update(overrides)

        class NS:
            def __init__(self, d):
                self.__dict__.update(d)
        return NS(defaults)

    def _nav(self, **kw):
        """Make a NavFrame with fresh timestamp."""
        import time
        defaults = dict(
            seq=0, valid=True, deviation_px=0.0, angle_deg=0.0,
            confidence_pct=80, point_count=20, bottom_x_px=320,
            status=0, timestamp=time.monotonic(),
        )
        defaults.update(kw)
        return br.NavFrame(**defaults)

    def test_no_nav_returns_stop(self):
        enable, valid_nav, linear, angular, _, mode, _reason = br.compute_control(
            None, self._args()
        )
        assert enable is False
        assert valid_nav is False
        assert linear == 0
        assert angular == 0
        assert mode == 2

    def test_timeout_returns_stop(self):
        args = self._args(timeout=0.1)
        import time
        nav = br.NavFrame(
            seq=0, valid=True, deviation_px=0.0, angle_deg=0.0,
            confidence_pct=80, point_count=20, bottom_x_px=320,
            status=0, timestamp=time.monotonic() - 0.2,
        )
        enable, valid_nav, _, _, _, mode, _ = br.compute_control(nav, args)
        assert enable is False
        assert valid_nav is False
        assert mode == 2

    def test_fresh_nav_within_timeout(self):
        args = self._args(timeout=2.0)
        nav = self._nav()
        enable, _, _, _, _, _, _ = br.compute_control(nav, args)
        assert enable is True

    def test_low_confidence_returns_stop(self):
        args = self._args(min_confidence=30)
        nav = self._nav(confidence_pct=29, valid=True)
        enable, valid_nav, _, _, _, mode, _ = br.compute_control(nav, args)
        assert enable is False
        assert valid_nav is False
        assert mode == 2

    def test_confidence_at_boundary(self):
        args = self._args(min_confidence=30)
        nav = self._nav(confidence_pct=30)
        enable, _, _, _, _, _, _ = br.compute_control(nav, args)
        assert enable is True

    def test_status_nonzero_returns_stop(self):
        args = self._args()
        nav = self._nav(valid=True, status=1)
        enable, valid_nav, _, _, _, mode, _ = br.compute_control(nav, args)
        assert enable is False
        assert mode == 2

    def test_status_zero_valid_false_returns_stop(self):
        """valid=False from A1 should still stop."""
        args = self._args()
        nav = self._nav(valid=False, status=0)
        enable, valid_nav, _, _, _, mode, _ = br.compute_control(nav, args)
        assert enable is False
        assert valid_nav is False
        assert mode == 2

    def test_timeout_and_low_confidence_both_stop(self):
        args = self._args(timeout=0.1, min_confidence=50)
        import time
        nav = br.NavFrame(
            seq=0, valid=True, deviation_px=0.0, angle_deg=0.0,
            confidence_pct=20, point_count=0, bottom_x_px=0,
            status=0, timestamp=time.monotonic() - 0.5,
        )
        enable, valid_nav, _, _, _, mode, _ = br.compute_control(nav, args)
        assert enable is False
        assert mode == 2

    def test_valid_nav_track_mode(self):
        nav = self._nav(deviation_px=10.0, angle_deg=-2.0)
        enable, valid_nav, linear, _, _, mode, _ = br.compute_control(
            nav, self._args()
        )
        assert enable is True
        assert valid_nav is True
        assert linear == 150
        assert mode == 1

    def test_angular_p_control_sign(self):
        """kp_dev < 0, kp_ang < 0: positive deviation -> negative angular."""
        args = self._args(kp_dev=-2.0, kp_ang=-20.0)
        nav = self._nav(deviation_px=50.0, angle_deg=10.0)
        _, _, _, angular, _, _, _ = br.compute_control(nav, args)
        assert angular == -300

    def test_angular_clamped_to_max(self):
        args = self._args(kp_dev=-20.0, kp_ang=-50.0, max_angular=800)
        nav = self._nav(deviation_px=200.0, angle_deg=90.0)
        _, _, _, angular, _, _, _ = br.compute_control(nav, args)
        assert angular == -800

    def test_angular_clamped_positive(self):
        args = self._args(kp_dev=20.0, kp_ang=50.0, max_angular=800)
        nav = self._nav(deviation_px=200.0, angle_deg=90.0)
        _, _, _, angular, _, _, _ = br.compute_control(nav, args)
        assert angular == 800

    def test_large_deviation_triggers_slow(self):
        args = self._args(slow_dev=180.0, linear=200)
        nav = self._nav(deviation_px=200.0)
        _, _, linear, _, _, _, _ = br.compute_control(nav, args)
        assert linear == 100

    def test_large_angle_triggers_slow(self):
        args = self._args(slow_angle=15.0, linear=200)
        nav = self._nav(angle_deg=20.0)
        _, _, linear, _, _, _, _ = br.compute_control(nav, args)
        assert linear == 100

    def test_large_dev_and_angle_not_double_slowed(self):
        """Both thresholds exceeded -> still *0.5, not *0.25."""
        args = self._args(slow_dev=180.0, slow_angle=15.0, linear=200)
        nav = self._nav(deviation_px=200.0, angle_deg=20.0)
        _, _, linear, _, _, _, _ = br.compute_control(nav, args)
        assert linear == 100

    def test_small_deviation_full_speed(self):
        args = self._args(slow_dev=180.0, slow_angle=15.0, linear=200)
        nav = self._nav(deviation_px=50.0, angle_deg=5.0)
        _, _, linear, _, _, _, _ = br.compute_control(nav, args)
        assert linear == 200


# ===========================================================================
# End-to-end scenario tests
# ===========================================================================

class TestEndToEnd:
    """Simulate a full A1 -> RDK -> lower-controller pipeline in memory."""

    def test_happy_path(self):
        """Valid A1 nav frame -> tracked by RDK -> control frame."""
        buf = bytearray(_build_a1_nav_frame(
            seq=42, deviation_px=-15.0, angle_deg=3.0,
            confidence_pct=85,
        ))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1

        args = TestComputeControl._args()
        enable, valid_nav, linear, angular, _, mode, _reason = br.compute_control(
            frames[0], args
        )
        assert enable is True
        assert valid_nav is True
        assert mode == 1

        cmd = br.make_command_frame(
            0, enable, valid_nav, linear, angular,
            frames[0].deviation_px, mode,
        )
        assert cmd[:2] == br.CMD_HEADER
        assert cmd[15] == _checksum15(cmd)
        assert cmd[3] == 0x03

    def test_stale_frame_pipeline(self):
        """Stale nav -> compute_control stops -> stop command frame."""
        import time
        nav = br.NavFrame(
            seq=1, valid=True, deviation_px=0.0, angle_deg=0.0,
            confidence_pct=80, point_count=20, bottom_x_px=320,
            status=0, timestamp=0.0,
        )
        args = TestComputeControl._args(timeout=0.3)
        enable, valid_nav, linear, angular, _, mode, _reason = br.compute_control(
            nav, args
        )
        assert enable is False
        assert mode == 2

        cmd = br.make_command_frame(99, enable, valid_nav, linear, angular, 0.0, mode)
        assert cmd[:2] == br.CMD_HEADER
        assert cmd[3] == 0x00
        assert cmd[12] == 2
        assert struct.unpack_from("<h", cmd, 6)[0] == 0
        assert struct.unpack_from("<h", cmd, 8)[0] == 0

    def test_invalid_frame_ignored_valid_next_frame_used(self):
        """Corrupt frame discarded; following valid frame drives control."""
        bad = bytearray(_build_a1_nav_frame(seq=1))
        bad[15] = (bad[15] + 1) & 0xFF
        buf = bytearray(bad)
        buf.extend(_build_a1_nav_frame(
            seq=2, valid=True, deviation_px=5.0, confidence_pct=90,
        ))
        frames = br.parse_nav_frames(buf)
        assert len(frames) == 1
        assert frames[0].seq == 2

        args = TestComputeControl._args()
        enable, _, _, _, _, _, _ = br.compute_control(frames[0], args)
        assert enable is True


# ===========================================================================
# Lower-controller reference parser (protocol symmetry + safety rules)
# ===========================================================================

class TestLowerControllerReference:
    """Verify lower-controller parser sees the same values that
    make_command_frame encodes. Doubles as reference for lower computer."""

    def _parse_ctrl(self, raw):
        """Reference parser for B5 5B control frame."""
        if len(raw) < 16:
            raise ValueError("frame too short")
        if raw[:2] != br.CMD_HEADER:
            raise ValueError("bad header")
        cs = sum(raw[:15]) & 0xFF
        if cs != raw[15]:
            raise ValueError("checksum mismatch")
        return {
            "version": raw[2],
            "enable": bool(raw[3] & 0x01),
            "valid_nav": bool(raw[3] & 0x02),
            "seq": struct.unpack_from("<H", raw, 4)[0],
            "linear_v_mm_s": struct.unpack_from("<h", raw, 6)[0],
            "angular_w_mrad_s": struct.unpack_from("<h", raw, 8)[0],
            "deviation_px": struct.unpack_from("<h", raw, 10)[0] / 10.0,
            "mode": raw[12],
        }

    def test_roundtrip_track(self):
        orig = {
            "seq": 123, "enable": True, "valid_nav": True,
            "linear_v_mm_s": 150, "angular_w_mrad_s": -300,
            "deviation_px": 20.0, "mode": 1,
        }
        frame = br.make_command_frame(**orig)
        parsed = self._parse_ctrl(frame)
        assert parsed["enable"] == orig["enable"]
        assert parsed["valid_nav"] == orig["valid_nav"]
        assert parsed["seq"] == orig["seq"]
        assert parsed["linear_v_mm_s"] == orig["linear_v_mm_s"]
        assert parsed["angular_w_mrad_s"] == orig["angular_w_mrad_s"]
        assert parsed["deviation_px"] == pytest.approx(orig["deviation_px"], abs=0.05)
        assert parsed["mode"] == orig["mode"]

    def test_roundtrip_stop(self):
        orig = {
            "seq": 0, "enable": False, "valid_nav": False,
            "linear_v_mm_s": 0, "angular_w_mrad_s": 0,
            "deviation_px": 0.0, "mode": 0,
        }
        frame = br.make_command_frame(**orig)
        parsed = self._parse_ctrl(frame)
        assert parsed["enable"] is False
        assert parsed["valid_nav"] is False
        assert parsed["mode"] == 0

    def test_safety_stop_mode2(self):
        orig = {
            "seq": 42, "enable": False, "valid_nav": False,
            "linear_v_mm_s": 0, "angular_w_mrad_s": 0,
            "deviation_px": 0.0, "mode": 2,
        }
        frame = br.make_command_frame(**orig)
        parsed = self._parse_ctrl(frame)
        assert parsed["mode"] == 2
        assert parsed["enable"] is False

    def test_lower_controller_safety_rules(self):
        """The three golden rules for the lower computer."""
        # Rule 1: reject non-B5 5B frames
        with pytest.raises(ValueError):
            self._parse_ctrl(b"\x00" * 16)

        # Rule 2: reject checksum errors
        good = br.make_command_frame(0, True, True, 100, 0, 0.0, 1)
        bad = bytearray(good)
        bad[6] ^= 0x01
        with pytest.raises(ValueError):
            self._parse_ctrl(bytes(bad))

        # Rule 3: only move when enable=1 AND valid_nav=1 AND mode!=2
        valid = br.make_command_frame(0, True, True, 100, 50, 10.0, 1)
        parsed = self._parse_ctrl(valid)
        assert parsed["enable"] and parsed["valid_nav"]

        stop = br.make_command_frame(0, False, True, 100, 0, 0.0, 2)
        parsed = self._parse_ctrl(stop)
        assert not parsed["enable"]


# ===========================================================================
# Protocol constant / field-width safety checks
# ===========================================================================

class TestProtocolConstants:
    """Verify protocol constants are consistent and frame lengths match."""

    def test_nav_frame_len(self):
        assert br.NAV_FRAME_LEN == 16

    def test_cmd_frame_len(self):
        assert br.CMD_FRAME_LEN == 16

    def test_nav_header_bytes(self):
        assert br.NAV_HEADER == b"\xA5\x5A"
        assert len(br.NAV_HEADER) == 2

    def test_cmd_header_bytes(self):
        assert br.CMD_HEADER == b"\xB5\x5B"
        assert len(br.CMD_HEADER) == 2

    def test_checksum_fn(self):
        frame = _build_a1_nav_frame()
        assert br.checksum15(frame) == _checksum15(frame)
        assert br.checksum15(frame) == frame[15]

    def test_clamp_identity(self):
        assert br.clamp(50.0, 0.0, 100.0) == 50.0

    def test_clamp_low(self):
        assert br.clamp(-999.0, 0.0, 100.0) == 0.0

    def test_clamp_high(self):
        assert br.clamp(999.0, 0.0, 100.0) == 100.0


# ===========================================================================
# compute_control safety reason strings
# ===========================================================================

class TestComputeControlSafetyReasons:
    """Verify compute_control returns correct safety_reason for each scenario."""

    @staticmethod
    def _args(**overrides):
        defaults = {
            "linear": 150, "kp_dev": -2.0, "kp_ang": -20.0,
            "max_angular": 800, "min_confidence": 30, "timeout": 0.3,
            "slow_dev": 180.0, "slow_angle": 15.0, "rate": 10.0,
            "port": "/dev/ttyS1", "baud": 115200,
        }
        defaults.update(overrides)

        class NS:
            def __init__(self, d):
                self.__dict__.update(d)
        return NS(defaults)

    def _nav(self, **kw):
        import time
        defaults = dict(
            seq=0, valid=True, deviation_px=0.0, angle_deg=0.0,
            confidence_pct=80, point_count=20, bottom_x_px=320,
            status=0, timestamp=time.monotonic(),
        )
        defaults.update(kw)
        return br.NavFrame(**defaults)

    def test_reason_no_frame(self):
        _, _, _, _, _, _, reason = br.compute_control(None, self._args())
        assert reason == "no_frame"

    def test_reason_timeout(self):
        import time
        nav = br.NavFrame(
            seq=0, valid=True, deviation_px=0.0, angle_deg=0.0,
            confidence_pct=80, point_count=20, bottom_x_px=320,
            status=0, timestamp=time.monotonic() - 1.0,
        )
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args(timeout=0.3))
        assert reason == "timeout"

    def test_reason_invalid_flag(self):
        nav = self._nav(valid=False, status=0)
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args())
        assert reason == "invalid_flag"

    def test_reason_status_error(self):
        nav = self._nav(valid=True, status=3)
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args())
        assert reason == "status_error"

    def test_reason_low_confidence(self):
        nav = self._nav(valid=True, status=0, confidence_pct=10)
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args(min_confidence=30))
        assert reason == "low_confidence"

    def test_reason_ok(self):
        nav = self._nav(deviation_px=10.0, angle_deg=2.0)
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args())
        assert reason == "ok"

    def test_reason_slow_speed(self):
        nav = self._nav(deviation_px=200.0, angle_deg=5.0)
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args(slow_dev=180.0))
        assert reason == "slow_speed"

    def test_reason_slow_speed_large_angle(self):
        nav = self._nav(deviation_px=10.0, angle_deg=20.0)
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args(slow_angle=15.0))
        assert reason == "slow_speed"

    def test_reason_priority_timeout_over_others(self):
        """Timeout should be reported even if other issues exist."""
        import time
        nav = br.NavFrame(
            seq=0, valid=False, deviation_px=0.0, angle_deg=0.0,
            confidence_pct=0, point_count=0, bottom_x_px=0,
            status=99, timestamp=time.monotonic() - 1.0,
        )
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args(timeout=0.3))
        assert reason == "timeout"

    def test_reason_priority_invalid_over_status(self):
        """invalid_flag checked before status_error."""
        nav = self._nav(valid=False, status=5)
        _, _, _, _, _, _, reason = br.compute_control(nav, self._args())
        assert reason == "invalid_flag"


# ===========================================================================
# BridgeStatus construction and JSON snapshot
# ===========================================================================

class TestBridgeStatus:
    """Tests for the BridgeStatus shared state class used by the web dashboard."""

    def test_default_construction(self):
        s = br.BridgeStatus()
        assert s.latest_nav_seq is None
        assert s.latest_nav_valid is False
        assert s.latest_cmd_seq == 0
        assert s.latest_cmd_enable is False
        assert s.checksum_errors == 0
        assert s.seq_jumps == 0
        assert s.a1_timeouts == 0
        assert s.safety_reason == ""
        assert s.cmd_rate_hz == 0.0
        assert s.total_nav_frames == 0
        assert s.total_cmd_frames == 0
        assert s.start_time > 0
        assert s._cs_err_ref == [0]

    def test_snapshot_structure(self):
        s = br.BridgeStatus()
        snap = s.snapshot()
        assert "nav" in snap
        assert "cmd" in snap
        assert "diag" in snap
        # nav sub-keys
        for k in ("seq", "valid", "deviation_px", "angle_deg", "confidence_pct",
                   "point_count", "bottom_x_px", "status", "age_ms"):
            assert k in snap["nav"], f"missing nav.{k}"
        # cmd sub-keys
        for k in ("seq", "enable", "valid_nav", "linear_mm_s", "angular_mrad_s",
                   "deviation_px", "mode"):
            assert k in snap["cmd"], f"missing cmd.{k}"
        # diag sub-keys
        for k in ("checksum_errors", "seq_jumps", "a1_timeouts", "safety_reason",
                   "safety_state", "a1_timeout", "rdk_output_active",
                   "cmd_rate_hz", "uptime_s", "total_nav_frames", "total_cmd_frames"):
            assert k in snap["diag"], f"missing diag.{k}"

    def test_snapshot_reflects_updates(self):
        s = br.BridgeStatus()
        with s.lock:
            s.latest_nav_seq = 42
            s.latest_nav_valid = True
            s.latest_nav_deviation_px = 15.5
            s.latest_cmd_enable = True
            s.latest_cmd_linear = 150
            s.checksum_errors = 3
            s.safety_reason = "ok"
        snap = s.snapshot()
        assert snap["nav"]["seq"] == 42
        assert snap["nav"]["valid"] is True
        assert snap["nav"]["deviation_px"] == 15.5
        assert snap["cmd"]["enable"] is True
        assert snap["cmd"]["linear_mm_s"] == 150
        assert snap["diag"]["checksum_errors"] == 3
        assert snap["diag"]["safety_reason"] == "ok"

    def test_snapshot_recomputes_nav_age_from_timestamp(self):
        import time

        s = br.BridgeStatus()
        with s.lock:
            s.latest_nav_timestamp = time.monotonic() - 0.2
        snap = s.snapshot()
        assert 150 <= snap["nav"]["age_ms"] <= 1000

    def test_snapshot_is_thread_safe(self):
        """Concurrent reads from snapshot() should not raise."""
        import threading
        s = br.BridgeStatus()
        errors = []

        def reader():
            try:
                for _ in range(100):
                    s.snapshot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_snapshot_uptime_increases(self):
        s = br.BridgeStatus()
        s1 = s.snapshot()
        import time
        time.sleep(0.05)
        s2 = s.snapshot()
        assert s2["diag"]["uptime_s"] > s1["diag"]["uptime_s"]

    def test_json_serializable(self):
        import json
        s = br.BridgeStatus()
        snap = s.snapshot()
        encoded = json.dumps(snap)
        decoded = json.loads(encoded)
        assert decoded["diag"]["checksum_errors"] == 0

    def test_start_time_is_monotonic(self):
        s1 = br.BridgeStatus()
        import time
        time.sleep(0.01)
        s2 = br.BridgeStatus()
        assert s2.start_time > s1.start_time

    def test_cs_err_ref_is_list(self):
        s = br.BridgeStatus()
        assert isinstance(s._cs_err_ref, list)
        assert len(s._cs_err_ref) == 1
        assert s._cs_err_ref[0] == 0


class TestSafetyStateMapping:
    """The web dashboard should expose operator-facing safety states."""

    def test_track_state(self):
        assert br.safety_state_from_reason("ok") == "TRACK"

    def test_slow_speed_still_tracks(self):
        assert br.safety_state_from_reason("slow_speed") == "TRACK"

    def test_no_frame_state(self):
        assert br.safety_state_from_reason("no_frame") == "STOP_NO_NAV"

    def test_invalid_flag_state(self):
        assert br.safety_state_from_reason("invalid_flag") == "STOP_NO_NAV"

    def test_low_confidence_state(self):
        assert br.safety_state_from_reason("low_confidence") == "STOP_LOW_CONF"

    def test_timeout_state(self):
        assert br.safety_state_from_reason("timeout") == "STOP_TIMEOUT"

    def test_status_error_state(self):
        assert br.safety_state_from_reason("status_error") == "STOP_STATUS_ERR"

    def test_snapshot_includes_mapped_safety_state(self):
        s = br.BridgeStatus()
        with s.lock:
            s.safety_reason = "low_confidence"
        assert s.snapshot()["diag"]["safety_state"] == "STOP_LOW_CONF"

    def test_snapshot_marks_a1_timeout(self):
        s = br.BridgeStatus()
        with s.lock:
            s.safety_reason = "timeout"
        assert s.snapshot()["diag"]["a1_timeout"] is True

    def test_snapshot_marks_rdk_output_active_from_rate(self):
        s = br.BridgeStatus()
        with s.lock:
            s.cmd_rate_hz = 9.8
        assert s.snapshot()["diag"]["rdk_output_active"] is True


class TestParseWebEndpoint:
    """Tests for --web HOST:PORT parsing."""

    def test_parse_ipv4_any(self):
        assert br.parse_web_endpoint("0.0.0.0:8080") == ("0.0.0.0", 8080)

    def test_parse_localhost(self):
        assert br.parse_web_endpoint("127.0.0.1:18080") == ("127.0.0.1", 18080)

    def test_parse_bracketed_ipv6(self):
        assert br.parse_web_endpoint("[::1]:8080") == ("::1", 8080)

    @pytest.mark.parametrize("value", ["8080", "0.0.0.0", "0.0.0.0:", ":8080", "0.0.0.0:0", "0.0.0.0:70000"])
    def test_reject_invalid_values(self, value):
        with pytest.raises(ValueError):
            br.parse_web_endpoint(value)


# ===========================================================================
# Web server handler tests (pure stdlib, no live server needed)
# ===========================================================================

class TestWebHandler:
    """Test BridgeHTTPHandler responses for /, /status, and 404 paths."""

    @staticmethod
    def _make_handler(path: str, status: br.BridgeStatus | None = None):
        """Create a handler instance wired to a BytesIO wfile and a mock server.

        We bypass the normal __init__ -> setup() -> handle() chain by directly
        instantiating the handler and setting up the minimal attributes that
        do_GET() needs.  This avoids requiring a real socket with makefile().
        """
        import io

        if status is None:
            status = br.BridgeStatus()

        # Minimal mock server carrying bridge_status
        class MockServer:
            pass
        server = MockServer()
        server.bridge_status = status

        # Bypass __init__ to avoid setup() requiring a real socket
        handler = br.BridgeHTTPHandler.__new__(br.BridgeHTTPHandler)
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        handler.path = path
        handler.command = "GET"
        handler.headers = {}
        handler.server = server
        handler.client_address = ("127.0.0.1", 8080)
        # Mock the response-related methods that do_GET calls
        handler._response_code = 200
        handler._response_headers = []

        # Override send_response / send_header / end_headers to not require
        # a real socket connection object
        def _send_response(code, message=None):
            handler._response_code = code
        def _send_header(key, value):
            handler._response_headers.append((key, value))
        def _end_headers():
            pass

        handler.send_response = _send_response  # type: ignore[method-assign]
        handler.send_header = _send_header  # type: ignore[method-assign]
        handler.end_headers = _end_headers  # type: ignore[method-assign]

        return handler

    def test_status_json_200(self):
        handler = self._make_handler("/status")
        handler.do_GET()
        body = handler.wfile.getvalue()  # type: ignore[union-attr]
        assert b"checksum_errors" in body
        assert b"safety_reason" in body
        assert b"uptime_s" in body

    def test_status_content_type_json(self):
        handler = self._make_handler("/status")
        handler.do_GET()
        body = handler.wfile.getvalue()  # type: ignore[union-attr]
        # verify it's valid JSON
        import json
        data = json.loads(body)
        assert "nav" in data
        assert "cmd" in data
        assert "diag" in data

    def test_dashboard_html_200(self):
        handler = self._make_handler("/")
        handler.do_GET()
        body = handler.wfile.getvalue()  # type: ignore[union-attr]
        assert b"<!DOCTYPE html>" in body
        assert b"RDK X5 Bridge Dashboard" in body

    def test_dashboard_path_also_works(self):
        handler = self._make_handler("/dashboard")
        handler.do_GET()
        body = handler.wfile.getvalue()  # type: ignore[union-attr]
        assert b"<!DOCTYPE html>" in body

    def test_404_unknown_path(self):
        handler = self._make_handler("/nonexistent")
        handler.do_GET()
        body = handler.wfile.getvalue()  # type: ignore[union-attr]
        assert b"not found" in body

    def test_404_is_json(self):
        handler = self._make_handler("/bad")
        handler.do_GET()
        body = handler.wfile.getvalue()  # type: ignore[union-attr]
        import json
        data = json.loads(body)
        assert data["error"] == "not found"

    def test_status_reflects_nav_update(self):
        s = br.BridgeStatus()
        with s.lock:
            s.latest_nav_seq = 100
            s.latest_nav_deviation_px = -5.0
            s.safety_reason = "low_confidence"
        handler = self._make_handler("/status", s)
        handler.do_GET()
        import json
        data = json.loads(handler.wfile.getvalue())  # type: ignore[union-attr]
        assert data["nav"]["seq"] == 100
        assert data["nav"]["deviation_px"] == -5.0
        assert data["diag"]["safety_reason"] == "low_confidence"

    def test_status_reflects_cmd_update(self):
        s = br.BridgeStatus()
        with s.lock:
            s.latest_cmd_seq = 99
            s.latest_cmd_enable = True
            s.latest_cmd_linear = 200
            s.latest_cmd_mode = 1
            s.cmd_rate_hz = 10.0
        handler = self._make_handler("/status", s)
        handler.do_GET()
        import json
        data = json.loads(handler.wfile.getvalue())  # type: ignore[union-attr]
        assert data["cmd"]["seq"] == 99
        assert data["cmd"]["enable"] is True
        assert data["cmd"]["linear_mm_s"] == 200
        assert data["cmd"]["mode"] == 1
        assert data["diag"]["cmd_rate_hz"] == 10.0

    def test_html_contains_key_elements(self):
        handler = self._make_handler("/")
        handler.do_GET()
        body = handler.wfile.getvalue().decode("utf-8")  # type: ignore[union-attr]
        assert "fetch('/status')" in body
        assert "nav-table" in body
        assert "cmd-table" in body
        assert "diag-grid" in body
        assert "safety_reason" in body or "reason" in body
        assert "setInterval" in body

    def test_dashboard_refreshes_status_every_readable_500ms_without_page_reload(self):
        handler = self._make_handler("/")
        handler.do_GET()
        body = handler.wfile.getvalue().decode("utf-8")  # type: ignore[union-attr]
        assert 'http-equiv="refresh"' not in body
        assert "const REFRESH_INTERVAL_MS = 500" in body
        assert "setInterval(render, REFRESH_INTERVAL_MS)" in body
        assert "数据保持 500ms" in body

    def test_dashboard_has_chinese_control_room_layout_text(self):
        handler = self._make_handler("/")
        handler.do_GET()
        body = handler.wfile.getvalue().decode("utf-8")  # type: ignore[union-attr]
        assert '<html lang="zh-CN">' in body
        assert "田间道路导航监控台" in body
        assert "A1 导航帧" in body
        assert "RDK 控制帧" in body
        assert "安全状态" in body
        assert "链路诊断" in body
        assert "layout-shell" in body
        assert "status-strip" in body

    def test_log_message_silent(self):
        """log_message should not raise (it's a no-op override)."""
        handler = self._make_handler("/")
        try:
            handler.log_message("test %s", "arg")
        except Exception:
            pytest.fail("log_message raised unexpectedly")

    def test_status_diag_counters(self):
        s = br.BridgeStatus()
        s.checksum_errors = 7
        s.seq_jumps = 3
        s.a1_timeouts = 2
        s.total_nav_frames = 500
        s.total_cmd_frames = 490
        handler = self._make_handler("/status", s)
        handler.do_GET()
        import json
        data = json.loads(handler.wfile.getvalue())  # type: ignore[union-attr]
        d = data["diag"]
        assert d["checksum_errors"] == 7
        assert d["seq_jumps"] == 3
        assert d["a1_timeouts"] == 2
        assert d["total_nav_frames"] == 500
        assert d["total_cmd_frames"] == 490

    def test_status_includes_link_booleans(self):
        s = br.BridgeStatus()
        s.safety_reason = "timeout"
        s.cmd_rate_hz = 10.0
        handler = self._make_handler("/status", s)
        handler.do_GET()
        import json
        data = json.loads(handler.wfile.getvalue())  # type: ignore[union-attr]
        assert data["diag"]["a1_timeout"] is True
        assert data["diag"]["rdk_output_active"] is True
