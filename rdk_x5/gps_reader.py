# gps_reader.py
# RDK X5 通过串口 AT 指令读取 4G 模块 (EC200A/Air724) 的 GPS 坐标
# 用法:
#   from gps_reader import GPSReader
#   gps = GPSReader("/dev/ttyUSB2")
#   lat, lon = gps.get_location()

import serial
import time
import re
from typing import Optional, Tuple


class GPSReader:
    def __init__(self, port: str = "/dev/ttyUSB2", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None

    def open(self) -> bool:
        try:
            self.ser = serial.Serial(
                self.port, self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=3.0,
            )
            # 启用 GPS
            self._send_at("AT+QGPS=1", wait=1.0)
            print(f"[GPS] 已打开 {self.port}")
            return True
        except serial.SerialException as e:
            print(f"[GPS] 打开失败: {e}")
            return False

    def _send_at(self, cmd: str, wait: float = 0.5) -> str:
        self.ser.write((cmd + "\r\n").encode())
        time.sleep(wait)
        return self.ser.read(self.ser.in_waiting or 1024).decode(errors="ignore")

    def get_location(self) -> Tuple[Optional[float], Optional[float]]:
        """返回 (lat, lon)，失败返回 (None, None)"""
        if self.ser is None or not self.ser.is_open:
            return None, None

        resp = self._send_at("AT+QGPSLOC?", wait=1.0)

        # 解析: +QGPSLOC: 061234.0,31.2304,121.4737,1.2,50.0,2,0.0,0.0,0.0,010724,12
        m = re.search(r"\+QGPSLOC:\s*[\d.]+,([\d.-]+),([\d.-]+)", resp)
        if m:
            lat = float(m.group(1))
            lon = float(m.group(2))
            return lat, lon

        # 换一种格式: +CGPSINFO: 3123.04,N,12147.37,E,...
        m = re.search(r"\+CGPSINFO:\s*([\d.]+),([NS]),([\d.]+),([EW])", resp)
        if m:
            lat = self._nmea_to_decimal(m.group(1), m.group(2))
            lon = self._nmea_to_decimal(m.group(3), m.group(4))
            return lat, lon

        return None, None

    @staticmethod
    def _nmea_to_decimal(val: str, direction: str) -> float:
        """NMEA 度分格式 → 十进制度"""
        if not val or "." not in val:
            return 0.0
        dot = val.index(".")
        deg = float(val[:dot - 2])
        minutes = float(val[dot - 2:])
        result = deg + minutes / 60.0
        return -result if direction in ("S", "W") else result

    def close(self):
        if self.ser and self.ser.is_open:
            self._send_at("AT+QGPSEND", wait=0.5)
            self.ser.close()
            print("[GPS] 已关闭")


# 测试
if __name__ == "__main__":
    gps = GPSReader()
    if gps.open():
        try:
            for _ in range(5):
                lat, lon = gps.get_location()
                if lat and lon:
                    print(f"GPS: {lat:.6f}, {lon:.6f}")
                    break
                print("等待 GPS 定位...")
                time.sleep(2)
        finally:
            gps.close()
    else:
        print("请检查: ls /dev/ttyUSB*  或  ls /dev/ttyS*")