"""
Oscilloscope Module for TENG Experiments
Handles communication with Digilent Analog Discovery oscilloscope
"""

import time
import numpy as np
import ctypes
from sys import platform
from os import sep
import sys
import os
from utils.dwfconstants import *



class OscilloscopeController:
    """
    Controls Digilent Analog Discovery oscilloscope for voltage measurements
    """
    
    def __init__(self):
        """Initialize oscilloscope controller"""
        self.dwf = self._initialize_dwf_library()
        self.device_handle = None
        self.is_connected = False
        
    def _initialize_dwf_library(self):
        """Load the DWF library based on the current platform"""
        if platform.startswith("win"):
            return ctypes.cdll.dwf
        elif platform.startswith("darwin"):
            # macOS - try multiple possible locations
            possible_paths = [
                "/Applications/WaveForms.app/Contents/Frameworks/dwf.framework/dwf",
                "/Library/Frameworks/dwf.framework/dwf",
                sep + "Library" + sep + "Frameworks" + sep + "dwf.framework" + sep + "dwf"
            ]
            
            for lib_path in possible_paths:
                try:
                    return ctypes.cdll.LoadLibrary(lib_path)
                except OSError:
                    continue
            
            raise OSError(
                "Could not find dwf.framework. Please install Digilent WaveForms from:\n"
                "https://digilent.com/shop/software/digilent-waveforms/"
            )
        else:
            # Linux
            return ctypes.cdll.LoadLibrary("libdwf.so")
    
    def connect(self):
        """Connect to the first available device"""
        device_handle = ctypes.c_int()
        self.dwf.FDwfDeviceOpen(ctypes.c_int(-1), ctypes.byref(device_handle))
        self.device_handle = device_handle
        self.is_connected = True

        
    def disconnect(self):
        """Disconnect and reset the device"""
        if self.is_connected and self.device_handle:
            self.dwf.FDwfAnalogInReset(self.device_handle)
            self.dwf.FDwfDeviceClose(self.device_handle)
            self.device_handle = None
            self.is_connected = False
            print("✓ Oscilloscope disconnected")
    
    def configure(self, sampling_frequency=2e6, buffer_size=10, offset=0, 
                  amplitude_range=50, channel=0):
        """
        Configure oscilloscope acquisition parameters
        
        Parameters:
            sampling_frequency: Sampling rate in Hz (default: 2 MHz)
            buffer_size: Number of samples per acquisition (default: 10)
            offset: Voltage offset in Volts (default: 0V)
            amplitude_range: Voltage range in Volts (default: ±50V)
            channel: Channel number (default: 0 for Channel 1)
        """
        if not self.is_connected:
            raise ConnectionError("Oscilloscope not connected. Call connect() first.")
        
        # Enable channel
        self.dwf.FDwfAnalogInChannelEnableSet(self.device_handle, ctypes.c_int(channel), 
                                              ctypes.c_bool(True))
        
        # Set offset voltage
        self.dwf.FDwfAnalogInChannelOffsetSet(self.device_handle, ctypes.c_int(channel), 
                                              ctypes.c_double(offset))
        
        # Set voltage range
        self.dwf.FDwfAnalogInChannelRangeSet(self.device_handle, ctypes.c_int(channel), 
                                             ctypes.c_double(amplitude_range))
        
        # Set buffer size
        self.dwf.FDwfAnalogInBufferSizeSet(self.device_handle, ctypes.c_int(buffer_size))
        
        # Set sampling frequency
        self.dwf.FDwfAnalogInFrequencySet(self.device_handle, ctypes.c_double(sampling_frequency))
        
        # Disable averaging
        self.dwf.FDwfAnalogInChannelFilterSet(self.device_handle, ctypes.c_int(-1), filterDecimate)
        
        print(f"✓ Oscilloscope configured: {sampling_frequency/1e6:.1f} MHz, ±{amplitude_range}V")
    
    def setup_trigger(self, trigger_channel=0, trigger_level=0.5, 
                     trigger_condition=trigcondRisingPositive):
        """
        Configure trigger settings
        
        Parameters:
            trigger_channel: Channel to trigger on (default: 0 for Channel 1)
            trigger_level: Trigger voltage threshold in Volts (default: 0.5V)
            trigger_condition: Trigger edge type (default: rising edge)
        """
        if not self.is_connected:
            raise ConnectionError("Oscilloscope not connected. Call connect() first.")
        
        # Set trigger source to analog input
        self.dwf.FDwfAnalogInTriggerSourceSet(self.device_handle, trigsrcDetectorAnalogIn)
        
        # Set trigger channel
        self.dwf.FDwfAnalogInTriggerChannelSet(self.device_handle, ctypes.c_int(trigger_channel))
        
        # Set trigger level
        self.dwf.FDwfAnalogInTriggerLevelSet(self.device_handle, ctypes.c_double(trigger_level))
        
        # Set trigger condition
        self.dwf.FDwfAnalogInTriggerConditionSet(self.device_handle, trigger_condition)
        
        print(f"✓ Trigger configured: Channel {trigger_channel + 1}, {trigger_level}V threshold")
    
    def configure_acquisition_time(self, acquisition_time_ms, sampling_freq):
        """
        Configure digital I/O and calculate number of samples
        
        Parameters:
            acquisition_time_ms: Acquisition duration in milliseconds
            sampling_freq: Sampling frequency in Hz
            
        Returns:
            num_samples: Number of samples that will be acquired
        """
        if not self.is_connected:
            raise ConnectionError("Oscilloscope not connected. Call connect() first.")
        
        # Set DIO as output (for trigger signal to Arduino)
        self.dwf.FDwfDigitalIOOutputEnableSet(self.device_handle, ctypes.c_int(0b00000010))
        
        # Calculate and set buffer size - FIXED: divide by 1000, not 1800!
        num_samples = int(sampling_freq * (acquisition_time_ms / 1000))
        self.dwf.FDwfAnalogInBufferSizeSet(self.device_handle, ctypes.c_int(num_samples))
        
        print(f"✓ Buffer configured: {num_samples:,} samples ({acquisition_time_ms} ms @ {sampling_freq/1e6:.1f} MHz)")
        
        return num_samples
    
    def acquire_single(self, num_samples, channel=0):
        """
        Perform a single triggered acquisition
        
        Parameters:
            num_samples: Number of samples to acquire
            channel: Channel to read from (default: 0 for Channel 1)
            
        Returns:
            voltage_data: NumPy array of voltage measurements
        """
        if not self.is_connected:
            raise ConnectionError("Oscilloscope not connected. Call connect() first.")
        
        # Start acquisition
        self.dwf.FDwfAnalogInConfigure(self.device_handle, ctypes.c_bool(False), ctypes.c_bool(True))
        
        # Set DIO 1 HIGH (trigger signal)
        self.dwf.FDwfDigitalIOOutputSet(self.device_handle, ctypes.c_int(0b00000010))
        
        # Wait for acquisition to complete
        sts = ctypes.c_byte()
        while True:
            self.dwf.FDwfAnalogInStatus(self.device_handle, ctypes.c_bool(True), ctypes.byref(sts))
            if sts.value == DwfStateDone.value:
                break
            time.sleep(0.01)
        
        # Retrieve data
        data_buffer = (ctypes.c_double * num_samples)()
        self.dwf.FDwfAnalogInStatusData(self.device_handle, channel, data_buffer, num_samples)
        voltage_data = np.array(data_buffer)
        
        # Set DIO 1 LOW
        self.dwf.FDwfDigitalIOOutputSet(self.device_handle, ctypes.c_int(0b00000000))
        
        return voltage_data
    
    def create_timestamp_array(self, num_samples, sampling_freq):
        """
        Create timestamp array in milliseconds
        
        Parameters:
            num_samples: Number of samples
            sampling_freq: Sampling frequency in Hz
            
        Returns:
            timestamp: NumPy array of timestamps in milliseconds
        """
        return np.arange(num_samples) / (sampling_freq / 1000)
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
