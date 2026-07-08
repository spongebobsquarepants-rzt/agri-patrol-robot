# Lower Controller v/w Control Frame Reference

This document describes the RDK X5 -> lower controller control frame protocol
from the lower computer's perspective. The lower computer (e.g. STM32, Arduino,
or other MCU) receives 16-byte control frames via UART and executes PID
closed-loop speed control based on the target v (linear velocity) and w
(angular velocity).

## Hardware Link

```
A1 UART0TX (1.8V) --> level shifter --> RDK X5 40Pin Pin10 / UART_RXD (3.3V)
RDK X5 40Pin Pin8 / UART_TXD (3.3V) --> lower controller UART_RX
A1 GND --- RDK X5 GND --- lower controller GND  (common ground mandatory)
```

- Baud rate: 115200 8N1 (configurable via `--baud` on RDK)
- Frame rate: default 10 Hz (configurable via `--rate`)
- Level: RDK X5 outputs 3.3V TTL; ensure lower controller UART is 3.3V-tolerant

## Control Frame Format (RDK -> Lower Controller)

Each frame is exactly **16 bytes**, sent continuously at the configured rate.
When there is no valid navigation, RDK still sends frames — but with
`enable=0` and `mode=2`, so the lower controller knows the link is alive but
should hold position.

```
Offset  Size  Field            Type     Description
------  ----  -----            ----     -----------
 0       2    header           u8[2]   0xB5 0x5B  (magic)
 2       1    version          u8      0x01
 3       1    flags            u8      bit0=enable, bit1=valid_nav
 4       2    seq              u16 LE  frame counter, wraps at 65535
 6       2    linear_v_mm_s    i16 LE  target linear velocity in mm/s
 8       2    angular_w_mrad_s i16 LE  target angular velocity in mrad/s
10       2    deviation_px10   i16 LE  deviation_px * 10 (diagnostic)
12       1    mode             u8      0=exit, 1=track, 2=safety_stop
13       2    reserved         u8[2]   always 0
15       1    checksum         u8      sum(bytes[0..14]) & 0xFF
```

### Mode Definitions

| mode | Name        | Meaning                                      |
|------|-------------|----------------------------------------------|
|  0   | exit_stop   | Bridge shutting down; stop immediately       |
|  1   | track       | Normal tracking; use v/w if enable && valid  |
|  2   | safety_stop | Nav lost/timeout/low-confidence; stop safely |

### Flags (byte 3)

| Bit | Name       | Meaning                                       |
|-----|------------|-----------------------------------------------|
| 0   | enable     | RDK authorises motion                         |
| 1   | valid_nav  | A1 navigation data is valid and recent        |
| 2-7 | reserved   |                                                |

## Lower Controller Safety Rules (MANDATORY)

The lower controller **must** enforce these rules. Ignoring any of them can
result in uncontrolled motion.

1. **Header check**: Only process frames where bytes 0-1 equal `0xB5 0x5B`.
   Discard any frame with a different header.

2. **Checksum verification**: Compute `sum(bytes[0..14]) & 0xFF` and compare
   with byte 15. Discard frames that fail checksum.

3. **Motion guard**: Only apply motor output when **all** of these hold:
   - `enable == 1` (bit 0 of `flags`)
   - `valid_nav == 1` (bit 1 of `flags`)
   - `mode == 1` (track mode)
   - `linear_v_mm_s` and `angular_w_mrad_s` are within hardware safety limits

4. **Watchdog timeout**: If no valid control frame (enable=1, valid_nav=1,
   mode=1, checksum OK) is received within **500 ms**, immediately stop all
   motors and enter safe state. Reset the watchdog on every valid track frame.

5. **On mode=0 or mode=2**: Stop motors immediately regardless of enable flag.

6. **Speed limiting**: Hardware-enforce maximum safe linear velocity and
   angular velocity. The RDK clamps to int16 range, but the lower controller
   should add its own physical safety limits.

## PID Integration Notes

The lower controller receives **target** v (linear velocity, mm/s) and w
(angular velocity, mrad/s). It should use its own encoder-based PID to
achieve these targets.

### Differential Drive Conversion

For a differential drive robot with wheel_base (distance between wheels,
in mm) and wheel_radius (in mm):

```python
# Convert target v/w to left/right wheel speeds
v_left_target  = v_target - w_target * wheel_base / 2000.0  # mm/s
v_right_target = v_target + w_target * wheel_base / 2000.0  # mm/s

# Convert to motor RPM or encoder ticks/s based on your hardware
# wheel_circumference = 2 * pi * wheel_radius  (mm)
# left_rpm  = v_left_target  * 60.0 / wheel_circumference
# right_rpm = v_right_target * 60.0 / wheel_circumference
```

Note: `w_target` is in **mrad/s**. The factor `2000.0` comes from
`2 * 1000` (2 wheels * mrad conversion). More precisely:
`v_diff = w_target * (wheel_base / 2.0) / 1000.0`.

### Ackermann Steering

For Ackermann-steered vehicles, use the bicycle model:
- `steering_angle = atan2(wheel_base * w_target / 1000.0, v_target)`
  (when v_target != 0)
- `v_target` controls rear wheel speed

### Without Encoders

If the lower controller has no encoders, use open-loop PWM mapping:
- Map `linear_v_mm_s` to a base PWM duty cycle
- Map `angular_w_mrad_s` to a differential PWM offset
- This is less accurate but functional for basic navigation

## Reference Parser (Python)

```python
import struct

CMD_HEADER = b"\xB5\x5B"


def parse_ctrl_frame(raw: bytes) -> dict | None:
    """Parse and validate a 16-byte control frame.
    Returns None if invalid; otherwise returns a dict with all fields.
    This is the exact logic the lower computer should implement in its
    native language (C, C++, MicroPython, etc.).
    """
    if len(raw) < 16:
        return None
    if raw[:2] != CMD_HEADER:
        return None
    cs = sum(raw[:15]) & 0xFF
    if cs != raw[15]:
        return None
    return {
        "version": raw[2],
        "enable": bool(raw[3] & 0x01),
        "valid_nav": bool(raw[3] & 0x02),
        "seq": struct.unpack_from("<H", raw, 4)[0],
        "v_mm_s": struct.unpack_from("<h", raw, 6)[0],
        "w_mrad_s": struct.unpack_from("<h", raw, 8)[0],
        "deviation_px": struct.unpack_from("<h", raw, 10)[0] / 10.0,
        "mode": raw[12],
    }


def should_move(frame: dict) -> bool:
    """Return True only when the lower controller should drive motors."""
    return (
        frame is not None
        and frame["enable"]
        and frame["valid_nav"]
        and frame["mode"] == 1
    )


# Example: lower controller main loop (pseudocode)
# last_valid_time = now()
# while True:
#     frame = read_uart_bytes_until_16()
#     parsed = parse_ctrl_frame(frame)
#     if should_move(parsed):
#         set_motor_targets(parsed["v_mm_s"], parsed["w_mrad_s"])
#         last_valid_time = now()
#     else:
#         stop_motors()
#     if now() - last_valid_time > 500_ms:
#         stop_motors()
```

## C Reference (for embedded MCUs)

```c
#include <stdint.h>
#include <stdbool.h>

#define CMD_HEADER_0  0xB5
#define CMD_HEADER_1  0x5B
#define CMD_FRAME_LEN 16
#define WATCHDOG_MS   500

typedef struct {
    uint8_t  version;
    bool     enable;
    bool     valid_nav;
    uint16_t seq;
    int16_t  v_mm_s;
    int16_t  w_mrad_s;
    int16_t  deviation_px10;
    uint8_t  mode;
} ctrl_frame_t;

// Returns true if frame is valid; fills *out on success.
bool parse_ctrl_frame(const uint8_t raw[16], ctrl_frame_t *out) {
    if (raw[0] != CMD_HEADER_0 || raw[1] != CMD_HEADER_1)
        return false;

    uint8_t cs = 0;
    for (int i = 0; i < 15; i++) cs += raw[i];
    if (cs != raw[15])
        return false;

    out->version        = raw[2];
    out->enable         = raw[3] & 0x01;
    out->valid_nav      = raw[3] & 0x02;
    out->seq            = raw[4] | (raw[5] << 8);
    out->v_mm_s         = (int16_t)(raw[6] | (raw[7] << 8));
    out->w_mrad_s       = (int16_t)(raw[8] | (raw[9] << 8));
    out->deviation_px10 = (int16_t)(raw[10] | (raw[11] << 8));
    out->mode           = raw[12];
    return true;
}

// Only drive motors when this returns true.
bool should_move(const ctrl_frame_t *f) {
    return f != NULL && f->enable && f->valid_nav && f->mode == 1;
}
```

## Testing

The protocol is covered by automated Python tests in
`field_nav_external/tests/test_rdk_bridge.py`. Key test classes:

- `TestMakeCommandFrame` — control frame packing and field encoding
- `TestParseNavFrames` — A1 nav frame byte-stream parsing
- `TestComputeControl` — safety stop logic (timeout, confidence, status)
- `TestLowerControllerReference` — round-trip parsing and safety rule
  enforcement (doubles as lower computer reference implementation)
- `TestEndToEnd` — full A1->RDK->lower controller pipeline simulation

Run tests with:

```bash
cd field_nav_external
python -m pytest tests/ -q
```

## Quick Reference Card

```
RDK outputs 16-byte frames on UART TX at 10 Hz (default)

  [B5 5B] [01] [flags] [seq:2] [v:mm/s:2] [w:mrad/s:2] [dev*10:2] [mode] [00 00] [cs]

Motion conditions:  header==B5 5B  AND  checksum OK
                    AND  enable==1  AND  valid_nav==1  AND  mode==1

Stop conditions:    mode==2  OR  enable==0  OR  valid_nav==0
                    OR  bad checksum  OR  bad header  OR  watchdog>500ms
```

## See Also

- `AGENTS.md` — full project constraints and UART/GPIO notes
- `field_nav_external/scripts/rdk_x5_nav_bridge.py` — RDK X5 bridge source
- `field_nav_external/src/field_nav_demo/src/main.cpp` — A1 nav frame packing
- `field_nav_external/README.md` — build and run instructions
