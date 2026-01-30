#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prusa Web Controller – Simple Flask version with jogging
"""

import os, threading, time
from flask import Flask, render_template, request, jsonify
import serial, serial.tools.list_ports

# ---------------------------
# Global variables
# ---------------------------
app = Flask(__name__)

printer_ser = None
printer_lock = threading.Lock()
printer_port = None
printer_baud = 115200
activity_log = []
DEFAULT_STEP_MM = 10

def log(msg):
    """Add a message to the activity log."""
    ts = time.strftime("%H:%M:%S")
    activity_log.append(f"[{ts}] {msg}")
    print(msg)
    # Keep log size reasonable
    if len(activity_log) > 200:
        activity_log.pop(0)

def list_serial_ports():
    """List available serial ports."""
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]

def autodetect_port():
    """Try common USB/ACM ports"""
    for c in ("/dev/ttyUSB0", "/dev/ttyACM0"):
        if os.path.exists(c):
            return c
    for p in serial.tools.list_ports.comports():
        if "USB" in p.device or "ACM" in p.device:
            return p.device
    return None

def send_gcode(line):
    """Send a G-code command to the printer."""
    global printer_ser
    if not printer_ser or not printer_ser.is_open:
        raise RuntimeError("Printer not connected")
    
    with printer_lock:
        printer_ser.write((line.strip() + "\n").encode("utf-8"))
        printer_ser.flush()
        log(f"> {line}")
        time.sleep(0.05)
        
        # Try reading responses
        responses = []
        try:
            start_time = time.time()
            while time.time() - start_time < 0.2:
                if printer_ser.in_waiting > 0:
                    response = printer_ser.readline().decode(errors="ignore").strip()
                    if response:
                        responses.append(response)
                        log(f"< {response}")
                else:
                    break
                time.sleep(0.01)
        except Exception as e:
            log(f"Error reading response: {e}")

# ---------------------------
# Flask routes
# ---------------------------

@app.route("/")
def index():
    """Serve the main page."""
    status = "Connected" if (printer_ser and printer_ser.is_open) else "Disconnected"
    return render_template(
        "index.html",
        status=status,
        port=printer_port or "(auto)",
        baud=printer_baud,
        default_step=DEFAULT_STEP_MM,
        logs=activity_log,
    )

@app.post("/api/connect")
def api_connect():
    """Connect to the printer."""
    global printer_ser, printer_port, printer_baud
    try:
        baud = int(request.json.get("baud", 115200))
        printer_baud = baud
        
        port = autodetect_port()
        if not port:
            return jsonify(ok=False, error="No serial port found."), 400
        
        printer_port = port
        
        if printer_ser and printer_ser.is_open:
            printer_ser.close()
        
        printer_ser = serial.Serial(printer_port, printer_baud, timeout=2)
        printer_ser.write(b"\n")
        printer_ser.flush()
        time.sleep(2)  # Wait for printer to reset
        
        # Clear buffer
        printer_ser.reset_input_buffer()
        
        log(f"Connected to printer on {printer_port} at {printer_baud} baud")
        return jsonify(ok=True, port=printer_port, baud=printer_baud)
    
    except Exception as e:
        log(f"Connection error: {e}")
        return jsonify(ok=False, error=str(e)), 400

@app.post("/api/disconnect")
def api_disconnect():
    """Disconnect from the printer."""
    global printer_ser
    try:
        if printer_ser and printer_ser.is_open:
            printer_ser.close()
        printer_ser = None
        log("Disconnected from printer")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

@app.post("/api/home")
def api_home():
    """Initialize printer for movement without homing."""
    try:
        log("Resetting printer and allowing moves without homing...")
        send_gcode("M999")  # Reset from error state
        time.sleep(0.5)
        send_gcode("M564 S0 H0")  # Allow movement without homing
        time.sleep(0.2)
        send_gcode("M17")  # Enable steppers
        time.sleep(0.2)
        send_gcode("G92 Z100 X100 Y100")  # Set current position
        log("✓ Ready to jog! Endstops ignored.")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

@app.post("/api/jog")
def api_jog():
    """Jog an axis by a given amount."""
    try:
        axis = request.json.get("axis")
        direction = float(request.json.get("dir", 1))
        step = float(request.json.get("step", DEFAULT_STEP_MM))
        
        if axis not in ("X", "Y", "Z"):
            return jsonify(ok=False, error="Invalid axis"), 400
        
        move = step * direction
        
        send_gcode("G91")  # Relative mode
        
        if axis in ("X", "Y"):
            send_gcode(f"G1 {axis}{move} F6000")
        else:
            send_gcode(f"G1 Z{move} F600")
        
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

@app.post("/api/goto")
def api_goto():
    """Go to a specific X,Y position."""
    try:
        x = request.json.get("x")
        y = request.json.get("y")
        send_gcode("G90")  # Absolute mode
        send_gcode(f"G1 X{float(x)} Y{float(y)} F6000")
        log(f"Moving to X{x} Y{y}")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

@app.post("/api/estop")
def api_estop():
    """Emergency stop."""
    try:
        if printer_ser and printer_ser.is_open:
            with printer_lock:
                printer_ser.write(b"M112\n")
                printer_ser.flush()
        log("!!! M112 (EMERGENCY STOP) !!!")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

@app.get("/api/status")
def api_status():
    """Get printer connection status."""
    connected = printer_ser is not None and printer_ser.is_open
    return jsonify(connected=connected, port=printer_port, baud=printer_baud)

@app.get("/api/logs")
def api_logs():
    """Get activity logs."""
    return jsonify(logs=activity_log[-200:])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
