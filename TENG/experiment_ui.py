"""
TENG Experiment UI
Web-based interface for configuring, running, and visualizing TENG experiments.
"""

import os
import sys
import json
import glob
import re
import io
import base64
import threading
import subprocess
import time
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, render_template, request, jsonify, send_file

# Add TENG root to path for imports
TENG_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TENG_DIR)

from utils.experiment_config import ExperimentConfig, OscilloscopeConfig

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global experiment state
# ---------------------------------------------------------------------------
experiment_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current_acquisition": 0,
    "status_text": "Idle",
    "log": [],
    "results": [],          # list of {acquisition, peak_voltage, ...}
    "waveforms": [],        # list of {acquisition, timestamps, voltages}
    "output_dir": None,
    "error": None,
    "finished": False,
}
experiment_lock = threading.Lock()
stop_event = threading.Event()


def _reset_state():
    with experiment_lock:
        experiment_state.update({
            "running": False,
            "progress": 0,
            "total": 0,
            "current_acquisition": 0,
            "status_text": "Idle",
            "log": [],
            "results": [],
            "waveforms": [],
            "output_dir": None,
            "error": None,
            "finished": False,
        })


def _log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    with experiment_lock:
        experiment_state["log"].append(f"[{ts}] {msg}")


# ---------------------------------------------------------------------------
# Experiment runner (background thread)
# ---------------------------------------------------------------------------
def _run_experiment_thread(config_dict):
    """Run experiment in background thread using the real hardware."""
    _reset_state()
    stop_event.clear()

    with experiment_lock:
        experiment_state["running"] = True
        experiment_state["total"] = config_dict["num_acquisitions"]
        experiment_state["status_text"] = "Initializing..."

    try:
        osc_cfg = OscilloscopeConfig(
            sampling_frequency=config_dict["sampling_frequency"],
            acquisition_time_ms=config_dict["acquisition_time_ms"],
            amplitude_range=config_dict["amplitude_range"],
            trigger_level=config_dict["trigger_level"],
            trigger_edge=config_dict["trigger_edge"],
            channel=config_dict["channel"],
            trigger_channel=config_dict.get("trigger_channel", config_dict["channel"]),
            offset=config_dict.get("offset", 0.0),
        )

        exp_config = ExperimentConfig(
            name=config_dict["name"],
            description=config_dict["description"],
            num_acquisitions=config_dict["num_acquisitions"],
            oscilloscope=osc_cfg,
            save_plots=config_dict.get("save_plots", True),
            output_dir=os.path.join(TENG_DIR, "experiments"),
        )

        from utils.experiment_manager import TENGExperiment

        experiment = TENGExperiment(exp_config)
        _log("Setting up hardware...")
        with experiment_lock:
            experiment_state["status_text"] = "Connecting to hardware..."

        experiment.setup()
        with experiment_lock:
            experiment_state["output_dir"] = experiment.output_dir

        _log(f"Output directory: {experiment.output_dir}")
        _log("Hardware ready – starting acquisitions")

        for acq_num in range(1, config_dict["num_acquisitions"] + 1):
            if stop_event.is_set():
                _log("Experiment stopped by user")
                break

            with experiment_lock:
                experiment_state["current_acquisition"] = acq_num
                experiment_state["progress"] = int((acq_num - 1) / config_dict["num_acquisitions"] * 100)
                experiment_state["status_text"] = f"Acquisition {acq_num}/{config_dict['num_acquisitions']} – waiting for trigger..."

            _log(f"Acquisition {acq_num}/{config_dict['num_acquisitions']} – waiting for trigger...")

            df = experiment.acquire_single(acq_num)

            if df is not None:
                peak = float(np.max(np.abs(df["Voltage_V"].values)))
                with experiment_lock:
                    experiment_state["results"].append({
                        "acquisition": acq_num,
                        "peak_voltage": peak,
                    })
                    # Keep waveform data (down-sampled for plotting)
                    step = max(1, len(df) // 2000)
                    experiment_state["waveforms"].append({
                        "acquisition": acq_num,
                        "timestamps": df["Timestamp_ms"].values[::step].tolist(),
                        "voltages": df["Voltage_V"].values[::step].tolist(),
                    })
                _log(f"Acquisition {acq_num} complete – peak {peak:.2f} V")
            else:
                _log(f"Acquisition {acq_num} timed out")

        # Generate summary
        if experiment.results:
            experiment._generate_summary()

        experiment.cleanup()
        _log("Experiment complete")

        with experiment_lock:
            experiment_state["progress"] = 100
            experiment_state["status_text"] = "Complete"
            experiment_state["finished"] = True
            experiment_state["running"] = False

    except Exception as e:
        _log(f"ERROR: {e}")
        with experiment_lock:
            experiment_state["error"] = str(e)
            experiment_state["status_text"] = f"Error: {e}"
            experiment_state["running"] = False
            experiment_state["finished"] = True


# ---------------------------------------------------------------------------
# Simulate mode (for testing without hardware)
# ---------------------------------------------------------------------------
def _run_simulated_experiment(config_dict):
    """Simulate an experiment for UI testing without oscilloscope hardware."""
    _reset_state()
    stop_event.clear()

    num_acq = config_dict["num_acquisitions"]
    fs = config_dict["sampling_frequency"]
    acq_time_ms = config_dict["acquisition_time_ms"]
    amp_range = config_dict["amplitude_range"]

    with experiment_lock:
        experiment_state["running"] = True
        experiment_state["total"] = num_acq
        experiment_state["status_text"] = "Simulating..."

    output_dir = os.path.join(TENG_DIR, "experiments",
                              f"{config_dict['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(output_dir, exist_ok=True)

    with experiment_lock:
        experiment_state["output_dir"] = output_dir

    _log(f"[SIM] Output: {output_dir}")

    for acq_num in range(1, num_acq + 1):
        if stop_event.is_set():
            _log("Stopped by user")
            break

        with experiment_lock:
            experiment_state["current_acquisition"] = acq_num
            experiment_state["progress"] = int((acq_num - 1) / num_acq * 100)
            experiment_state["status_text"] = f"Simulating acquisition {acq_num}/{num_acq}..."

        _log(f"Simulating acquisition {acq_num}/{num_acq}...")

        # Generate synthetic waveform
        n_samples = int(fs * acq_time_ms / 1000)
        t = np.linspace(0, acq_time_ms, n_samples)
        peak_v = np.random.uniform(0.3, 0.8) * amp_range / 2
        noise = np.random.normal(0, 0.02 * amp_range, n_samples)
        # Simulated TENG impulse
        impulse_center = acq_time_ms * 0.4
        impulse_width = acq_time_ms * 0.05
        signal = peak_v * np.exp(-0.5 * ((t - impulse_center) / impulse_width) ** 2) + noise
        # Add small negative bounce
        signal += -0.3 * peak_v * np.exp(-0.5 * ((t - impulse_center - impulse_width * 3) / (impulse_width * 1.5)) ** 2)

        df = pd.DataFrame({"Timestamp_ms": t, "Voltage_V": signal})
        csv_path = os.path.join(output_dir, f"acquisition_{acq_num:04d}.csv")
        df.to_csv(csv_path, index=False)

        peak = float(np.max(np.abs(signal)))
        with experiment_lock:
            experiment_state["results"].append({
                "acquisition": acq_num,
                "peak_voltage": peak,
            })
            step = max(1, len(t) // 2000)
            experiment_state["waveforms"].append({
                "acquisition": acq_num,
                "timestamps": t[::step].tolist(),
                "voltages": signal[::step].tolist(),
            })

        _log(f"Acquisition {acq_num} – peak {peak:.2f} V")
        time.sleep(0.6)  # Simulate acquisition delay

    _log("Simulation complete")
    with experiment_lock:
        experiment_state["progress"] = 100
        experiment_state["status_text"] = "Complete"
        experiment_state["finished"] = True
        experiment_state["running"] = False


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("experiment_ui.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    if experiment_state["running"]:
        return jsonify({"error": "Experiment already running"}), 400

    data = request.json
    simulate = data.pop("simulate", False)

    config = {
        "name": data.get("name", "TENG_Test"),
        "description": data.get("description", ""),
        "num_acquisitions": int(data.get("num_acquisitions", 10)),
        "sampling_frequency": float(data.get("sampling_frequency", 500e3)),
        "acquisition_time_ms": float(data.get("acquisition_time_ms", 15)),
        "amplitude_range": float(data.get("amplitude_range", 50)),
        "trigger_level": float(data.get("trigger_level", 0.5)),
        "trigger_edge": data.get("trigger_edge", "rising"),
        "channel": int(data.get("channel", 0)),
        "trigger_channel": int(data.get("trigger_channel", 0)),
        "offset": float(data.get("offset", 0.0)),
        "save_plots": data.get("save_plots", True),
    }

    target = _run_simulated_experiment if simulate else _run_experiment_thread
    t = threading.Thread(target=target, args=(config,), daemon=True)
    t.start()

    return jsonify({"ok": True, "simulate": simulate})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_event.set()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    with experiment_lock:
        return jsonify({
            "running": experiment_state["running"],
            "progress": experiment_state["progress"],
            "total": experiment_state["total"],
            "current_acquisition": experiment_state["current_acquisition"],
            "status_text": experiment_state["status_text"],
            "log": experiment_state["log"][-50:],
            "results": experiment_state["results"],
            "error": experiment_state["error"],
            "finished": experiment_state["finished"],
            "output_dir": experiment_state["output_dir"],
        })


@app.route("/api/waveforms")
def api_waveforms():
    """Return waveform data for live plotting."""
    with experiment_lock:
        return jsonify(experiment_state["waveforms"])


@app.route("/api/experiments")
def api_experiments():
    """List all past experiment directories."""
    exp_root = os.path.join(TENG_DIR, "experiments")
    if not os.path.isdir(exp_root):
        return jsonify([])

    dirs = []
    for d in sorted(os.listdir(exp_root), reverse=True):
        full = os.path.join(exp_root, d)
        if os.path.isdir(full):
            csvs = glob.glob(os.path.join(full, "acquisition_*.csv"))
            if not csvs:
                csvs = glob.glob(os.path.join(full, "cycle_*.csv"))
            dirs.append({
                "name": d,
                "path": full,
                "n_files": len(csvs),
                "has_config": os.path.exists(os.path.join(full, "experiment_config.txt")),
            })
    return jsonify(dirs)


# ---------------------------------------------------------------------------
# Background cache builder  (runs in a SUBPROCESS — no GIL interference)
# ---------------------------------------------------------------------------
_cache_procs = {}  # name -> subprocess.Popen

# Stand-alone script run via subprocess — reads CSVs, writes progress + cache
_CACHE_BUILDER_SCRIPT = r'''
import sys, os, json, re, glob

def main():
    exp_dir = sys.argv[1]
    cache_path = sys.argv[2]
    progress_path = cache_path + ".progress"

    csv_files = sorted(glob.glob(os.path.join(exp_dir, "acquisition_*.csv")))
    if not csv_files:
        csv_files = sorted(glob.glob(os.path.join(exp_dir, "cycle_*.csv")))
    total = len(csv_files)
    if total == 0:
        json.dump({"n_files": 0, "peaks": []}, open(cache_path, "w"))
        try: os.remove(progress_path)
        except: pass
        return

    peaks = []
    for i, cf in enumerate(csv_files):
        try:
            peak = 0.0
            with open(cf, "r") as f:
                next(f)  # skip header
                for line in f:
                    parts = line.split(",")
                    if len(parts) >= 2:
                        v = abs(float(parts[1]))
                        if v > peak:
                            peak = v
            num = int(re.search(r"(\d+)", os.path.basename(cf)).group(1))
            peaks.append({"acquisition": num, "peak_voltage": peak})
        except Exception:
            pass

        # Write progress file every 100 files
        if (i + 1) % 100 == 0 or (i + 1) == total:
            peaks_sorted = sorted(peaks, key=lambda p: p["acquisition"])
            try:
                with open(progress_path, "w") as pf:
                    json.dump({"done": i + 1, "total": total, "peaks": peaks_sorted}, pf)
            except Exception:
                pass

    peaks_sorted = sorted(peaks, key=lambda p: p["acquisition"])
    with open(cache_path, "w") as f:
        json.dump({"n_files": total, "peaks": peaks_sorted}, f)

    # Clean up progress file
    try: os.remove(progress_path)
    except: pass

if __name__ == "__main__":
    main()
'''


def _start_cache_subprocess(name, exp_dir, cache_path):
    """Spawn a separate Python process to build the cache.
    Zero GIL interference with Flask."""
    if name in _cache_procs:
        proc = _cache_procs[name]
        if proc.poll() is None:  # still running
            return
    proc = subprocess.Popen(
        [sys.executable, "-c", _CACHE_BUILDER_SCRIPT, exp_dir, cache_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _cache_procs[name] = proc


def _get_cache_progress(cache_path):
    """Read progress from the subprocess's progress file."""
    progress_path = cache_path + ".progress"
    if os.path.exists(progress_path):
        try:
            with open(progress_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


@app.route("/api/experiment/<name>")
def api_experiment_detail(name):
    """Load peaks + config from a past experiment. Waveforms loaded lazily."""
    exp_dir = os.path.join(TENG_DIR, "experiments", name)
    if not os.path.isdir(exp_dir):
        return jsonify({"error": "Not found"}), 404

    # Read config (lightweight)
    config_text = ""
    config_path = os.path.join(exp_dir, "experiment_config.txt")
    if os.path.exists(config_path):
        with open(config_path, encoding='utf-8', errors='replace') as f:
            config_text = f.read()

    cache_path = os.path.join(exp_dir, ".cache.json")

    # --- Check if cache is ready on disk ---
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                cached = json.load(f)
            csv_files = glob.glob(os.path.join(exp_dir, "acquisition_*.csv"))
            if not csv_files:
                csv_files = glob.glob(os.path.join(exp_dir, "cycle_*.csv"))
            if cached.get("n_files") == len(csv_files):
                return jsonify({
                    "name": name,
                    "config": config_text,
                    "peaks": cached["peaks"],
                    "n_waveforms": cached["n_files"],
                    "waveforms": [],
                    "cache_status": "done",
                })
        except Exception:
            pass

    # --- Cache not ready: check if subprocess is building ---
    progress = _get_cache_progress(cache_path)

    # Count CSV files
    csv_files = glob.glob(os.path.join(exp_dir, "acquisition_*.csv"))
    if not csv_files:
        csv_files = glob.glob(os.path.join(exp_dir, "cycle_*.csv"))
    n_total = len(csv_files)

    if n_total == 0:
        return jsonify({
            "name": name, "config": config_text,
            "peaks": [], "n_waveforms": 0, "waveforms": [],
            "cache_status": "done",
        })

    # Start subprocess if not already running
    _start_cache_subprocess(name, exp_dir, cache_path)

    if progress:
        pct = int(progress["done"] / progress["total"] * 100) if progress["total"] else 0
        return jsonify({
            "name": name,
            "config": config_text,
            "peaks": progress.get("peaks", []),
            "n_waveforms": n_total,
            "n_indexed": progress.get("done", 0),
            "waveforms": [],
            "cache_status": "building",
            "cache_progress": pct,
        })

    return jsonify({
        "name": name,
        "config": config_text,
        "peaks": [],
        "n_waveforms": n_total,
        "waveforms": [],
        "cache_status": "building",
        "cache_progress": 0,
    })


DOWNSAMPLE_POINTS = 500
MAX_BATCH_WAVEFORMS = 50  # Hard cap to prevent memory bombs


def _find_csv_path(exp_dir, acq_num):
    """Locate the CSV file for a given acquisition number."""
    candidates = [
        os.path.join(exp_dir, f"acquisition_{acq_num:04d}.csv"),
        os.path.join(exp_dir, f"acquisition_{acq_num:03d}.csv"),
        os.path.join(exp_dir, f"acquisition_{acq_num}.csv"),
        os.path.join(exp_dir, f"cycle_{acq_num:04d}.csv"),
        os.path.join(exp_dir, f"cycle_{acq_num:03d}.csv"),
        os.path.join(exp_dir, f"cycle_{acq_num}.csv"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _read_csv_downsampled(csv_path, max_points=DOWNSAMPLE_POINTS):
    """Read a CSV and return downsampled (timestamps, voltages) lists."""
    df = pd.read_csv(csv_path, engine='c')  # C engine releases GIL properly
    t_col = df.iloc[:, 0].values
    v_col = df.iloc[:, 1].values
    step = max(1, len(t_col) // max_points)
    return t_col[::step].tolist(), v_col[::step].tolist()


@app.route("/api/experiment/<name>/waveform/<int:acq_num>")
def api_waveform_single(name, acq_num):
    """Load a single waveform (down-sampled) for lazy loading."""
    exp_dir = os.path.join(TENG_DIR, "experiments", name)
    if not os.path.isdir(exp_dir):
        return jsonify({"error": "Not found"}), 404

    csv_path = _find_csv_path(exp_dir, acq_num)
    if csv_path is None:
        return jsonify({"error": f"Waveform {acq_num} not found"}), 404

    try:
        timestamps, voltages = _read_csv_downsampled(csv_path)
        return jsonify({
            "acquisition": acq_num,
            "timestamps": timestamps,
            "voltages": voltages,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/experiment/<name>/waveforms")
def api_waveforms_batch(name):
    """Load multiple waveforms in one request. Pass ?ids=1,2,3 (capped at MAX_BATCH_WAVEFORMS)."""
    exp_dir = os.path.join(TENG_DIR, "experiments", name)
    if not os.path.isdir(exp_dir):
        return jsonify({"error": "Not found"}), 404

    ids_param = request.args.get('ids', '')
    if not ids_param:
        return jsonify([])

    requested = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
    # Hard cap to prevent memory bombs on large experiments
    requested = requested[:MAX_BATCH_WAVEFORMS]

    waveforms = []
    for acq_num in requested:
        csv_path = _find_csv_path(exp_dir, acq_num)
        if csv_path is None:
            continue
        try:
            timestamps, voltages = _read_csv_downsampled(csv_path)
            waveforms.append({
                "acquisition": acq_num,
                "timestamps": timestamps,
                "voltages": voltages,
            })
        except Exception:
            continue

    return jsonify(waveforms)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    os.makedirs(os.path.join(TENG_DIR, "templates"), exist_ok=True)
    print("=" * 60)
    print("  TENG Experiment UI")
    print("  http://127.0.0.1:5002")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5002, debug=False)
