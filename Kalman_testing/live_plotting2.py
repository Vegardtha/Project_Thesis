# live_cpr_depth.py
# Run:  python live_cpr_depth.py --port /dev/cu.usbmodem1201 --baud 115200
#       (close Arduino Serial Monitor first)

import argparse
import math
import re
import sys
import time
import threading
import queue

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

try:
    from cpr_depth_from_angles import depth_from_two_angles
except Exception as e:
    print("ERROR: Could not import cpr_depth_from_two_angles.py:", e)
    sys.exit(1)

# ---------------- Config defaults ----------------
DEFAULT_L_MM = 240.0
DEFAULT_S_MM = 103.0
DEFAULT_BAUD = 115200

ROLL_RX = re.compile(
    r'ROLL\s*,\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)',
    re.I
)

def parse_two_angles(line: str):
    """Return (theta1_deg, theta2_deg) from a text line, or None."""
    m = ROLL_RX.search(line)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None

# ---------------- Serial reader (thread) ----------------
class SerialAnglesReader:
    """Reads 'ROLL,<a>,<b>' from serial and provides the latest pair."""
    def __init__(self, port: str, baud: int):
        self.port = port
        self.baud = baud
        self.stop = threading.Event()
        self.latest = queue.SimpleQueue()
        self.ready = threading.Event()
        self.error = None

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        return t

    def _run(self):
        try:
            import serial
            ser = serial.Serial(self.port, self.baud, timeout=0.5)
        except Exception as e:
            self.error = f"Serial open failed on {self.port}: {e}"
            return

        try:
            # Due resets on open: give it time, then clear startup noise
            time.sleep(2.5)
            ser.reset_input_buffer()
            self.ready.set()

            while not self.stop.is_set():
                try:
                    raw = ser.readline()
                except Exception:
                    continue
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                pair = parse_two_angles(line)
                if pair is None:
                    # uncomment for debugging:
                    # print("RAW:", repr(line))
                    continue
                # Keep only the newest pair
                while not self.latest.empty():
                    try:
                        self.latest.get_nowait()
                    except Exception:
                        break
                self.latest.put(pair)
        finally:
            try:
                ser.close()
            except Exception:
                pass

# ---------------- Plot & cosine rendering ----------------
def y_of(x_mm, D_mm, L_mm):
    return -0.5 * D_mm * (1.0 - np.cos(2.0 * np.pi * (x_mm / L_mm)))

class LivePlot:
    def __init__(self, L_mm: float, s_mm: float):
        self.L = float(L_mm)
        self.s = float(s_mm)

        self.x = np.linspace(0, self.L, 800)
        self.fig, self.ax = plt.subplots(figsize=(9, 4.5))
        (self.curve,) = self.ax.plot([], [], lw=2)
        (self.imu1_pt,) = self.ax.plot([], [], 'o', ms=8)
        (self.imu2_pt,) = self.ax.plot([], [], 'o', ms=8)
        (self.min_pt,)  = self.ax.plot([], [], 's', ms=6)

        self.text = self.ax.text(
            0.01, 0.98, "Waiting for data...",
            transform=self.ax.transAxes, va="top", ha="left",
            family="monospace"
        )

        self.ax.set_xlim(0, self.L)
        self.ax.set_ylim(-60, 5)
        self.ax.set_xlabel("x  [mm]")
        self.ax.set_ylabel("y  [mm]  (down is negative)")
        self.ax.grid(True, alpha=0.35)
        self.ax.set_title("CPR depth from two IMU angles (live)")

    def update_solution(self, theta1_deg: float, theta2_deg: float):
        res = depth_from_two_angles(
            theta1_deg=theta1_deg,
            theta2_deg=theta2_deg,
            s_mm=self.s,
            L_mm=self.L,
            segment_samples=400
        )
        if not res.ok:
            self.text.set_text(
                f"θ1={theta1_deg:+6.2f}°, θ2={theta2_deg:+6.2f}°\n"
                f"No solution: {res.message}"
            )
            return

        D = res.D_mm
        y = y_of(self.x, D, self.L)
        self.curve.set_data(self.x, y)

        # positions (wrap into [0, L))
        x1 = res.x1_mm % self.L
        x2 = res.x2_mm % self.L
        self.imu1_pt.set_data([x1], [res.y1_mm])
        self.imu2_pt.set_data([x2], [res.y2_mm])

        xmin = res.xmin_mm % self.L
        self.min_pt.set_data([xmin], [res.ymin_mm])

        # autoscale Y nicely around current depth
        y_margin = max(10.0, 0.15 * D)
        self.ax.set_ylim(-(D + y_margin), y_margin * 0.5)

        self.text.set_text(
            f"θ1={theta1_deg:+6.2f}°, θ2={theta2_deg:+6.2f}°\n"
            f"D={D:6.2f} mm | y1={res.y1_mm:6.2f} mm  y2={res.y2_mm:6.2f} mm\n"
            f"ymin={res.ymin_mm:6.2f} mm at x={res.xmin_mm:6.1f} mm"
        )

# ---------------- Auto-detect (optional helper) ----------------
def autodetect_mac_port():
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            dev = (p.device or "").lower()
            desc = (p.description or "").lower()
            if "usbmodem" in dev or "arduino" in desc:
                return p.device
        return None
    except Exception:
        return None

# ---------------- Main ----------------
def main():
    ap = argparse.ArgumentParser(
        description="Live CPR depth: read two IMU accRoll angles from Arduino serial, solve, and plot."
    )
    ap.add_argument("--port", "-p", help="Serial device, e.g. /dev/cu.usbmodem1201")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--L", type=float, default=DEFAULT_L_MM, help="Cosine period L (mm)")
    ap.add_argument("--s", type=float, default=DEFAULT_S_MM, help="IMU separation s (mm)")
    ap.add_argument("--swap", action="store_true", help="Swap IMU order (treat B as θ1)")
    args = ap.parse_args()

    port = args.port or autodetect_mac_port()
    if not port:
        print("No serial port specified and none auto-detected. Use --port /dev/cu.usbmodemXXXX")
        sys.exit(2)
    print(f"[Serial] Opening {port} @ {args.baud} (close Arduino Serial Monitor!)")

    reader = SerialAnglesReader(port, args.baud)
    reader_thread = reader.start()

    # wait for port open/reset
    if not reader.ready.wait(timeout=5.0):
        print("ERROR: Serial not ready.")
        if reader.error:
            print(reader.error)
        sys.exit(3)

    def serial_angles():
        last_warn = 0.0
        while True:
            if reader.error:
                raise RuntimeError(reader.error)
            if reader.latest.empty():
                # gentle warning every few seconds if nothing arrives
                if time.time() - last_warn > 3:
                    # print("Waiting for ROLL,<a>,<b> ...")
                    last_warn = time.time()
                time.sleep(0.01)
                continue
            a, b = reader.latest.get()
            yield (b, a) if args.swap else (a, b)
    angle_source = serial_angles()

    plot = LivePlot(args.L, args.s)

    def on_timer(_frame):
        try:
            # consume all pending angles, use the freshest one
            latest = None
            for _ in range(4):
                try:
                    latest = next(angle_source)
                except StopIteration:
                    break
                except Exception as e:
                    plot.text.set_text(f"Serial error: {e}")
                    return plot.curve, plot.imu1_pt, plot.imu2_pt, plot.min_pt, plot.text
            if latest is not None:
                th1, th2 = latest
                plot.update_solution(th1, th2)
        except Exception as e:
            plot.text.set_text(f"Error: {e}")
        return plot.curve, plot.imu1_pt, plot.imu2_pt, plot.min_pt, plot.text

    ani = FuncAnimation(plot.fig, on_timer, interval=40, blit=False)

    try:
        plt.show()
    finally:
        # stop serial thread if running
        try:
            reader.stop.set()  # type: ignore
        except Exception:
            pass
        if reader_thread and reader_thread.is_alive():
            reader_thread.join(timeout=1.0)

if __name__ == "__main__":
    main()
