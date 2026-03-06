#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prusa Web Controller – Simple Flask version with jogging
"""

import csv, io, os, re, threading, time, datetime
from flask import Flask, render_template, request, jsonify, send_file
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

# Load cell
loadcell_ser = None
loadcell_port = None
loadcell_baud = 9600
loadcell_raw = 0.0       # latest raw reading from sensor
loadcell_tare = 0.0     # tare offset
loadcell_lock = threading.Lock()
loadcell_buffer = []    # rolling buffer for smoothing
LOADCELL_SMOOTH_SIZE = 10  # number of readings to average

# ESP / IMU
esp_ser = None
esp_port = None
esp_baud = 115200
esp_lock = threading.Lock()
imu_latest = {}  # keyed by imu_number -> {id, imu, ax, ay, az, gx, gy, gz}
esp_raw_lines = []          # last N raw lines received (for debug)
ESP_RAW_BUFFER = 30
esp_bytes_received = 0      # total bytes read from ESP (debug counter)

# IMU recording state
imu_recording = False
imu_record_lock = threading.Lock()
imu_records = []           # kept only for row count in status endpoint
imu_pending = {}           # ms_timestamp -> {"compression": int, "z": float, "imus": {}}
imu_current_compression = 0
imu_csv_path = None        # path of the current/last CSV
imu_csv_file = None        # open file handle for streaming writes
imu_csv_writer = None      # csv.DictWriter writing to imu_csv_file
imu_row_count = 0          # rows written so far

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

def autodetect_printer_port():
    """Find the Prusa printer specifically by its USB vendor ID."""
    for p in serial.tools.list_ports.comports():
        # Prusa printers use VID 2C99
        if "2C99" in (p.hwid or ""):
            return p.device
    return None


def autodetect_loadcell_port():
    """Find the load cell (Arduino) by excluding the Prusa and ESP (CH340) ports."""
    for p in serial.tools.list_ports.comports():
        hwid = p.hwid or ""
        if "2C99" in hwid:   # Prusa
            continue
        if "1A86" in hwid:   # CH340 = ESP, skip
            continue
        if "USB" in p.device or "ACM" in p.device:
            return p.device
    return None


def autodetect_esp_port():
    """Find the ESP32 by its CH340 USB chip (VID 1A86), excluding the Prusa port."""
    for p in serial.tools.list_ports.comports():
        hwid = p.hwid or ""
        # Skip Prusa printer
        if "2C99" in hwid:
            continue
        # CH340 chip used by the ESP
        if "1A86" in hwid:
            return p.device
    # Fallback: third non-Prusa USB/ACM port
    exclude = set()
    for p in serial.tools.list_ports.comports():
        if "2C99" in (p.hwid or ""):
            exclude.add(p.device)
    lc_port = None
    for p in serial.tools.list_ports.comports():
        if p.device not in exclude and ("USB" in p.device or "ACM" in p.device):
            lc_port = p.device
            break
    if lc_port:
        exclude.add(lc_port)
    for p in serial.tools.list_ports.comports():
        if p.device not in exclude and ("USB" in p.device or "ACM" in p.device):
            return p.device
    return None


def loadcell_reader_thread():
    """Background thread: auto-connects and continuously reads from the load cell."""
    global loadcell_raw, loadcell_ser, loadcell_port
    while True:
        if not (loadcell_ser and loadcell_ser.is_open):
            port = autodetect_loadcell_port()
            if port:
                try:
                    loadcell_ser = serial.Serial(port, loadcell_baud, timeout=1)
                    loadcell_port = port
                    log(f"Load cell auto-connected on {port}")
                except Exception:
                    time.sleep(2)
                    continue
            else:
                time.sleep(2)
                continue
        try:
            line = loadcell_ser.readline().decode(errors="ignore").strip()
            if line:
                nums = re.findall(r"[-+]?\d*\.?\d+", line)
                if nums:
                    val = float(nums[-1])
                    with loadcell_lock:
                        loadcell_buffer.append(val)
                        if len(loadcell_buffer) > LOADCELL_SMOOTH_SIZE:
                            loadcell_buffer.pop(0)
                        loadcell_raw = sum(loadcell_buffer) / len(loadcell_buffer)
        except Exception:
            loadcell_ser = None
            time.sleep(1)


def esp_reader_thread():
    """Background thread: auto-connects and continuously reads IMU data from ESP."""
    global esp_ser, esp_port, imu_latest, esp_bytes_received
    global imu_recording, imu_records, imu_current_compression
    global imu_csv_file, imu_csv_writer, imu_row_count
    while True:
        if not (esp_ser and esp_ser.is_open):
            port = autodetect_esp_port()
            if port:
                try:
                    esp_ser = serial.Serial(
                        port, esp_baud, timeout=1,
                        dsrdtr=False, rtscts=False
                    )
                    esp_ser.dtr = False   # don't hold ESP in reset
                    esp_ser.rts = False   # don't hold ESP in download mode
                    time.sleep(3)         # wait for ESP to boot
                    esp_ser.reset_input_buffer()
                    esp_port = port
                    log(f"ESP/IMU auto-connected on {port}")
                except Exception:
                    time.sleep(2)
                    continue
            else:
                time.sleep(2)
                continue
        try:
            waiting = esp_ser.in_waiting
            line = esp_ser.readline().decode(errors="ignore").strip()
            # Always count raw bytes for diagnostics
            esp_bytes_received += len(line)
            if not line:
                continue
            # Store raw line for debug inspection
            esp_raw_lines.append(line)
            if len(esp_raw_lines) > ESP_RAW_BUFFER:
                esp_raw_lines.pop(0)
            # Expected format: ms,ax1,ay1,az1,gx1,gy1,gz1,ax2,...,gz4 (25 fields, all 4 IMUs)
            parts = line.split(",")
            if len(parts) != 25:
                continue
            try:
                ms = int(parts[0])
                imus = {}
                for n in range(1, 5):
                    base = 1 + (n - 1) * 6
                    imus[n] = {
                        "id": ms,
                        "imu": n,
                        "ax": float(parts[base]),
                        "ay": float(parts[base + 1]),
                        "az": float(parts[base + 2]),
                        "gx": float(parts[base + 3]),
                        "gy": float(parts[base + 4]),
                        "gz": float(parts[base + 5]),
                    }
            except (ValueError, IndexError):
                log(f"ESP parse error on: {repr(line)}")
                continue

            with esp_lock:
                for n, imu in imus.items():
                    imu_latest[n] = imu

            # If recording, emit one combined row per timestamp directly
            with imu_record_lock:
                if imu_recording:
                    with pos_lock:
                        cur_z = tracked_pos["z"]
                    row = {
                        "compression_number": imu_current_compression,
                        "z_value": cur_z,
                        "ms": ms,
                    }
                    for n in range(1, 5):
                        imu = imus.get(n, {})
                        for axis in ("ax", "ay", "az", "gx", "gy", "gz"):
                            row[f"{axis}{n}"] = imu.get(axis, "")
                    if imu_csv_writer:
                        imu_csv_writer.writerow(row)
                        imu_csv_file.flush()
                        imu_row_count += 1
        except Exception:
            esp_ser = None
            time.sleep(1)


def send_gcode(line):
    """Send a G-code command to the printer. Returns list of response lines."""
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
        return responses

# ---------------------------
# Coordinate press system
# ---------------------------
CENTER_X = 108        # Absolute X of bed center after homing (103 + 5mm correction)
CENTER_Y = 83         # Absolute Y of bed center after homing (85 - 2mm correction)
PUSH_STEP_MM = 0.5    # Z step size during force-controlled descent
PUSH_SPEED = 600      # Z descent speed (mm/min)
PUSH_SETTLE = 0.08    # Seconds to wait after each Z step
MAX_OFFSET_X = 105    # Max mm X offset from center (safety limit)
MAX_OFFSET_Y = 85     # Max mm Y offset from center (safety limit)

# Software-tracked position (relative to center)
tracked_pos = {"x": 0.0, "y": 0.0, "z": 95.0}
pos_lock = threading.Lock()

def update_pos(**kwargs):
    """Update tracked position. Pass x=, y=, z= as absolute offsets from center."""
    with pos_lock:
        for k, v in kwargs.items():
            tracked_pos[k] = round(v, 2)

abort_flag = threading.Event()
sequence_state = {
    "running": False,
    "current_coord_index": 0,
    "total_coords": 0,
    "results": [],
    "message": ""
}
sequence_lock = threading.Lock()


def do_single_push(target_kg, max_depth_mm=150):
    """Lower Z until target force is reached, then return to start height."""
    # Clear smoothing buffer so stale readings can't trigger
    with loadcell_lock:
        loadcell_buffer.clear()

    # Wait for at least 2 fresh near-zero readings
    settle_start = time.time()
    while time.time() - settle_start < 1.0:
        time.sleep(0.03)
        with loadcell_lock:
            if len(loadcell_buffer) >= 2:
                current = (loadcell_raw - loadcell_tare) / 1000
                if abs(current) < target_kg * 0.5:
                    break
    else:
        log("  Warning: load cell didn't settle to zero, proceeding anyway")

    send_gcode("G91")  # Relative mode
    total_depth = 0
    peak_force = 0.0
    aborted = False

    with pos_lock:
        start_z = tracked_pos["z"]

    try:
        while total_depth < max_depth_mm:
            if abort_flag.is_set():
                aborted = True
                log("  Push aborted by user")
                break

            send_gcode(f"G1 Z-{PUSH_STEP_MM} F{PUSH_SPEED}")
            time.sleep(PUSH_SETTLE)

            with loadcell_lock:
                current_kg = (loadcell_raw - loadcell_tare) / 1000

            peak_force = max(peak_force, current_kg)
            total_depth += PUSH_STEP_MM
            cur_z = round(start_z - total_depth, 2)
            update_pos(z=cur_z)

            if current_kg >= target_kg:
                log(f"  Target reached: {current_kg:.3f} kg at {total_depth:.1f}mm")
                break

        # Always return Z to starting height
        if total_depth > 0:
            send_gcode(f"G1 Z{total_depth} F2400")
            time.sleep(max(total_depth / 40, 0.3))
            update_pos(z=start_z)
    finally:
        send_gcode("G90")  # Back to absolute

    return {
        "depth_mm": round(total_depth, 2),
        "peak_force_kg": round(peak_force, 4),
        "target_reached": peak_force >= target_kg,
        "aborted": aborted
    }


def run_coordinate_sequence(coordinates, target_kg, max_depth_mm):
    """Background task: press at each coordinate in sequence."""
    global imu_recording, imu_records, imu_current_compression, imu_csv_path
    global imu_csv_file, imu_csv_writer, imu_row_count

    with sequence_lock:
        sequence_state.update({
            "running": True,
            "current_coord_index": 0,
            "total_coords": len(coordinates),
            "results": [],
            "message": "Starting sequence..."
        })

    # Start IMU recording — open CSV immediately so every row is written to disk live
    _imu_fieldnames = ["compression_number", "z_value", "ms"]
    for _n in range(1, 5):
        for _ax in ("ax", "ay", "az", "gx", "gy", "gz"):
            _imu_fieldnames.append(f"{_ax}{_n}")
    os.makedirs("imu_recordings", exist_ok=True)
    _ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with imu_record_lock:
        imu_csv_path = os.path.join("imu_recordings", f"imu_sequence_{_ts}.csv")
        imu_csv_file = open(imu_csv_path, "w", newline="")
        imu_csv_writer = csv.DictWriter(imu_csv_file, fieldnames=_imu_fieldnames)
        imu_csv_writer.writeheader()
        imu_csv_file.flush()
        imu_row_count = 0
        imu_records = []
        imu_pending.clear()
        imu_current_compression = 0
        imu_recording = True
    log(f"IMU recording started → {imu_csv_path}")

    all_results = []
    try:
        for i, coord in enumerate(coordinates):
            if abort_flag.is_set():
                with sequence_lock:
                    sequence_state["message"] = "Sequence aborted by user"
                break

            # Update IMU compression number (1-indexed)
            with imu_record_lock:
                imu_current_compression = i + 1

            with sequence_lock:
                sequence_state["current_coord_index"] = i + 1
                sequence_state["message"] = f"Moving to point {i+1}/{len(coordinates)} ({coord['x']}, {coord['y']})"

            abs_x = CENTER_X + coord['x']
            abs_y = CENTER_Y + coord['y']
            log(f"▶ Point {i+1}/{len(coordinates)}: offset ({coord['x']}, {coord['y']}) → abs X{abs_x} Y{abs_y}")

            send_gcode("G90")
            send_gcode(f"G1 X{abs_x} Y{abs_y} F6000")
            update_pos(x=coord['x'], y=coord['y'])
            time.sleep(1)  # Wait for XY move

            with sequence_lock:
                sequence_state["message"] = f"Pressing at point {i+1}/{len(coordinates)}"

            point_depth = coord.get('z', max_depth_mm)
            result = do_single_push(target_kg, point_depth)
            all_results.append({"coord": coord, "result": result})

            # Re-assert XY after push — corrects any lost steps / frame-flex drift
            send_gcode("G90")
            send_gcode(f"G1 X{abs_x} Y{abs_y} F3000")
            time.sleep(0.5)

            with sequence_lock:
                sequence_state["results"] = all_results

        # Return to center
        with sequence_lock:
            sequence_state["message"] = "Returning to center..."
        send_gcode("G90")
        send_gcode(f"G1 X{CENTER_X} Y{CENTER_Y} F6000")
        update_pos(x=0.0, y=0.0)
        time.sleep(2)

        with sequence_lock:
            if not abort_flag.is_set():
                sequence_state["message"] = f"Sequence complete! {len(all_results)} points processed."
            sequence_state["running"] = False

        log(f"✓ Coordinate sequence finished: {len(all_results)} points")

    except Exception as e:
        with sequence_lock:
            sequence_state["message"] = f"Error: {e}"
            sequence_state["running"] = False
        log(f"Sequence error: {e}")

    finally:
        # Stop IMU recording and close the CSV file
        with imu_record_lock:
            imu_recording = False
            if imu_csv_file:
                try:
                    imu_csv_file.flush()
                    imu_csv_file.close()
                except Exception:
                    pass
            imu_csv_file = None
            imu_csv_writer = None
            saved_path = imu_csv_path
            saved_rows = imu_row_count
            imu_records = []
        if saved_rows > 0:
            log(f"IMU recording stopped. {saved_rows} rows saved to {saved_path}")
        else:
            log("No IMU data recorded (ESP may not be connected)")


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
        
        port = autodetect_printer_port()
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

        # Run homing sequence in background so HTTP response returns immediately
        def run_homing():
            try:
                log("Auto-homing: starting...")
                time.sleep(0.5)
                send_gcode("M999")       # Clear any error state
                time.sleep(0.5)
                send_gcode("M564 S0 H0") # Disable homing/calibration enforcement
                time.sleep(0.2)
                send_gcode("G28 W X Y")  # Home X and Y only (no Z endstop/PINDA)
                send_gcode("G92 Z0")     # Set current Z as 0
                log("✓ Homing complete - moving to start position...")
                time.sleep(0.5)
                send_gcode("G91")        # Relative mode
                send_gcode("G1 X103 F12000")   # X+103mm at max speed
                send_gcode("G1 Y85 F12000")    # Y+85mm at max speed
                send_gcode("G1 Z95 F1200")     # Z+90mm at max speed
                send_gcode("G90")        # Back to absolute mode
                update_pos(x=0.0, y=0.0, z=95.0)
                log("✓ Start position reached")
            except Exception as e:
                log(f"Homing error: {e}")

        threading.Thread(target=run_homing, daemon=True).start()

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
        
        # Update tracked position
        with pos_lock:
            tracked_pos[axis.lower()] = round(tracked_pos[axis.lower()] + move, 2)
        
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

# ── Load cell endpoints ────────────────────────────────────────────────────

@app.post("/api/loadcell/tare")
def api_loadcell_tare():
    """Zero the load cell at current reading."""
    global loadcell_tare
    with loadcell_lock:
        loadcell_tare = loadcell_raw
        loadcell_buffer.clear()
    log(f"Load cell tared at {loadcell_tare}")
    return jsonify(ok=True)


@app.get("/api/loadcell/weight")
def api_loadcell_weight():
    """Return the current tared weight."""
    with loadcell_lock:
        raw = loadcell_raw
        tare = loadcell_tare
    weight = raw - tare
    connected = loadcell_ser is not None and loadcell_ser.is_open
    return jsonify(ok=True, weight_kg=round(weight / 1000, 4), weight_raw=weight, connected=connected)


@app.get("/api/status")
def api_status():
    """Get printer, load cell, and ESP connection status."""
    connected = printer_ser is not None and printer_ser.is_open
    lc_connected = loadcell_ser is not None and loadcell_ser.is_open
    esp_connected = esp_ser is not None and esp_ser.is_open
    return jsonify(
        connected=connected, port=printer_port, baud=printer_baud,
        loadcell_connected=lc_connected, loadcell_port=loadcell_port,
        esp_connected=esp_connected, esp_port=esp_port
    )

@app.get("/api/logs")
def api_logs():
    """Get activity logs."""
    return jsonify(logs=activity_log[-200:])

@app.get("/api/position")
def api_position():
    """Get current tracked position relative to center."""
    with pos_lock:
        return jsonify(ok=True, x=tracked_pos["x"], y=tracked_pos["y"], z=tracked_pos["z"])

# ── Force push endpoints ───────────────────────────────────────────────────

@app.post("/api/force/push_coordinates")
def api_force_push_coordinates():
    """Start a coordinate press sequence (runs in background thread)."""
    try:
        data = request.json
        coordinates = data.get("coordinates", [])
        target_kg = float(data.get("target_kg", 2.0))
        max_depth_mm = float(data.get("max_depth_mm", 150))

        if not coordinates:
            return jsonify(ok=False, error="No coordinates provided"), 400

        # Validate coordinates are within safe range
        for c in coordinates:
            if abs(c['x']) > MAX_OFFSET_X or abs(c['y']) > MAX_OFFSET_Y:
                return jsonify(ok=False, error=f"Coordinate ({c['x']}, {c['y']}) exceeds safe range (X: ±{MAX_OFFSET_X}, Y: ±{MAX_OFFSET_Y}mm)"), 400

        with sequence_lock:
            if sequence_state["running"]:
                return jsonify(ok=False, error="A push operation is already running"), 400

        abort_flag.clear()
        log(f"Starting coordinate sequence: {len(coordinates)} points, {target_kg}kg")

        threading.Thread(
            target=run_coordinate_sequence,
            args=(coordinates, target_kg, max_depth_mm),
            daemon=True
        ).start()

        return jsonify(ok=True, message=f"Sequence started: {len(coordinates)} coordinates")
    except Exception as e:
        log(f"Coordinate push error: {e}")
        return jsonify(ok=False, error=str(e)), 400


@app.post("/api/upload_csv")
def api_upload_csv():
    """Parse an uploaded CSV file with X, Y, Z columns and return coordinates."""
    try:
        if 'file' not in request.files:
            return jsonify(ok=False, error="No file provided"), 400

        f = request.files['file']
        if not f.filename.lower().endswith('.csv'):
            return jsonify(ok=False, error="File must be a .csv"), 400

        stream = io.StringIO(f.stream.read().decode('utf-8-sig'))
        reader = csv.DictReader(stream)

        # Accept headers case-insensitively
        if reader.fieldnames is None:
            return jsonify(ok=False, error="Empty CSV file"), 400

        headers = [h.strip().upper() for h in reader.fieldnames]
        if 'X' not in headers or 'Y' not in headers:
            return jsonify(ok=False, error="CSV must have X and Y columns"), 400

        has_z = 'Z' in headers
        coordinates = []
        errors = []

        for row_num, row in enumerate(reader, start=2):
            norm = {h.strip().upper(): v.strip() for h, v in row.items()}
            try:
                x = float(norm['X'])
                y = float(norm['Y'])
                z = float(norm['Z']) if has_z and norm.get('Z', '') != '' else None
            except (ValueError, KeyError) as e:
                errors.append(f"Row {row_num}: invalid value – {e}")
                continue

            if abs(x) > MAX_OFFSET_X or abs(y) > MAX_OFFSET_Y:
                errors.append(f"Row {row_num}: ({x}, {y}) exceeds safe range (X: ±{MAX_OFFSET_X}, Y: ±{MAX_OFFSET_Y} mm)")
                continue

            coord = {'x': round(x, 3), 'y': round(y, 3)}
            if z is not None:
                coord['z'] = round(z, 3)
            coordinates.append(coord)

        if not coordinates:
            return jsonify(ok=False, error="No valid coordinates found. " + '; '.join(errors)), 400

        log(f"CSV upload: {len(coordinates)} coordinate(s) loaded")
        return jsonify(ok=True, coordinates=coordinates, warnings=errors)

    except Exception as e:
        log(f"CSV upload error: {e}")
        return jsonify(ok=False, error=str(e)), 400


@app.get("/api/force/sequence_status")
def api_force_sequence_status():
    """Get coordinate sequence progress."""
    with sequence_lock:
        return jsonify(ok=True, **{k: v for k, v in sequence_state.items()
                                   if k != 'results'},
                       result_count=len(sequence_state["results"]))


@app.post("/api/force/abort")
def api_force_abort():
    """Abort any running push operation."""
    abort_flag.set()
    log("⚠ Abort requested!")
    return jsonify(ok=True)


# ── ESP / IMU endpoints ───────────────────────────────────────────────────────────────

@app.get("/api/esp/status")
def api_esp_status():
    """Get ESP/IMU connection status and latest readings."""
    connected = esp_ser is not None and esp_ser.is_open
    with esp_lock:
        latest = dict(imu_latest)
    with imu_record_lock:
        recording = imu_recording
        record_count = imu_row_count
    return jsonify(
        ok=True,
        connected=connected,
        port=esp_port,
        imu_count=len(latest),
        imus=latest,
        recording=recording,
        record_count=record_count,
        last_csv=imu_csv_path,
        bytes_received=esp_bytes_received,
        raw_line_count=len(esp_raw_lines)
    )


@app.get("/api/esp/download_csv")
def api_esp_download_csv():
    """Download the last recorded IMU CSV file."""
    if not imu_csv_path or not os.path.isfile(imu_csv_path):
        return jsonify(ok=False, error="No IMU recording available"), 404
    return send_file(imu_csv_path, as_attachment=True)


@app.get("/api/esp/raw")
def api_esp_raw():
    """Return the last raw lines received from the ESP (for format debugging)."""
    return jsonify(ok=True, lines=list(esp_raw_lines))


if __name__ == "__main__":
    # Start load cell reader thread
    t = threading.Thread(target=loadcell_reader_thread, daemon=True)
    t.start()
    # Start ESP/IMU reader thread
    t2 = threading.Thread(target=esp_reader_thread, daemon=True)
    t2.start()
    app.run(host="0.0.0.0", port=5001)
