"""
TENG Experiment Runner - SIMPLE VERSION
Just configure your experiment settings and run!
"""

from utils import TENGExperiment, ExperimentConfig, OscilloscopeConfig


# ============================================================================
# CONFIGURE YOUR EXPERIMENT HERE
# ============================================================================

def main():
    # Configure your experiment
    config = ExperimentConfig(
        name="LongBeltTest",
        description="TENG impact testing",
        num_acquisitions=2,  # How many data acquisitions to record
        
        oscilloscope=OscilloscopeConfig(
            sampling_frequency=500e3,   # 0.5 MHz
            acquisition_time_ms=15,     # 30 ms buffer (max recording window)
            amplitude_range=50,         # ±25V (Range is peak-to-peak)
            trigger_level=0.5,          # Start recording at 0.5V
            channel=0                   # Oscilloscope channel (0=Ch1, 1=Ch2)
        ),
        
        save_plots=True
    )
    
    # Run the experiment
    print("="*70)
    print("STARTING EXPERIMENT:")
    print(f"Name: {config.name}")
    print(f"Acquisitions: {config.num_acquisitions}")
    print("="*70 + "\n")
    
    experiment = TENGExperiment(config)
    experiment.run()


if __name__ == "__main__":
    main()

