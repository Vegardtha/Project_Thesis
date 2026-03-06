"""
Static Noise Recording Script
Records voltage data from a Digilent Analog Discovery oscilloscope and saves to CSV.

Usage examples:
    # Baseline: short CH1+ to CH1- before running this
    python record_static_noise.py --label reference_shorted --note "input shorted, session start"

    # Test condition
    python record_static_noise.py --label TENG_open_circuit --note "TENG electrodes 5cm apart"
    python record_static_noise.py --label TENG_with_filter --note "RC low-pass 1kHz"

    # Custom duration / range
    python record_static_noise.py --duration 10 --range 1 --label shorted_1V
"""

import argparse
import json
import numpy as np
import pandas as pd
import ctypes
from sys import platform
from datetime import datetime
import os


def _initialize_dwf_library():
    """Load the DWF library"""
    if platform.startswith("win"):
        return ctypes.cdll.dwf
    elif platform.startswith("darwin"):
        possible_paths = [
            "/Applications/WaveForms.app/Contents/Frameworks/dwf.framework/dwf",
            "/Library/Frameworks/dwf.framework/dwf",
        ]
        for lib_path in possible_paths:
            try:
                return ctypes.cdll.LoadLibrary(lib_path)
            except OSError:
                continue
        raise OSError("Could not find dwf.framework")
    else:
        return ctypes.cdll.LoadLibrary("libdwf.so")


def record_static_noise(duration_seconds=5, sampling_frequency=500e3,
                        amplitude_range=5, channel=0):
    """Record noise from oscilloscope using record mode for long acquisitions"""
    
    dwf = _initialize_dwf_library()
    device_handle = ctypes.c_int()
    dwf.FDwfDeviceOpen(ctypes.c_int(-1), ctypes.byref(device_handle))
    
    if device_handle.value == 0:
        raise ConnectionError("Failed to open Digilent device")
    
    try:
        total_samples = int(sampling_frequency * duration_seconds)
        
        # Configure channel
        dwf.FDwfAnalogInChannelEnableSet(device_handle, ctypes.c_int(channel), 
                                         ctypes.c_bool(True))
        dwf.FDwfAnalogInChannelRangeSet(device_handle, ctypes.c_int(channel), 
                                        ctypes.c_double(amplitude_range))
        dwf.FDwfAnalogInFrequencySet(device_handle, ctypes.c_double(sampling_frequency))
        
        # Use record mode (acqmodeRecord = 3)
        dwf.FDwfAnalogInAcquisitionModeSet(device_handle, ctypes.c_int(3))
        
        # Set record length
        dwf.FDwfAnalogInRecordLengthSet(device_handle, ctypes.c_double(duration_seconds))
        
        print(f"Recording {duration_seconds}s at {sampling_frequency/1e3:.0f} kHz ({total_samples:,} samples)...")
        
        # Start recording
        dwf.FDwfAnalogInConfigure(device_handle, ctypes.c_bool(False), ctypes.c_bool(True))
        
        # Collect data in chunks
        all_data = []
        samples_collected = 0
        device_done = False  # set when DwfStateDone is received
        consecutive_empty = 0  # guard against momentary available=0 between USB chunks

        while samples_collected < total_samples:
            sts = ctypes.c_byte()
            dwf.FDwfAnalogInStatus(device_handle, ctypes.c_bool(True), ctypes.byref(sts))

            if sts.value == 2:  # DwfStateDone
                device_done = True

            # Always read the available count, even when done, to drain the buffer fully
            available = ctypes.c_int()
            lost = ctypes.c_int()
            corrupted = ctypes.c_int()
            dwf.FDwfAnalogInStatusRecord(device_handle, ctypes.byref(available),
                                         ctypes.byref(lost), ctypes.byref(corrupted))

            if lost.value:
                print(f"Warning: Lost {lost.value} samples!")
            if corrupted.value:
                print(f"Warning: Corrupted {corrupted.value} samples!")

            if available.value > 0:
                chunk_size = min(available.value, total_samples - samples_collected)
                data_buffer = (ctypes.c_double * chunk_size)()
                dwf.FDwfAnalogInStatusData(device_handle, channel, data_buffer, chunk_size)
                all_data.extend(data_buffer)
                samples_collected += chunk_size

                progress = (samples_collected / total_samples) * 100
                print(f"\rProgress: {progress:.1f}% ({samples_collected:,}/{total_samples:,})", end='', flush=True)

            # Only exit once the device is done AND the buffer is confirmed empty
            # Require 3 consecutive polls with available=0 to guard against momentary gaps
            if device_done and available.value == 0:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
            else:
                consecutive_empty = 0
        
        print()  # New line after progress
        print(f"✓ Recorded {len(all_data):,} samples")
        
        # Create DataFrame
        voltage_data = np.array(all_data)
        timestamp = np.arange(len(voltage_data)) / (sampling_frequency / 1000)
        df = pd.DataFrame({
            'Timestamp_ms': timestamp,
            'Voltage_V': voltage_data
        })
        
        return df
        
    finally:
        dwf.FDwfAnalogInReset(device_handle)
        dwf.FDwfDeviceClose(device_handle)


def main():
    parser = argparse.ArgumentParser(description="Record static noise from Analog Discovery")
    parser.add_argument("--duration",  type=float, default=5,     help="Recording duration in seconds (default: 5)")
    parser.add_argument("--freq",      type=float, default=500e3,  help="Sampling frequency in Hz (default: 500000)")
    parser.add_argument("--range",     type=float, default=5,      help="Amplitude range in V peak-to-peak (default: 5 → ±2.5 V)")
    parser.add_argument("--channel",   type=int,   default=0,      help="Oscilloscope channel index (default: 0)")
    parser.add_argument("--label",     type=str,   default="",     help="Short label for this recording, e.g. 'reference_shorted'")
    parser.add_argument("--note",      type=str,   default="",     help="Free-text note saved alongside the recording")
    args = parser.parse_args()

    if not args.label:
        print("Tip: use --label to tag this recording (e.g. --label reference_shorted)")

    # Record data
    df = record_static_noise(
        duration_seconds=args.duration,
        sampling_frequency=args.freq,
        amplitude_range=args.range,
        channel=args.channel,
    )

    # Save to CSV
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
    os.makedirs(output_dir, exist_ok=True)
    filename = f"static_noise_{ts}.csv"
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    print(f"✓ Saved: {filepath}")

    # Persist label + note into noise_labels.json so the dashboard picks them up immediately
    if args.label or args.note:
        labels_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "noise_labels.json")
        labels = {}
        if os.path.exists(labels_file):
            with open(labels_file) as f:
                labels = json.load(f)
        labels[filename] = {"label": args.label, "note": args.note}
        with open(labels_file, "w") as f:
            json.dump(labels, f, indent=2)
        print(f"✓ Label '{args.label}' saved to noise_labels.json")


if __name__ == "__main__":
    main()
