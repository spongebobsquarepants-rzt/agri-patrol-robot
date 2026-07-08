#!/usr/bin/env python3
"""RDK X5 UART bridge for A1 field navigation.

The same RDK 40Pin UART is used in full-duplex mode:
  A1 UART0TX  -> RDK UART RX
  RDK UART TX -> lower controller UART RX

This script has no third-party dependency. It uses Linux termios directly.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import struct
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    import termios
except ModuleNotFoundError:
    termios = None


# A1 -> RDK 导航帧长度，必须与 main.cpp 的 packet[16] 保持一致。
NAV_FRAME_LEN = 16
# RDK -> 下位机控制帧长度，当前同样固定为 16 字节。
CMD_FRAME_LEN = 16
# A1 导航帧帧头：用于在串口字节流中重新同步帧边界。
NAV_HEADER = b"\xA5\x5A"
# 下位机控制帧帧头：便于下位机区分 RDK 控制命令。
CMD_HEADER = b"\xB5\x5B"

def supported_baudrates() -> dict[int, int]:
    """Return Linux termios baud constants.

    The protocol helpers are intentionally importable on Windows for offline
    tests; actual UART access still requires Linux termios on the RDK X5.
    """

    if termios is None:
        return {}
    return {
        9600: termios.B9600,
        19200: termios.B19200,
        38400: termios.B38400,
        57600: termios.B57600,
        115200: termios.B115200,
        230400: termios.B230400,
        460800: termios.B460800,
        921600: termios.B921600,
    }


class BridgeStatus:
    """Thread-safe shared state between bridge main loop and web dashboard.

    Tracks latest A1 nav frame, latest RDK control frame, and diagnostic counters.
    All public attribute writes should be protected by ``lock`` when accessed from
    multiple threads (main loop + HTTP handler thread).
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()

        # ---- A1 nav frame (latest parsed) ----
        self.latest_nav_seq: int | None = None
        self.latest_nav_valid: bool = False
        self.latest_nav_deviation_px: float = 0.0
        self.latest_nav_angle_deg: float = 0.0
        self.latest_nav_confidence_pct: int = 0
        self.latest_nav_point_count: int = 0
        self.latest_nav_bottom_x_px: int = 0
        self.latest_nav_status: int = 0
        self.latest_nav_age_ms: float = 0.0
        self.latest_nav_timestamp: float | None = None

        # ---- RDK control frame (latest sent) ----
        self.latest_cmd_seq: int = 0
        self.latest_cmd_enable: bool = False
        self.latest_cmd_valid_nav: bool = False
        self.latest_cmd_linear: int = 0
        self.latest_cmd_angular: int = 0
        self.latest_cmd_deviation_px: float = 0.0
        self.latest_cmd_mode: int = 0

        # ---- diagnostics / counters ----
        self.checksum_errors: int = 0
        self.seq_jumps: int = 0
        self.a1_timeouts: int = 0
        self.safety_reason: str = ""
        self.cmd_rate_hz: float = 0.0
        self.uptime_s: float = 0.0
        self.total_nav_frames: int = 0
        self.total_cmd_frames: int = 0
        self.start_time: float = time.monotonic()

        # ---- mutable counter ref for parse_nav_frames ----
        self._cs_err_ref: list[int] = [0]

    def snapshot(self) -> dict:
        """Return a thread-safe shallow-copy dict for JSON serialization."""
        with self.lock:
            self.uptime_s = round(time.monotonic() - self.start_time, 3)
            nav_age_ms = self.latest_nav_age_ms
            if self.latest_nav_timestamp is not None:
                nav_age_ms = (time.monotonic() - self.latest_nav_timestamp) * 1000.0
                self.latest_nav_age_ms = nav_age_ms
            return {
                "nav": {
                    "seq": self.latest_nav_seq,
                    "valid": self.latest_nav_valid,
                    "deviation_px": self.latest_nav_deviation_px,
                    "angle_deg": self.latest_nav_angle_deg,
                    "confidence_pct": self.latest_nav_confidence_pct,
                    "point_count": self.latest_nav_point_count,
                    "bottom_x_px": self.latest_nav_bottom_x_px,
                    "status": self.latest_nav_status,
                    "age_ms": nav_age_ms,
                },
                "cmd": {
                    "seq": self.latest_cmd_seq,
                    "enable": self.latest_cmd_enable,
                    "valid_nav": self.latest_cmd_valid_nav,
                    "linear_mm_s": self.latest_cmd_linear,
                    "angular_mrad_s": self.latest_cmd_angular,
                    "deviation_px": self.latest_cmd_deviation_px,
                    "mode": self.latest_cmd_mode,
                },
                "diag": {
                    "checksum_errors": self.checksum_errors,
                    "seq_jumps": self.seq_jumps,
                    "a1_timeouts": self.a1_timeouts,
                    "safety_reason": self.safety_reason,
                    "safety_state": safety_state_from_reason(self.safety_reason),
                    "a1_timeout": self.safety_reason == "timeout",
                    "rdk_output_active": self.cmd_rate_hz > 0.0,
                    "cmd_rate_hz": self.cmd_rate_hz,
                    "uptime_s": self.uptime_s,
                    "total_nav_frames": self.total_nav_frames,
                    "total_cmd_frames": self.total_cmd_frames,
                },
            }


@dataclass
class NavFrame:
    """A1 导航帧的结构化结果。

    字段来自 16 字节协议帧：seq 用于观察丢帧，valid/status/confidence 用于安全判定，
    deviation_px/angle_deg/bottom_x_px 用于计算 RDK 输出给下位机的线速度和角速度。
    """

    seq: int
    valid: bool
    deviation_px: float
    angle_deg: float
    confidence_pct: int
    point_count: int
    bottom_x_px: int
    status: int
    timestamp: float


def checksum15(frame: bytes) -> int:
    """计算协议校验和。

    输入 frame 至少 15 字节；输出为前 15 字节累加后的低 8 位。
    使用注意：A1 导航帧和 RDK 控制帧共用该校验规则。
    """

    return sum(frame[:15]) & 0xFF


def clamp(value: float, low: float, high: float) -> float:
    """把 value 限制在 [low, high]，用于速度和协议 int16 字段防溢出。"""

    return max(low, min(high, value))


def open_uart(path: str, baudrate: int) -> int:
    """打开并配置 RDK 侧 UART。

    输入 path 为 /dev/ttyS* 等设备，baudrate 为 BAUD_MAP 支持值。
    输出为非阻塞 fd；异常表示设备不存在、权限不足或波特率不支持。
    """

    baud_map = supported_baudrates()
    if termios is None:
        raise RuntimeError("Linux termios is required to open UART; run this script on RDK X5 Linux")
    if baudrate not in baud_map:
        raise ValueError(f"unsupported baudrate: {baudrate}")

    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    baud = baud_map[baudrate]

    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = baud
    attrs[5] = baud
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def parse_nav_frames(buffer: bytearray, cs_err: list[int] | None = None) -> list[NavFrame]:
    """从串口接收缓冲区中解析完整 A1 导航帧。

    输入 buffer 会被原地消费；输出为本次解析出的 NavFrame 列表。
    实现原理：查找 A5 5A 帧头，长度够 16 字节后校验 checksum，坏帧直接丢弃并继续同步。

    可选参数 cs_err 是一个单元素 list[int]，当不为 None 时，每次 checksum
    错误会递增 cs_err[0]，供上层统计丢帧率。
    """

    frames: list[NavFrame] = []
    while True:
        start = buffer.find(NAV_HEADER)
        if start < 0:
            del buffer[:-1]
            return frames
        if start > 0:
            del buffer[:start]
        if len(buffer) < NAV_FRAME_LEN:
            return frames

        raw = bytes(buffer[:NAV_FRAME_LEN])
        del buffer[:NAV_FRAME_LEN]
        if checksum15(raw) != raw[15]:
            if cs_err is not None:
                cs_err[0] += 1
            continue

        seq = raw[4] | (raw[5] << 8)
        deviation_x10 = struct.unpack_from("<h", raw, 6)[0]
        angle_x100 = struct.unpack_from("<h", raw, 8)[0]
        bottom_x = raw[12] | (raw[13] << 8)
        frames.append(
            NavFrame(
                seq=seq,
                valid=(raw[3] & 0x01) != 0,
                deviation_px=deviation_x10 / 10.0,
                angle_deg=angle_x100 / 100.0,
                confidence_pct=raw[10],
                point_count=raw[11],
                bottom_x_px=bottom_x,
                status=raw[14],
                timestamp=time.monotonic(),
            )
        )


def make_command_frame(
    seq: int,
    enable: bool,
    valid_nav: bool,
    linear_v_mm_s: int,
    angular_w_mrad_s: int,
    deviation_px: float,
    mode: int,
) -> bytes:
    """生成 RDK 发给下位机的 16 字节控制帧。

    输入 seq/enable/valid_nav/速度/偏差/mode；输出 bytes。
    使用注意：线速度单位为 mm/s，角速度单位为 mrad/s，偏差按 px*10 写入 int16。
    """

    packet = bytearray(CMD_FRAME_LEN)
    packet[0:2] = CMD_HEADER
    packet[2] = 0x01
    packet[3] = (0x01 if enable else 0x00) | (0x02 if valid_nav else 0x00)
    struct.pack_into("<H", packet, 4, seq & 0xFFFF)
    struct.pack_into("<h", packet, 6, int(clamp(linear_v_mm_s, -32768, 32767)))
    struct.pack_into("<h", packet, 8, int(clamp(angular_w_mrad_s, -32768, 32767)))
    struct.pack_into("<h", packet, 10, int(clamp(round(deviation_px * 10.0), -32768, 32767)))
    packet[12] = mode & 0xFF
    packet[13] = 0
    packet[14] = 0
    packet[15] = checksum15(packet)
    return bytes(packet)


def compute_control(nav: NavFrame | None, args: argparse.Namespace) -> tuple[bool, bool, int, int, float, int, str]:
    """把最近一帧 A1 导航数据转换为下位机速度命令。

    输入 nav 可为空，args 提供阈值和比例参数；输出
    (enable, valid_nav, linear, angular, deviation, mode, safety_reason)。
    安全策略：无帧、超时、低置信度或 A1 status 非 0 时全部输出停车。
    safety_reason 为人类可读的字符串，用于 web 仪表盘显示。
    """

    if nav is None:
        return False, False, 0, 0, 0.0, 2, "no_frame"

    age = time.monotonic() - nav.timestamp
    if age > args.timeout:
        return False, False, 0, 0, nav.deviation_px, 2, "timeout"
    if not nav.valid:
        return False, False, 0, 0, nav.deviation_px, 2, "invalid_flag"
    if nav.status != 0:
        return False, False, 0, 0, nav.deviation_px, 2, "status_error"
    if nav.confidence_pct < args.min_confidence:
        return False, False, 0, 0, nav.deviation_px, 2, "low_confidence"

    # 简单 P 控制：横向偏差和航向角共同决定角速度，下位机只执行 RDK 的最终控制帧。
    angular = args.kp_dev * nav.deviation_px + args.kp_ang * nav.angle_deg
    angular = int(clamp(round(angular), -args.max_angular, args.max_angular))
    linear = args.linear
    slowed = abs(nav.deviation_px) > args.slow_dev or abs(nav.angle_deg) > args.slow_angle
    if slowed:
        linear = int(linear * 0.5)
    reason = "slow_speed" if slowed else "ok"
    return True, True, int(linear), angular, nav.deviation_px, 1, reason


def safety_state_from_reason(reason: str) -> str:
    """Map internal control reasons to operator-facing dashboard states."""

    if reason in ("ok", "slow_speed"):
        return "TRACK"
    if reason == "timeout":
        return "STOP_TIMEOUT"
    if reason == "low_confidence":
        return "STOP_LOW_CONF"
    if reason == "status_error":
        return "STOP_STATUS_ERR"
    return "STOP_NO_NAV"


def parse_web_endpoint(value: str) -> tuple[str, int]:
    """Parse --web HOST:PORT into host and port."""

    host_part, sep, port_part = value.rpartition(":")
    if sep != ":" or not host_part or not port_part:
        raise ValueError("expected HOST:PORT")
    host = host_part.strip("[]")
    if not host:
        raise ValueError("host is empty")
    port = int(port_part)
    if port < 1 or port > 65535:
        raise ValueError("port out of range")
    return host, port


# ---------------------------------------------------------------------------
# Web dashboard (pure stdlib, no third-party deps)
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>田间道路导航监控台 | RDK X5 Bridge Dashboard</title>
<style>
  :root{
    --bg:#10120f;--panel:#191d18;--panel-2:#222720;--line:#3b4637;
    --text:#eef4e8;--muted:#a5af9d;--green:#52d273;--amber:#f4b740;
    --red:#ff5c5c;--cyan:#73d2de;--blue:#8fb7ff;
  }
  *{box-sizing:border-box}
  body{font-family:Consolas,"Microsoft YaHei UI","Microsoft YaHei",monospace;background:var(--bg);color:var(--text);margin:0;padding:14px}
  h1{margin:0;font-size:20px;line-height:1.2;color:var(--text);letter-spacing:0}
  .sub{color:var(--muted);font-size:12px;margin-top:6px}
  .layout-shell{max-width:1280px;margin:0 auto;display:grid;gap:12px}
  .topbar{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:14px;border:1px solid var(--line);border-radius:8px;background:linear-gradient(135deg,#171b16 0%,#1f241d 100%)}
  .status-strip{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:8px;min-width:520px}
  .strip-cell{border:1px solid var(--line);border-radius:6px;background:#11150f;padding:8px 10px}
  .strip-label{display:block;color:var(--muted);font-size:11px;margin-bottom:4px}
  .strip-value{font-size:16px;font-weight:700}
  .panel-grid{display:grid;grid-template-columns:1.1fr 1fr;gap:12px}
  .side-grid{display:grid;grid-template-columns:1fr;gap:12px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px;min-width:0}
  .card h2{font-size:14px;color:var(--text);margin:0 0 10px 0;display:flex;align-items:center;gap:8px}
  .tag{font-size:10px;color:#0f130d;background:var(--green);border-radius:4px;padding:2px 6px}
  table{width:100%;border-collapse:collapse;table-layout:fixed}
  td{padding:7px 4px;font-size:13px;border-bottom:1px solid #2a3228}
  td.k{color:var(--muted);white-space:nowrap}
  td.v{text-align:right;color:var(--text);font-weight:700;overflow-wrap:anywhere}
  .ok{color:var(--green)}.warn{color:var(--amber)}.err{color:var(--red)}.info{color:var(--cyan)}
  .diag-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .diag-item{background:var(--panel-2);border:1px solid var(--line);border-radius:6px;padding:10px;text-align:center;min-height:72px}
  .diag-item .val{font-size:24px;font-weight:800;line-height:1.1}
  .diag-item .lbl{font-size:11px;color:var(--muted);margin-top:6px}
  #reason{font-size:24px;font-weight:800;padding:14px 16px;border-radius:8px;display:block;text-align:center;border:1px solid var(--line);margin-bottom:8px}
  #reason.ok{background:#12291a;color:var(--green);border-color:#245b34}
  #reason.warn{background:#33270f;color:var(--amber);border-color:#6b501c}
  #reason.err{background:#301313;color:var(--red);border-color:#74302f}
  .timeline{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .timeline div{border:1px solid var(--line);border-radius:6px;padding:10px;background:#11150f}
  .timeline strong{display:block;color:var(--blue);font-size:13px;margin-bottom:4px}
  .timeline span{color:var(--muted);font-size:11px}
  @media (max-width:900px){
    body{padding:10px}
    .topbar{display:grid}
    .status-strip{min-width:0;grid-template-columns:repeat(2,1fr)}
    .panel-grid{grid-template-columns:1fr}
    .timeline{grid-template-columns:1fr}
  }
</style>
</head>
<body>
<div class="layout-shell">
<header class="topbar">
  <div>
    <h1>田间道路导航监控台</h1>
    <div class="sub">RDK X5 Bridge Dashboard - Python 标准库 HTTP 服务 - 数据保持 500ms，便于观察变化</div>
  </div>
  <div class="status-strip">
    <div class="strip-cell"><span class="strip-label">安全状态</span><span class="strip-value" id="status-state">--</span></div>
    <div class="strip-cell"><span class="strip-label">导航帧年龄</span><span class="strip-value" id="update-age">-- ms</span></div>
    <div class="strip-cell"><span class="strip-label">控制输出</span><span class="strip-value" id="cmd-rate-top">-- Hz</span></div>
    <div class="strip-cell"><span class="strip-label">网页刷新</span><span class="strip-value">500 ms</span></div>
  </div>
</header>
<main class="panel-grid">
  <div class="card" id="nav-card">
    <h2>A1 导航帧 <span class="tag">A5 5A</span></h2>
    <table id="nav-table"></table>
  </div>
  <div class="side-grid">
    <div class="card" id="cmd-card">
      <h2>RDK 控制帧 <span class="tag">B5 5B</span></h2>
      <table id="cmd-table"></table>
    </div>
    <div class="card">
      <h2>链路流程</h2>
      <div class="timeline">
        <div><strong>A1 视觉</strong><span>分割道路并输出 NavLine</span></div>
        <div><strong>RDK 判定</strong><span>校验、限幅和安全停车</span></div>
        <div><strong>下位机</strong><span>执行 B5 5B 控制帧</span></div>
      </div>
    </div>
  </div>
</main>
<section class="panel-grid">
  <div class="card">
    <h2>链路诊断</h2>
    <div class="diag-grid" id="diag-grid"></div>
  </div>
  <div class="card">
    <h2>安全状态</h2>
    <div id="reason" class="err">加载中...</div>
    <table id="safety-table" style="margin-top:8px"></table>
  </div>
</section>
</div>
<script>
const REFRESH_INTERVAL_MS = 500;
let inFlight = false;
function yesNo(value){return value?'是':'否'}
function stateText(state){
  return {
    TRACK:'循迹中',
    STOP_TIMEOUT:'停车: A1 超时',
    STOP_LOW_CONF:'停车: 低置信度',
    STOP_STATUS_ERR:'停车: A1 状态异常',
    STOP_NO_NAV:'停车: 无有效导航'
  }[state] || state || '--';
}
function render(){
  if(inFlight)return;
  inFlight=true;
  fetch('/status').then(r=>r.json()).then(s=>{
    let n=s.nav, c=s.cmd, d=s.diag;
    let state=d.safety_state||'STOP_NO_NAV';
    let reason=d.safety_reason||'--';
    let rcls='err';
    if(state==='TRACK')rcls=reason==='slow_speed'?'warn':'ok';
    document.getElementById('status-state').textContent=stateText(state);
    document.getElementById('status-state').className='strip-value '+rcls;
    document.getElementById('update-age').textContent=`${n.age_ms.toFixed(0)} ms`;
    document.getElementById('cmd-rate-top').textContent=`${d.cmd_rate_hz.toFixed(1)} Hz`;
    document.getElementById('nav-table').innerHTML=
      `<tr><td class="k">序号 seq</td><td class="v">${n.seq??'--'}</td></tr>
       <tr><td class="k">有效 valid</td><td class="v ${n.valid?'ok':'err'}">${yesNo(n.valid)}</td></tr>
       <tr><td class="k">横向偏差 deviation</td><td class="v">${n.deviation_px.toFixed(1)}&nbsp;px</td></tr>
       <tr><td class="k">航向角 angle</td><td class="v">${n.angle_deg.toFixed(2)}&deg;</td></tr>
       <tr><td class="k">置信度 confidence</td><td class="v">${n.confidence_pct}%</td></tr>
       <tr><td class="k">导航点 points</td><td class="v">${n.point_count}</td></tr>
       <tr><td class="k">底部中心 bottom_x</td><td class="v">${n.bottom_x_px}&nbsp;px</td></tr>
       <tr><td class="k">A1 状态 status</td><td class="v ${n.status==0?'ok':'err'}">${n.status}</td></tr>
       <tr><td class="k">帧年龄 age</td><td class="v">${n.age_ms.toFixed(0)}&nbsp;ms</td></tr>`;
    document.getElementById('cmd-table').innerHTML=
      `<tr><td class="k">序号 seq</td><td class="v">${c.seq}</td></tr>
       <tr><td class="k">使能 enable</td><td class="v ${c.enable?'ok':'err'}">${yesNo(c.enable)}</td></tr>
       <tr><td class="k">导航有效 valid_nav</td><td class="v ${c.valid_nav?'ok':'err'}">${yesNo(c.valid_nav)}</td></tr>
       <tr><td class="k">线速度 linear</td><td class="v">${c.linear_mm_s}&nbsp;mm/s</td></tr>
       <tr><td class="k">角速度 angular</td><td class="v">${c.angular_mrad_s}&nbsp;mrad/s</td></tr>
       <tr><td class="k">偏差回传 deviation</td><td class="v">${c.deviation_px.toFixed(1)}&nbsp;px</td></tr>
       <tr><td class="k">模式 mode</td><td class="v">${c.mode}</td></tr>`;
    let re=document.getElementById('reason');
    re.textContent=stateText(state);
    re.className=rcls;
    document.getElementById('safety-table').innerHTML=
      `<tr><td class="k">原因 reason</td><td class="v">${reason}</td></tr>
       <tr><td class="k">A1 超时 a1_timeout</td><td class="v ${d.a1_timeout?'err':'ok'}">${yesNo(d.a1_timeout)}</td></tr>
       <tr><td class="k">RDK 输出 rdk_output</td><td class="v ${d.rdk_output_active?'ok':'err'}">${d.rdk_output_active?'输出中':'已停止'}</td></tr>
       <tr><td class="k">超时次数</td><td class="v ${d.a1_timeouts?'err':'ok'}">${d.a1_timeouts}</td></tr>
       <tr><td class="k">序号跳变</td><td class="v ${d.seq_jumps?'warn':'ok'}">${d.seq_jumps}</td></tr>
       <tr><td class="k">校验错误</td><td class="v ${d.checksum_errors?'err':'ok'}">${d.checksum_errors}</td></tr>
       <tr><td class="k">导航帧总数</td><td class="v">${d.total_nav_frames}</td></tr>
       <tr><td class="k">控制帧总数</td><td class="v">${d.total_cmd_frames}</td></tr>`;
    document.getElementById('diag-grid').innerHTML=
      `<div class="diag-item"><div class="val ${d.cmd_rate_hz?'ok':'err'}">${d.cmd_rate_hz.toFixed(1)}</div><div class="lbl">控制频率 CMD Hz</div></div>
       <div class="diag-item"><div class="val info">${d.uptime_s.toFixed(0)}</div><div class="lbl">运行时间 s</div></div>
       <div class="diag-item"><div class="val ${d.checksum_errors?'err':'ok'}">${d.checksum_errors}</div><div class="lbl">校验错误 CS</div></div>`;
  }).catch(e=>{document.getElementById('reason').textContent='FETCH ERROR';})
    .finally(()=>{inFlight=false;});
}
setInterval(render, REFRESH_INTERVAL_MS);
render();
</script>
</body>
</html>"""


class BridgeHTTPHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler: / returns dashboard HTML, /status returns JSON.

    The handler reads from a shared :class:`BridgeStatus` object set on the
    server instance (``server.bridge_status``).
    """

    # Silence per-request log to stderr in production; enable for debugging.
    def log_message(self, format, *args):  # noqa: A002
        pass

    def _status_json(self) -> bytes:
        status: BridgeStatus = self.server.bridge_status  # type: ignore[attr-defined]
        payload = json.dumps(status.snapshot(), ensure_ascii=False)
        return payload.encode("utf-8")

    def do_GET(self) -> None:
        if self.path == "/status":
            body = self._status_json()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/", "/dashboard"):
            body = _DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b'{"error":"not found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def start_web_server(host: str, port: int, status: BridgeStatus) -> HTTPServer:
    """Start a blocking HTTP server on *host:port* serving the bridge dashboard.

    In production this is called from a daemon thread so the main bridge loop
    can continue running.
    """
    server = HTTPServer((host, port), BridgeHTTPHandler)
    server.bridge_status = status  # type: ignore[attr-defined]
    server.serve_forever()
    return server


def main() -> int:
    """RDK 桥接主循环。

    负责打开 UART、持续解析 A1 导航帧、按固定频率输出控制帧，并在退出时发送停车帧。
    """

    parser = argparse.ArgumentParser(description="RDK X5 bridge: A1 nav UART -> lower controller command UART")
    parser.add_argument("--port", required=True, help="RDK 40Pin UART device, for example /dev/ttyS1")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=0.3, help="A1 nav timeout in seconds")
    parser.add_argument("--linear", type=int, default=150, help="track mode linear speed, mm/s")
    parser.add_argument("--kp-dev", type=float, default=-2.0, help="mrad/s per pixel deviation")
    parser.add_argument("--kp-ang", type=float, default=-20.0, help="mrad/s per degree heading angle")
    parser.add_argument("--max-angular", type=int, default=800, help="angular speed clamp, mrad/s")
    parser.add_argument("--min-confidence", type=int, default=30, help="minimum A1 confidence percent")
    parser.add_argument("--slow-dev", type=float, default=180.0)
    parser.add_argument("--slow-angle", type=float, default=15.0)
    parser.add_argument("--web", type=str, default=None, metavar="HOST:PORT",
                        help="enable web dashboard on HOST:PORT (e.g. 0.0.0.0:8080)")
    args = parser.parse_args()

    # Parse --web HOST:PORT
    web_host: str | None = None
    web_port: int = 0
    if args.web:
        try:
            web_host, web_port = parse_web_endpoint(args.web)
        except (ValueError, TypeError) as exc:
            print(f"[rdk_nav] invalid --web value '{args.web}': {exc}", file=sys.stderr)
            return 1

    stop = False

    def handle_signal(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    fd = open_uart(args.port, args.baud)
    print(f"[rdk_nav] opened {args.port} baud={args.baud} rate={args.rate}Hz", flush=True)

    rx_buffer = bytearray()  # 串口接收缓冲，parse_nav_frames 会原地消费完整帧。
    last_nav: NavFrame | None = None  # 最近一帧有效格式的 A1 导航数据。
    next_send = time.monotonic()  # 下一次发送下位机控制帧的时间点。
    interval = 1.0 / max(args.rate, 1.0)  # RDK 输出控制帧周期，最低按 1Hz 防止除零。
    cmd_seq = 0  # RDK 控制帧序号，16 位循环。
    last_report = time.monotonic()  # 人类可读诊断日志的上次打印时间。

    # ---- shared state for web dashboard ----
    status = BridgeStatus()
    _last_seq: int | None = None  # track seq for jump detection
    _last_reason: str = "--"  # last safety reason for console log

    # ---- start optional web server in daemon thread ----
    web_thread: threading.Thread | None = None
    if web_host and web_port:
        web_thread = threading.Thread(
            target=start_web_server,
            args=(web_host, web_port, status),
            daemon=True,
            name="rdk-web",
        )
        web_thread.start()
        print(f"[rdk_nav] web dashboard on http://{web_host}:{web_port}", flush=True)

    # ---- track control rate via rolling timestamps ----
    _cmd_send_times: list[float] = []  # rolling window of last N send timestamps

    try:
        while not stop:
            now = time.monotonic()
            timeout = max(0.0, min(0.02, next_send - now))
            # select 控制阻塞时间：既及时读 A1 串口，也保证按 rate 周期发送控制帧。
            readable, _, _ = select.select([fd], [], [], timeout)
            if readable:
                try:
                    chunk = os.read(fd, 128)
                    if chunk:
                        rx_buffer.extend(chunk)
                        for frame in parse_nav_frames(rx_buffer, status._cs_err_ref):
                            # seq jump detection
                            if _last_seq is not None:
                                expected = (_last_seq + 1) & 0xFFFF
                                if frame.seq != expected:
                                    status.seq_jumps += 1
                            _last_seq = frame.seq
                            last_nav = frame
                            status.total_nav_frames += 1
                            # update web status: nav frame
                            with status.lock:
                                status.latest_nav_seq = frame.seq
                                status.latest_nav_valid = frame.valid
                                status.latest_nav_deviation_px = frame.deviation_px
                                status.latest_nav_angle_deg = frame.angle_deg
                                status.latest_nav_confidence_pct = frame.confidence_pct
                                status.latest_nav_point_count = frame.point_count
                                status.latest_nav_bottom_x_px = frame.bottom_x_px
                                status.latest_nav_status = frame.status
                                status.latest_nav_timestamp = frame.timestamp
                                status.latest_nav_age_ms = (now - frame.timestamp) * 1000.0
                except BlockingIOError:
                    pass

            # copy checksum error count from mutable ref
            status.checksum_errors = status._cs_err_ref[0]

            now = time.monotonic()
            if now >= next_send:
                # 每个周期都发送控制帧；无有效导航时 compute_control 会返回停车命令。
                enable, valid_nav, linear, angular, deviation, mode, reason = compute_control(last_nav, args)
                _last_reason = reason
                packet = make_command_frame(cmd_seq, enable, valid_nav, linear, angular, deviation, mode)
                os.write(fd, packet)
                cmd_seq = (cmd_seq + 1) & 0xFFFF
                next_send = now + interval

                # track control rate
                _cmd_send_times.append(now)
                # keep last 20 samples (~2 s at 10 Hz)
                while len(_cmd_send_times) > 20:
                    _cmd_send_times.pop(0)

                status.total_cmd_frames += 1
                with status.lock:
                    status.latest_cmd_seq = (cmd_seq - 1) & 0xFFFF
                    status.latest_cmd_enable = enable
                    status.latest_cmd_valid_nav = valid_nav
                    status.latest_cmd_linear = linear
                    status.latest_cmd_angular = angular
                    status.latest_cmd_deviation_px = deviation
                    status.latest_cmd_mode = mode
                    status.safety_reason = reason
                    if reason == "timeout":
                        status.a1_timeouts += 1
                    # compute rolling control rate
                    if len(_cmd_send_times) >= 2:
                        elapsed = _cmd_send_times[-1] - _cmd_send_times[0]
                        if elapsed > 0:
                            status.cmd_rate_hz = round((len(_cmd_send_times) - 1) / elapsed, 1)
                    status.uptime_s = round(now - status.start_time, 3)

            if now - last_report >= 1.0:
                if last_nav is None:
                    print("[rdk_nav] no A1 nav frame yet, sending stop", flush=True)
                else:
                    age_ms = (now - last_nav.timestamp) * 1000.0
                    print(
                        "[rdk_nav] nav seq={} valid={} dev={:.1f}px angle={:.2f}deg conf={} age={:.0f}ms reason={}".format(
                            last_nav.seq,
                            1 if last_nav.valid else 0,
                            last_nav.deviation_px,
                            last_nav.angle_deg,
                            last_nav.confidence_pct,
                            age_ms,
                            _last_reason,
                        ),
                        flush=True,
                    )
                last_report = now
    finally:
        # 无论异常还是 Ctrl+C 退出，都尽量先发停车帧，降低下位机继续运动风险。
        stop_packet = make_command_frame(cmd_seq, False, False, 0, 0, 0.0, 0)
        try:
            os.write(fd, stop_packet)
        except OSError:
            pass
        os.close(fd)
        print("[rdk_nav] closed, stop frame sent", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
