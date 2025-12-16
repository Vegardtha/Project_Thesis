"""
TENG Experiment Manager
Oscilloscope data acquisition for TENG experiments
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import ctypes
import time
from datetime import datetime
from .dwfconstants import trigcondRisingPositive, trigcondFallingNegative

from hardware import OscilloscopeController


class TENGExperiment:
    """
    Manages TENG data acquisition with triggered oscilloscope recording
    """
    
    def __init__(self, config):
        """Initialize experiment with configuration"""
        self.config = config
        self.oscilloscope = None
        self.output_dir = None
        self.results = []
        
    def setup(self):
        """Initialize hardware connections and create output directory"""
        
        # Create output directory
        self.output_dir = self.config.get_output_directory()
        print(f"Output directory: {self.output_dir}")
        
        # Save configuration
        self.config.save_config_to_file(self.output_dir)
        
        # Initialize oscilloscope
        self.oscilloscope = OscilloscopeController()
        self.oscilloscope.connect()
        
        # Configure oscilloscope
        self.oscilloscope.configure(
            sampling_frequency=self.config.oscilloscope.sampling_frequency,
            offset=self.config.oscilloscope.offset,
            amplitude_range=self.config.oscilloscope.amplitude_range,
            channel=self.config.oscilloscope.channel
        )
        
        # Setup trigger
        trigger_condition = (trigcondRisingPositive if self.config.oscilloscope.trigger_edge == "rising" 
                           else trigcondFallingNegative)
        self.oscilloscope.setup_trigger(
            trigger_channel=self.config.oscilloscope.trigger_channel,
            trigger_level=self.config.oscilloscope.trigger_level,
            trigger_condition=trigger_condition
        )
        
        # Configure acquisition time
        self.num_samples = self.oscilloscope.configure_acquisition_time(
            self.config.oscilloscope.acquisition_time_ms,
            self.config.oscilloscope.sampling_frequency
        )

        
    def acquire_single(self, acquisition_num):
        """Perform a single triggered data acquisition"""
        print(f"\nAcquisition {acquisition_num}/{self.config.num_acquisitions} - Waiting for trigger...")
        
        # Start acquisition in triggered mode - will wait for trigger event
        self.oscilloscope.dwf.FDwfAnalogInConfigure(self.oscilloscope.device_handle, 
                                                     ctypes.c_bool(False), 
                                                     ctypes.c_bool(True))
        
        # Set DIO 1 HIGH (trigger signal)
        self.oscilloscope.dwf.FDwfDigitalIOOutputSet(self.oscilloscope.device_handle, 
                                                      ctypes.c_int(0b00000010))
        
        # Wait for acquisition to complete
        sts = ctypes.c_byte()
        timeout = 30  # 30 second timeout
        start_time = time.time()
        
        while True:
            self.oscilloscope.dwf.FDwfAnalogInStatus(self.oscilloscope.device_handle, 
                                                      ctypes.c_bool(True), 
                                                      ctypes.byref(sts))
            if sts.value == 2:  # DwfStateDone
                break
            if time.time() - start_time > timeout:
                print(f"  ⚠ Timeout waiting for trigger!")
                return None
            time.sleep(0.01)
        
        # Retrieve data
        data_buffer = (ctypes.c_double * self.num_samples)()
        self.oscilloscope.dwf.FDwfAnalogInStatusData(self.oscilloscope.device_handle, 
                                                       self.config.oscilloscope.channel, 
                                                       data_buffer, 
                                                       self.num_samples)
        voltage_data = np.array(data_buffer)
        
        # Set DIO 1 LOW
        self.oscilloscope.dwf.FDwfDigitalIOOutputSet(self.oscilloscope.device_handle, 
                                                      ctypes.c_int(0b00000000))
        
        # Create timestamp array
        timestamp = self.oscilloscope.create_timestamp_array(
            self.num_samples,
            self.config.oscilloscope.sampling_frequency
        )
        
        # Create DataFrame
        df = pd.DataFrame({
            'Timestamp_ms': timestamp,
            'Voltage_V': voltage_data
        })
        
        # Calculate peak voltage
        peak_voltage = np.max(np.abs(voltage_data))
        
        # Save data
        csv_path = f"{self.output_dir}/acquisition_{acquisition_num:04d}.csv"
        df.to_csv(csv_path, index=False)
        print(f"✓ Peak: {peak_voltage:.2f} V - Saved: acquisition_{acquisition_num:04d}.csv")
        
        # Store result
        self.results.append({
            'acquisition': acquisition_num,
            'timestamp': datetime.now(),
            'peak_voltage': peak_voltage,
            'data': df
        })
            
        return df
    
    def run(self):
        """Execute complete experiment"""
        try:
            # Setup hardware
            self.setup()
            
            print(f"\n{'='*70}")

            
            # Run acquisitions
            for acquisition_num in range(1, self.config.num_acquisitions + 1):
                self.acquire_single(acquisition_num)
            
            # Generate summary
            self._generate_summary()
            
        except KeyboardInterrupt:
            print("\n\n⚠ Experiment interrupted by user")
            
        except Exception as e:
            print(f"\n\n✗ Error during experiment: {e}")
            raise
            
        finally:
            self.cleanup()
    
    def _generate_summary(self):
        """Generate experiment summary with statistics and plots"""
        print("\n" + "="*70)
        print("SUMMARY")
        print("="*70)
        
        if not self.results:
            print("⚠ No data collected")
            return
        
        # Extract statistics
        acquisitions = [r['acquisition'] for r in self.results]
        peak_voltages = [r['peak_voltage'] for r in self.results]
        
        # Summary statistics
        summary_df = pd.DataFrame({
            'Acquisition': acquisitions,
            'Peak_Voltage_V': peak_voltages
        })
        
        summary_path = f"{self.output_dir}/experiment_summary.csv"
        summary_df.to_csv(summary_path, index=False)
        
        # Statistics
        print(f"Total Acquisitions: {len(acquisitions)}")
        print(f"Mean Peak Voltage: {np.mean(peak_voltages):.2f} V")
        print(f"Std Dev: {np.std(peak_voltages):.2f} V")
        print(f"Max Peak: {np.max(peak_voltages):.2f} V")
        print(f"Min Peak: {np.min(peak_voltages):.2f} V")
        
        # Generate summary plots
        if self.config.save_plots:
            self._plot_summary(acquisitions, peak_voltages)
    
    def _plot_summary(self, acquisitions, peak_voltages):
        """Generate summary plots"""
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        
        # Peak voltage over acquisitions
        axes[0].plot(acquisitions, peak_voltages, 'o-', linewidth=2, markersize=6)
        axes[0].axhline(y=np.mean(peak_voltages), color='r', linestyle='--', 
                       label=f'Mean: {np.mean(peak_voltages):.2f} V', alpha=0.7)
        axes[0].set_xlabel("Acquisition Number")
        axes[0].set_ylabel("Peak Voltage (V)")
        axes[0].set_title("Peak Voltage vs Acquisition Number")
        axes[0].legend()
        axes[0].grid(alpha=0.3)
        
        # Histogram
        axes[1].hist(peak_voltages, bins=20, edgecolor='black', alpha=0.7)
        axes[1].axvline(x=np.mean(peak_voltages), color='r', linestyle='--', 
                       label=f'Mean: {np.mean(peak_voltages):.2f} V', linewidth=2)
        axes[1].set_xlabel("Peak Voltage (V)")
        axes[1].set_ylabel("Frequency")
        axes[1].set_title("Peak Voltage Distribution")
        axes[1].legend()
        axes[1].grid(alpha=0.3, axis='y')
        
        plt.tight_layout()
        summary_plot_path = f"{self.output_dir}/experiment_summary.png"
        plt.savefig(summary_plot_path, dpi=150)
        plt.close()
        
        # Overlay plot of all waveforms
        self._plot_all_waveforms_overlay()
    
    def _plot_all_waveforms_overlay(self):
        """Create overlay plot of all acquired waveforms"""
        plt.figure(figsize=(12, 6))
        
        for result in self.results:
            df = result['data']
            acq = result['acquisition']
            plt.plot(df['Timestamp_ms'], df['Voltage_V'], 
                    alpha=0.6, linewidth=0.8, label=f"Acq {acq}")
        
        plt.xlabel("Time (ms)")
        plt.ylabel("Voltage (V)")
        plt.title(f"All Waveforms Overlay - {len(self.results)} Acquisitions")
        plt.grid(alpha=0.3)
        
        # Only show legend if not too many acquisitions
        if len(self.results) <= 10:
            plt.legend(loc='best', fontsize=8)
        
        plt.tight_layout()
        overlay_path = f"{self.output_dir}/all_waveforms_overlay.png"
        plt.savefig(overlay_path, dpi=150)
        plt.close()
        print(f"Plots saved: experiment_summary.png, all_waveforms_overlay.png")
    
    def cleanup(self):
        """Disconnect hardware"""
        if self.oscilloscope:
            self.oscilloscope.disconnect()
            
        print("EXPERIMENT COMPLETE")
        print("="*70 + "\n")
