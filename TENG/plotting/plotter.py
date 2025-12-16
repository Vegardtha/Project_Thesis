import os
import glob
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import re

def natural_sort_key(s):
    """Key for natural sorting of strings containing numbers"""
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

def load_cycles(experiment_dir):
    """Load all cycle CSV files from the experiment directory"""
    pattern = os.path.join(experiment_dir, "cycle_*.csv")
    files = glob.glob(pattern)
    files.sort(key=natural_sort_key)
    
    cycles = []
    for f in files:
        try:
            # Extract cycle number from filename
            basename = os.path.basename(f)
            match = re.search(r'cycle_(\d+)\.csv', basename)
            if match:
                cycle_num = int(match.group(1))
                df = pd.read_csv(f)
                cycles.append((cycle_num, df))
        except Exception as e:
            print(f"Error loading {f}: {e}")
            
    return cycles


def find_missing_cycles(experiment_dir, expected_max=4005):
    """
    Find missing cycle numbers in the experiment directory
    
    Parameters:
        experiment_dir: Path to experiment directory
        expected_max: Maximum expected cycle number (default: 4005)
    
    Returns:
        List of missing cycle numbers
    """
    pattern = os.path.join(experiment_dir, "cycle_*.csv")
    files = glob.glob(pattern)
    
    # Extract all cycle numbers that exist
    existing_cycles = set()
    for f in files:
        basename = os.path.basename(f)
        match = re.search(r'cycle_(\d+)\.csv', basename)
        if match:
            cycle_num = int(match.group(1))
            existing_cycles.add(cycle_num)
    
    # Find missing cycles
    expected_cycles = set(range(1, expected_max + 1))
    missing_cycles = sorted(expected_cycles - existing_cycles)
    
    return missing_cycles, existing_cycles

def plot_overlay(cycles, output_dir, title_suffix="", filename_suffix=""):
    """Plot multiple cycles overlaid on one plot"""
    if not cycles:
        print("No cycles to plot.")
        return

    plt.figure(figsize=(12, 6))
    
    for cycle_num, df in cycles:
        plt.plot(df['Timestamp_ms'], df['Voltage_V'], alpha=0.3, linewidth=0.5)
        
    plt.xlabel("Time (ms)")
    plt.ylabel("Voltage (V)")
    plt.title(f"Waveforms Overlay {title_suffix} ({len(cycles)} cycles)")
    plt.grid(alpha=0.3)
    
    filename = f"overlay_{filename_suffix}.png" if filename_suffix else "overlay.png"
    save_path = os.path.join(output_dir, filename)
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"Saved overlay plot: {save_path}")

def plot_chunks(cycles, output_dir, chunk_size):
    """Plot cycles in chunks"""
    # Sort cycles by cycle number just in case
    cycles.sort(key=lambda x: x[0])
    
    total_cycles = len(cycles)
    num_chunks = (total_cycles + chunk_size - 1) // chunk_size
    
    print(f"Plotting {num_chunks} chunks of size {chunk_size}...")
    
    for i in range(num_chunks):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, total_cycles)
        
        chunk_cycles = cycles[start_idx:end_idx]
        
        if not chunk_cycles:
            continue
            
        start_cycle = chunk_cycles[0][0]
        end_cycle = chunk_cycles[-1][0]
        
        title_suffix = f"- Cycles {start_cycle} to {end_cycle}"
        filename_suffix = f"cycles_{start_cycle}_{end_cycle}"
        
        plot_overlay(chunk_cycles, output_dir, title_suffix, filename_suffix)

def analyze_statistics(cycles, output_dir):
    """Perform statistical analysis on the experiment"""
    print("Analyzing statistics...")
    
    stats_data = []
    
    for cycle_num, df in cycles:
        voltage = df['Voltage_V']
        peak_voltage = np.max(np.abs(voltage))
        max_voltage = np.max(voltage)
        min_voltage = np.min(voltage)
        mean_voltage = np.mean(voltage)
        std_voltage = np.std(voltage)
        
        stats_data.append({
            'Cycle': cycle_num,
            'Peak_Voltage_V': peak_voltage,
            'Max_Voltage_V': max_voltage,
            'Min_Voltage_V': min_voltage,
            'Mean_Voltage_V': mean_voltage,
            'Std_Voltage_V': std_voltage
        })
    
    stats_df = pd.DataFrame(stats_data)
    stats_csv_path = os.path.join(output_dir, "detailed_statistics.csv")
    stats_df.to_csv(stats_csv_path, index=False)
    print(f"Saved detailed statistics to {stats_csv_path}")
    
    # Global statistics
    print("\n--- Global Statistics ---")
    print(f"Total Cycles: {len(cycles)}")
    print(f"Average Peak Voltage: {stats_df['Peak_Voltage_V'].mean():.2f} V")
    print(f"Max Peak Voltage: {stats_df['Peak_Voltage_V'].max():.2f} V (Cycle {stats_df.loc[stats_df['Peak_Voltage_V'].idxmax(), 'Cycle']})")
    print(f"Min Peak Voltage: {stats_df['Peak_Voltage_V'].min():.2f} V (Cycle {stats_df.loc[stats_df['Peak_Voltage_V'].idxmin(), 'Cycle']})")
    print(f"Std Dev of Peak Voltage: {stats_df['Peak_Voltage_V'].std():.2f} V")

    # Plot Peak Voltage Trend
    plt.figure(figsize=(12, 6))
    plt.plot(stats_df['Cycle'], stats_df['Peak_Voltage_V'], 'b-', linewidth=1, alpha=0.7)
    plt.axhline(y=stats_df['Peak_Voltage_V'].mean(), color='r', linestyle='--', label=f"Mean: {stats_df['Peak_Voltage_V'].mean():.2f} V")
    plt.xlabel("Cycle Number")
    plt.ylabel("Peak Voltage (V)")
    plt.title("Peak Voltage vs Cycle Number")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.savefig(os.path.join(output_dir, "peak_voltage_trend.png"), dpi=150)
    plt.close()
    
    # Histogram of Peak Voltages
    plt.figure(figsize=(10, 6))
    plt.hist(stats_df['Peak_Voltage_V'], bins=30, edgecolor='black', alpha=0.7)
    plt.axvline(x=stats_df['Peak_Voltage_V'].mean(), color='r', linestyle='--', label=f"Mean: {stats_df['Peak_Voltage_V'].mean():.2f} V")
    plt.xlabel("Peak Voltage (V)")
    plt.ylabel("Count")
    plt.title("Distribution of Peak Voltages")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.savefig(os.path.join(output_dir, "peak_voltage_distribution.png"), dpi=150)
    plt.close()


def plot_averaged_groups(cycles, output_dir, group_size=500):
    """
    Plot averaged waveforms for groups of cycles
    Each line represents the average of group_size cycles
    
    Parameters:
        cycles: List of (cycle_num, dataframe) tuples
        output_dir: Directory to save the plot
        group_size: Number of cycles to average together (default: 500)
    """
    print(f"\nGenerating averaged waveform plot (groups of {group_size})...")
    
    # Sort cycles by cycle number
    cycles.sort(key=lambda x: x[0])
    
    if not cycles:
        print("No cycles to plot.")
        return
    
    total_cycles = len(cycles)
    num_groups = (total_cycles + group_size - 1) // group_size
    
    plt.figure(figsize=(14, 7))
    
    colors = plt.cm.viridis(np.linspace(0, 1, num_groups))
    
    for i in range(num_groups):
        start_idx = i * group_size
        end_idx = min((i + 1) * group_size, total_cycles)
        
        group_cycles = cycles[start_idx:end_idx]
        
        if not group_cycles:
            continue
        
        start_cycle = group_cycles[0][0]
        end_cycle = group_cycles[-1][0]
        
        # Get all dataframes for this group and align them
        group_dfs = [df for _, df in group_cycles]
        
        # Find common time range (use the shortest)
        min_length = min(len(df) for df in group_dfs)
        
        # Truncate all to same length and average
        truncated_dfs = [df.iloc[:min_length].copy() for df in group_dfs]
        
        # Calculate average voltage
        avg_voltage = np.mean([df['Voltage_V'].values for df in truncated_dfs], axis=0)
        timestamp = truncated_dfs[0]['Timestamp_ms'].values
        
        # Plot the averaged line
        label = f"Cycles {start_cycle}-{end_cycle} (n={len(group_cycles)})"
        plt.plot(timestamp, avg_voltage, color=colors[i], linewidth=2, label=label, alpha=0.8)
    
    plt.xlabel("Time (ms)")
    plt.ylabel("Voltage (V)")
    plt.title(f"Averaged Waveforms by Groups of {group_size} Cycles")
    plt.legend(loc='best', fontsize=9)
    plt.grid(alpha=0.3)
    
    save_path = os.path.join(output_dir, f"averaged_groups_{group_size}.png")
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"✓ Saved averaged groups plot: {save_path}")


def plot_missing_cycles_visualization(missing_cycles, existing_cycles, output_dir, expected_max=4005):
    """
    Create visualizations showing where missing cycles occur
    
    Parameters:
        missing_cycles: List of missing cycle numbers
        existing_cycles: Set of existing cycle numbers
        output_dir: Directory to save the plots
        expected_max: Maximum expected cycle number
    """
    print("\nGenerating missing cycles visualization...")
    
    if not missing_cycles:
        print("No missing cycles to visualize!")
        return
    
    # Create a binary array: 1 for existing, 0 for missing
    cycle_status = np.zeros(expected_max)
    for cycle in existing_cycles:
        if 1 <= cycle <= expected_max:
            cycle_status[cycle - 1] = 1
    
    # Figure 1: Timeline visualization
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 8))
    
    # Top plot: Binary timeline
    cycle_numbers = np.arange(1, expected_max + 1)
    colors_map = ['red' if status == 0 else 'green' for status in cycle_status]
    
    ax1.scatter(cycle_numbers, cycle_status, c=colors_map, s=1, alpha=0.6)
    ax1.set_xlabel("Cycle Number")
    ax1.set_ylabel("Status")
    ax1.set_yticks([0, 1])
    ax1.set_yticklabels(['Missing', 'Present'])
    ax1.set_title(f"Cycle Data Availability Timeline (Total: {expected_max}, Missing: {len(missing_cycles)})")
    ax1.grid(alpha=0.3, axis='x')
    ax1.set_xlim(0, expected_max + 1)
    
    # Bottom plot: Histogram showing distribution of missing cycles
    ax2.hist(missing_cycles, bins=50, color='red', alpha=0.7, edgecolor='black')
    ax2.set_xlabel("Cycle Number")
    ax2.set_ylabel("Number of Missing Cycles in Range")
    ax2.set_title("Distribution of Missing Cycles")
    ax2.grid(alpha=0.3)
    ax2.set_xlim(0, expected_max + 1)
    
    plt.tight_layout()
    save_path = os.path.join(output_dir, "missing_cycles_timeline.png")
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"✓ Saved missing cycles timeline: {save_path}")
    
    # Figure 2: Heatmap-style visualization (grouped in bins of 100)
    fig, ax = plt.subplots(figsize=(14, 8))
    
    bin_size = 100
    num_bins = (expected_max + bin_size - 1) // bin_size
    
    # Calculate completeness percentage for each bin
    completeness = []
    bin_labels = []
    
    for i in range(num_bins):
        start = i * bin_size + 1
        end = min((i + 1) * bin_size, expected_max)
        
        cycles_in_bin = sum(1 for c in existing_cycles if start <= c <= end)
        expected_in_bin = end - start + 1
        completeness_pct = (cycles_in_bin / expected_in_bin) * 100
        
        completeness.append(completeness_pct)
        bin_labels.append(f"{start}-{end}")
    
    # Create bar chart
    x_pos = np.arange(len(bin_labels))
    colors_bar = ['red' if pct < 100 else 'green' for pct in completeness]
    
    bars = ax.bar(x_pos, completeness, color=colors_bar, alpha=0.7, edgecolor='black')
    
    # Add percentage labels on bars
    for i, (bar, pct) in enumerate(zip(bars, completeness)):
        height = bar.get_height()
        if pct < 100:
            ax.text(bar.get_x() + bar.get_width()/2., height + 1,
                   f'{pct:.1f}%', ha='center', va='bottom', fontsize=8)
    
    ax.set_xlabel("Cycle Range")
    ax.set_ylabel("Data Completeness (%)")
    ax.set_title(f"Data Completeness by {bin_size}-Cycle Bins")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(bin_labels, rotation=45, ha='right')
    ax.set_ylim(0, 110)
    ax.axhline(y=100, color='black', linestyle='--', linewidth=1, alpha=0.5)
    ax.grid(alpha=0.3, axis='y')
    
    plt.tight_layout()
    save_path = os.path.join(output_dir, "missing_cycles_completeness.png")
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"✓ Saved data completeness chart: {save_path}")


def main():
    experiment_path = "/home/troll1234/Documents/TENG/TENG/experiments/LongBeltTest_20251201_172747"
    
    # Create a directory for plots inside the experiment folder
    plots_dir = os.path.join(experiment_path, "plots_analysis")
    os.makedirs(plots_dir, exist_ok=True)
    
    # Check for missing cycles first
    print("="*70)
    print("CHECKING FOR MISSING CYCLES")
    print("="*70)
    missing_cycles, existing_cycles = find_missing_cycles(experiment_path, expected_max=4005)
    
    print(f"\nExpected cycles: 1 to 4005")
    print(f"Found cycles: {len(existing_cycles)}")
    print(f"Missing cycles: {len(missing_cycles)}")
    
    if missing_cycles:
        print(f"\n⚠ Missing {len(missing_cycles)} cycles!")
        
        # Find gaps (consecutive missing cycles)
        gaps = []
        if missing_cycles:
            gap_start = missing_cycles[0]
            gap_end = missing_cycles[0]
            
            for i in range(1, len(missing_cycles)):
                if missing_cycles[i] == gap_end + 1:
                    gap_end = missing_cycles[i]
                else:
                    gaps.append((gap_start, gap_end))
                    gap_start = missing_cycles[i]
                    gap_end = missing_cycles[i]
            gaps.append((gap_start, gap_end))
        
        print("\nMissing cycle ranges:")
        for start, end in gaps:
            if start == end:
                print(f"  Cycle {start}")
            else:
                print(f"  Cycles {start}-{end} ({end-start+1} missing)")
        
        # Save missing cycles to file
        missing_file = os.path.join(plots_dir, "missing_cycles.txt")
        with open(missing_file, 'w') as f:
            f.write(f"Missing Cycles Report\n")
            f.write(f"{'='*70}\n\n")
            f.write(f"Expected cycles: 1 to 4005\n")
            f.write(f"Found cycles: {len(existing_cycles)}\n")
            f.write(f"Missing cycles: {len(missing_cycles)}\n\n")
            f.write(f"Missing cycle ranges:\n")
            for start, end in gaps:
                if start == end:
                    f.write(f"  Cycle {start}\n")
                else:
                    f.write(f"  Cycles {start}-{end} ({end-start+1} missing)\n")
            f.write(f"\n\nAll missing cycle numbers:\n")
            f.write(", ".join(map(str, missing_cycles)))
        
        print(f"\n✓ Saved missing cycles report to: {missing_file}")
        
        # Generate visualizations of missing cycles
        plot_missing_cycles_visualization(missing_cycles, existing_cycles, plots_dir, expected_max=4005)
    else:
        print("\n✓ No missing cycles - all cycles from 1 to 4005 are present!")
    
    print("\n" + "="*70)
    
    print(f"\nLoading data from {experiment_path}...")
    cycles = load_cycles(experiment_path)
    print(f"Loaded {len(cycles)} cycles.")
    
    if not cycles:
        print("No data found!")
        return

    # 1. Plot all overlaid
    print("\nGenerating full overlay plot...")
    plot_overlay(cycles, plots_dir, title_suffix="(All Cycles)", filename_suffix="all")
    
    # 2. Plot in chunks of 500
    print("\nGenerating 500-cycle chunk plots...")
    plot_chunks(cycles, plots_dir, chunk_size=500)
    
    # 3. Plot in chunks of 1000
    print("\nGenerating 1000-cycle chunk plots...")
    plot_chunks(cycles, plots_dir, chunk_size=1000)
    
    # 4. Statistical Analysis
    print("\nPerforming statistical analysis...")
    analyze_statistics(cycles, plots_dir)
    
    # 5. Plot averaged groups of 500 cycles
    print("\nGenerating averaged waveform plot (500-cycle groups)...")
    plot_averaged_groups(cycles, plots_dir, group_size=500)
    
    print("\nDone! Check the 'plots_analysis' folder inside the experiment directory.")

if __name__ == "__main__":
    main()
