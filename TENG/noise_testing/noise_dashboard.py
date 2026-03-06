"""
Noise Testing Dashboard
Interactive web GUI for comparing and analysing static noise measurements.

Run:
    python noise_dashboard.py
Then open http://localhost:5003 in a browser.
"""

import os
import json
import glob
import numpy as np
import pandas as pd
from datetime import datetime
from scipy.signal import welch
from flask import Flask, render_template, jsonify, request

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
LABELS_FILE   = os.path.join(BASE_DIR, "noise_labels.json")
PORT = 5003

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_labels() -> dict:
    if os.path.exists(LABELS_FILE):
        with open(LABELS_FILE) as f:
            return json.load(f)
    return {}


def save_labels(labels: dict):
    with open(LABELS_FILE, "w") as f:
        json.dump(labels, f, indent=2)


def discover_files() -> list[dict]:
    """Return metadata for all noise CSV files in the recordings/ folder, sorted newest-first."""
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    patterns = [
        os.path.join(RECORDINGS_DIR, "static_noise_*.csv"),
        os.path.join(RECORDINGS_DIR, "static_noise_filtered_*.csv"),
    ]
    files = []
    seen = set()
    for pat in patterns:
        for path in sorted(glob.glob(pat), reverse=True):
            name = os.path.basename(path)
            if name in seen:
                continue
            seen.add(name)
            files.append({"name": name, "path": path})
    return files


def compute_stats(df: pd.DataFrame, col: str) -> dict:
    v = df[col].dropna().values
    if len(v) == 0:
        return {}
    rms = float(np.sqrt(np.mean(v ** 2)))
    return {
        "mean_mv":   round(float(np.mean(v))  * 1e3, 4),
        "std_mv":    round(float(np.std(v))   * 1e3, 4),
        "rms_mv":    round(rms                * 1e3, 4),
        "pp_mv":     round((v.max() - v.min()) * 1e3, 4),
        "max_mv":    round(float(v.max())     * 1e3, 4),
        "min_mv":    round(float(v.min())     * 1e3, 4),
        "n_samples": len(v),
    }


def detect_columns(df: pd.DataFrame) -> list[str]:
    """Return the voltage column(s) available in a DataFrame."""
    candidates = ["Voltage_V", "Voltage_Raw_V", "Voltage_Filtered_V"]
    return [c for c in candidates if c in df.columns]


def load_file(path: str) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def downsample(times, values, max_pts=8000):
    """Thin data to at most max_pts points for fast browser rendering."""
    n = len(times)
    if n <= max_pts:
        return times, values
    idx = np.round(np.linspace(0, n - 1, max_pts)).astype(int)
    return times[idx], values[idx]


def psd_data(values, fs_hz: float, max_pts=4000):
    """Return PSD via Welch, downsampled, in log10 power."""
    nperseg = min(len(values), 8192)
    freqs, psd = welch(values, fs=fs_hz, nperseg=nperseg)
    freqs, psd = downsample(freqs, psd, max_pts)
    return freqs.tolist(), np.log10(psd + 1e-30).tolist()


def histogram_data(values, bins=120):
    counts, edges = np.histogram(values * 1e3, bins=bins)  # → mV
    centres = ((edges[:-1] + edges[1:]) / 2).tolist()
    return centres, counts.tolist()


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("noise_dashboard.html")


@app.route("/api/files")
def api_files():
    labels = load_labels()
    result = []
    for meta in discover_files():
        name = meta["name"]
        df = load_file(meta["path"])
        if df is None:
            continue
        cols = detect_columns(df)
        # Use first voltage column for the summary stats
        stats = compute_stats(df, cols[0]) if cols else {}
        result.append({
            "name":     name,
            "label":    labels.get(name, {}).get("label", ""),
            "note":     labels.get(name, {}).get("note", ""),
            "filtered": "Voltage_Filtered_V" in df.columns,
            "stats":    stats,
        })
    return jsonify(result)


@app.route("/api/label", methods=["POST"])
def api_label():
    data = request.json
    labels = load_labels()
    name = data.get("name", "")
    if name:
        labels[name] = {
            "label": data.get("label", ""),
            "note":  data.get("note", ""),
        }
        save_labels(labels)
    return jsonify({"ok": True})


@app.route("/api/timeseries")
def api_timeseries():
    """Return downsampled time-series data for one or more files."""
    names = request.args.getlist("names")
    labels = load_labels()
    result = []

    file_map = {m["name"]: m["path"] for m in discover_files()}

    for name in names:
        if name not in file_map:
            continue
        df = load_file(file_map[name])
        if df is None:
            continue
        cols = detect_columns(df)
        t = df["Timestamp_ms"].values
        label = labels.get(name, {}).get("label") or name
        series = []
        for col in cols:
            v = df[col].values
            td, vd = downsample(t, v)
            series.append({
                "col":   col.replace("Voltage_", "").replace("_V", ""),
                "times": td.tolist(),
                "volts": (vd * 1e3).tolist(),  # → mV
            })
        result.append({"name": name, "label": label, "series": series})

    return jsonify(result)


@app.route("/api/psd")
def api_psd():
    """Return power spectral density (Welch) for one or more files."""
    names = request.args.getlist("names")
    labels = load_labels()
    file_map = {m["name"]: m["path"] for m in discover_files()}
    result = []

    for name in names:
        if name not in file_map:
            continue
        df = load_file(file_map[name])
        if df is None:
            continue
        cols = detect_columns(df)
        # Infer sampling frequency from timestamps
        dt_ms = float(df["Timestamp_ms"].iloc[1] - df["Timestamp_ms"].iloc[0])
        fs = 1.0 / (dt_ms / 1000.0)
        label = labels.get(name, {}).get("label") or name
        series = []
        for col in cols:
            v = df[col].values
            freqs, log_psd = psd_data(v, fs)
            series.append({
                "col":     col.replace("Voltage_", "").replace("_V", ""),
                "freqs":   freqs,
                "log_psd": log_psd,
            })
        result.append({"name": name, "label": label, "series": series})

    return jsonify(result)


@app.route("/api/histogram")
def api_histogram():
    names = request.args.getlist("names")
    labels = load_labels()
    file_map = {m["name"]: m["path"] for m in discover_files()}
    result = []

    for name in names:
        if name not in file_map:
            continue
        df = load_file(file_map[name])
        if df is None:
            continue
        cols = detect_columns(df)
        label = labels.get(name, {}).get("label") or name
        series = []
        for col in cols:
            centres, counts = histogram_data(df[col].values)
            series.append({
                "col":     col.replace("Voltage_", "").replace("_V", ""),
                "centres": centres,
                "counts":  counts,
            })
        result.append({"name": name, "label": label, "series": series})

    return jsonify(result)


@app.route("/api/stats")
def api_stats():
    names = request.args.getlist("names")
    labels = load_labels()
    file_map = {m["name"]: m["path"] for m in discover_files()}
    result = []

    for name in names:
        if name not in file_map:
            continue
        df = load_file(file_map[name])
        if df is None:
            continue
        cols = detect_columns(df)
        label = labels.get(name, {}).get("label") or name
        stats_per_col = {}
        for col in cols:
            stats_per_col[col.replace("Voltage_", "").replace("_V", "")] = compute_stats(df, col)
        result.append({"name": name, "label": label, "stats": stats_per_col})

    return jsonify(result)


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Noise Testing Dashboard → http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
