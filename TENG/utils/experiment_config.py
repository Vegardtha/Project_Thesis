"""
Experiment Configuration for TENG Testing
Centralized configuration for oscilloscope settings and data acquisition
"""

from dataclasses import dataclass
from datetime import datetime
import os


@dataclass
class ArduinoConfig:
    """Arduino motor controller configuration"""
    port: str = "COM3"          # Serial port (e.g. COM3 on Windows, /dev/ttyUSB0 on Linux)
    baud_rate: int = 115200
    timeout: float = 1.0        # Serial read timeout (s)
    impact_wait_s: float = 6.0  # Max seconds to wait for IMPACT message after acquisition


@dataclass
class OscilloscopeConfig:
    """Oscilloscope configuration"""
    # Acquisition settings
    sampling_frequency: float = 2e6  # 2 MHz
    acquisition_time_ms: float = 30  # Duration per acquisition (ms)
    
    # Channel settings
    channel: int = 0  # 0 = Channel 1, 1 = Channel 2
    offset: float = 0.0  # Voltage offset (V)
    amplitude_range: float = 50.0  # ±50V range
    
    # Trigger settings
    trigger_channel: int = 0  # Channel to trigger on
    trigger_level: float = 0.5  # Trigger voltage threshold (V)
    trigger_edge: str = "rising"  # "rising" or "falling"


@dataclass
class ExperimentConfig:
    """Complete experiment configuration"""
    # Experiment identification
    name: str = "TENG_Test"
    description: str = "Triboelectric nanogenerator impact testing"
    num_acquisitions: int = 10  # Number of data acquisitions to record
    
    # Hardware configurations
    oscilloscope: OscilloscopeConfig = None
    arduino: ArduinoConfig = None   # Set to ArduinoConfig(...) to enable Arduino integration

    # Data output
    output_dir: str = "experiments"
    save_plots: bool = True
    
    def __post_init__(self):
        if self.oscilloscope is None:
            self.oscilloscope = OscilloscopeConfig()
    
    def get_output_directory(self):
        """
        Create and return timestamped output directory for this experiment
        
        Returns:
            path: Path to the experiment output directory
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        exp_dir = os.path.join(self.output_dir, f"{self.name}_{timestamp}")
        os.makedirs(exp_dir, exist_ok=True)
        return exp_dir
    
    def save_config_to_file(self, directory):
        """
        Save configuration to a text file for documentation
        
        Parameters:
            directory: Directory to save the config file
        """
        config_path = os.path.join(directory, "experiment_config.txt")
        
        with open(config_path, 'w') as f:
            f.write("="*70 + "\n")
            f.write(f"TENG EXPERIMENT CONFIGURATION\n")
            f.write("="*70 + "\n\n")
            
            f.write(f"Experiment: {self.name}\n")
            f.write(f"Description: {self.description}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Number of Acquisitions: {self.num_acquisitions}\n\n")
            
            f.write("-"*70 + "\n")
            f.write("OSCILLOSCOPE SETTINGS\n")
            f.write("-"*70 + "\n")
            f.write(f"Sampling Frequency: {self.oscilloscope.sampling_frequency/1e6:.1f} MHz\n")
            f.write(f"Acquisition Time: {self.oscilloscope.acquisition_time_ms} ms\n")
            f.write(f"Channel: {self.oscilloscope.channel + 1}\n")
            f.write(f"Voltage Range: ±{self.oscilloscope.amplitude_range} V\n")
            f.write(f"Voltage Offset: {self.oscilloscope.offset} V\n")
            f.write(f"Trigger Channel: {self.oscilloscope.trigger_channel + 1}\n")
            f.write(f"Trigger Level: {self.oscilloscope.trigger_level} V\n")
            f.write(f"Trigger Edge: {self.oscilloscope.trigger_edge}\n\n")

            if self.arduino is not None:
                f.write("-"*70 + "\n")
                f.write("ARDUINO SETTINGS\n")
                f.write("-"*70 + "\n")
                f.write(f"Port: {self.arduino.port}\n")
                f.write(f"Baud Rate: {self.arduino.baud_rate}\n")
                f.write(f"Impact Wait Timeout: {self.arduino.impact_wait_s} s\n\n")

            f.write("-"*70 + "\n")
            f.write("DATA OUTPUT\n")
            f.write("-"*70 + "\n")
            f.write(f"Output Directory: {directory}\n")
            f.write(f"Save Plots: {self.save_plots}\n")
            
    
    def __str__(self):
        """String representation for printing"""
        return (
            f"Experiment: {self.name}\n"
            f"Acquisitions: {self.num_acquisitions}\n"
            f"Sampling: {self.oscilloscope.sampling_frequency/1e6:.1f} MHz\n"
            f"Acquisition: {self.oscilloscope.acquisition_time_ms} ms\n"
            f"Voltage Range: ±{self.oscilloscope.amplitude_range} V"
        )
