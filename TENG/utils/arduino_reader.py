"""
Arduino serial reader for TENG experiments.
Parses STATUS and IMPACT messages from the motor controller in a background thread.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import serial
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False


@dataclass
class ArduinoState:
    position_cm: float = 0.0
    direction: str = "idle"


@dataclass
class ImpactData:
    peak_g: float = 0.0
    position_cm: float = 0.0
    timestamp: float = field(default_factory=time.time)


class ArduinoReader:
    """
    Reads structured serial messages from the Arduino motor controller.

    Expected message formats:
        STATUS pos_cm=1.54 dir=idle
        IMPACT peak_g=45.2 pos_cm=1.54
    """

    def __init__(self, config):
        self.config = config
        self._serial = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._latest_status = ArduinoState()
        self._pending_impact: Optional[ImpactData] = None
        self._connected = False

    def connect(self) -> bool:
        if not _SERIAL_AVAILABLE:
            print("  ⚠ pyserial not installed — run: pip install pyserial")
            return False
        try:
            self._serial = serial.Serial(
                self.config.port,
                self.config.baud_rate,
                timeout=self.config.timeout
            )
            time.sleep(2.0)  # Arduino resets on serial open
            self._serial.reset_input_buffer()
            self._running = True
            self._connected = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            print(f"  Arduino connected: {self.config.port} @ {self.config.baud_rate} baud")
            return True
        except Exception as e:
            print(f"  Arduino connection failed ({self.config.port}): {e}")
            return False

    def disconnect(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._connected = False

    def _read_loop(self):
        while self._running:
            try:
                raw = self._serial.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if line.startswith("STATUS "):
                    self._parse_status(line[7:])
                elif line.startswith("IMPACT "):
                    self._parse_impact(line[7:])
            except Exception:
                if self._running:
                    pass  # transient read error, keep going
                else:
                    break

    @staticmethod
    def _parse_kv(s: str) -> dict:
        result = {}
        for token in s.split():
            if "=" in token:
                k, v = token.split("=", 1)
                result[k] = v
        return result

    def _parse_status(self, body: str):
        fields = self._parse_kv(body)
        try:
            with self._lock:
                self._latest_status = ArduinoState(
                    position_cm=float(fields.get("pos_cm", 0.0)),
                    direction=fields.get("dir", "idle"),
                )
        except ValueError:
            pass

    def _parse_impact(self, body: str):
        fields = self._parse_kv(body)
        try:
            impact = ImpactData(
                peak_g=float(fields.get("peak_g", 0.0)),
                position_cm=float(fields.get("pos_cm", 0.0)),
            )
            with self._lock:
                self._pending_impact = impact
        except ValueError:
            pass

    @property
    def latest_status(self) -> ArduinoState:
        with self._lock:
            s = self._latest_status
            return ArduinoState(position_cm=s.position_cm, direction=s.direction)

    def pop_latest_impact(self) -> Optional[ImpactData]:
        """Return and clear the most recent IMPACT message, or None if not yet received."""
        with self._lock:
            impact = self._pending_impact
            self._pending_impact = None
            return impact

    @property
    def is_connected(self) -> bool:
        return self._connected
