"""
Static Noise Recording Script with 50 Hz Mains Filtering
Records voltage data from Digilent oscilloscope and applies notch filters
at 50 Hz and its harmonics (100, 150, 200, ... Hz) before saving to CSV.
"""

import numpy as np
import pandas as pd
import ctypes
from scipy.signal import iirnotch, sosfilt, tf2sos
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


def apply_notch_filters(data, sampling_frequency, fundamental=50.0, quality_factor=30.0):
    """
    Apply cascaded notch filters at 50 Hz and all harmonics up to the Nyquist frequency.

    Parameters
    ----------
    data : np.ndarray
        Raw voltage samples.
    sampling_frequency : float
        Sampling rate in Hz.
    fundamental : float
        Mains frequency to remove (default 50 Hz).
    quality_factor : float
        Q-factor controlling notch bandwidth.
        Higher Q = narrower notch (default 30).
        Bandwidth ≈ fundamental / Q  →  ~1.7 Hz at Q=30.

    Returns
    -------
    np.ndarray
        Filtered voltage samples.
    """
    nyquist = sampling_frequency / 2.0
    filtered = data.copy()

    harmonic = fundamental
    notch_freqs = []
    while harmonic < nyquist:
        notch_freqs.append(harmonic)
        harmonic += fundamental

    print(f"Applying notch filters at: {[f'{f:.0f} Hz' for f in notch_freqs]}")

    for freq in notch_freqs:
        b, a = iirnotch(w0=freq, Q=quality_factor, fs=sampling_frequency)
        sos = tf2sos(b, a)
        filtered = sosfilt(sos, filtered)

    return filtered


def record_static_noise_filtered(duration_seconds=5, sampling_frequency=500e3,
                                  amplitude_range=50, channel=0,
                                  fundamental=50.0, quality_factor=30.0):
    """
    Record noise from oscilloscope and filter out 50 Hz mains interference
    and its harmonics.

    Parameters
    ----------
    duration_seconds : float
        Recording duration in seconds.
    sampling_frequency : float
        Oscilloscope sampling rate in Hz.
    amplitude_range : float
        Input voltage range in volts (peak-to-peak).
    channel : int
        Oscilloscope channel index (0-based).
    fundamental : float
        Mains frequency to suppress (default 50 Hz).
    quality_factor : float
        Notch filter Q-factor (default 30).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: Timestamp_ms, Voltage_Raw_V, Voltage_Filtered_V
    """
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
        dwf.FDwfAnalogInRecordLengthSet(device_handle, ctypes.c_double(duration_seconds))

        print(f"Recording {duration_seconds}s at {sampling_frequency/1e3:.0f} kHz "
              f"({total_samples:,} samples)...")

        dwf.FDwfAnalogInConfigure(device_handle, ctypes.c_bool(False), ctypes.c_bool(True))

        # Collect data in chunks
        all_data = []
        samples_collected = 0

        while samples_collected < total_samples:
            sts = ctypes.c_byte()
            dwf.FDwfAnalogInStatus(device_handle, ctypes.c_bool(True), ctypes.byref(sts))

            if sts.value == 2:  # DwfStateDone
                break

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
                print(f"\rProgress: {progress:.1f}% ({samples_collected:,}/{total_samples:,})",
                      end='', flush=True)

        print()
        print(f"✓ Recorded {len(all_data):,} samples")

        raw_voltage = np.array(all_data)

        # Apply notch filters
        filtered_voltage = apply_notch_filters(
            raw_voltage, sampling_frequency,
            fundamental=fundamental,
            quality_factor=quality_factor
        )
        print("✓ Notch filters applied")

        timestamp_ms = np.arange(len(raw_voltage)) / (sampling_frequency / 1000)
        df = pd.DataFrame({
            'Timestamp_ms': timestamp_ms,
            'Voltage_Raw_V': raw_voltage,
            'Voltage_Filtered_V': filtered_voltage
        })

        return df

    finally:
        dwf.FDwfAnalogInReset(device_handle)
        dwf.FDwfDeviceClose(device_handle)


def main():
    df = record_static_noise_filtered(
        duration_seconds=5,
        sampling_frequency=500e3,
        amplitude_range=50,
        channel=0,
        fundamental=50.0,
        quality_factor=30.0,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
    os.makedirs(output_dir, exist_ok=True)
    filename = f"static_noise_filtered_{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)

    df.to_csv(filepath, index=False)
    print(f"✓ Saved: {filepath}")

    # Summary statistics comparing raw vs filtered
    print("\n--- Noise Summary ---")
    print(f"Raw     RMS: {df['Voltage_Raw_V'].std() * 1e3:.4f} mV")
    print(f"Filtered RMS: {df['Voltage_Filtered_V'].std() * 1e3:.4f} mV")


if __name__ == "__main__":
    main()
