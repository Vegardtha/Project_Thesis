# CPR Depth Measurement System

Real-time depth calculation for CPR compressions using dual IMU sensors and full-cosine modeling.

## Overview

This project contains two distinct testing phases:

1. **IMU Calibration Testing** (`Kalman_testing.ipynb`): Initial experiments testing IMU sensors with a rotatinator device for sensor validation and calibration.

2. **CPR Depth Calculation** (`live_plotting2.py`, `cpr_depth_from_angles.py`): Real-time system that measures CPR compression depth by analyzing accelerometer roll angles from two IMU sensors positioned along a flexible measurement device. The solver uses a full-cosine displacement model to compute depth, position, and deepest compression point in real-time.

## Features

- **Real-time visualization**: Live animated plot of compression depth profile
- **Dual IMU tracking**: Processes accelerometer data from two synchronized sensors
- **Full-cosine solver**: Accurate depth calculation based on geometric constraints
- **Demo mode**: Test the system without hardware using synthetic data
- **Flexible configuration**: Adjustable sensor separation and measurement period

## Requirements

```bash
cd Kalman_testing
pip install -r requirements.txt
```

## Usage

```bash
python live_plotting2.py --port /dev/cu.usbmodem1201 --baud 115200
```

### Configuration Options
- `--port`: Serial port for Arduino connection
- `--baud`: Baud rate (default: 115200)
- `--L`: Cosine period in mm (default: 240.0)
- `--s`: IMU separation distance in mm (default: 103.0)
- `--swap`: Reverse IMU order if needed

## Hardware Setup

Expected serial format from Arduino:
```
ROLL, <angle1>, <angle2>
```

Where `angle1` and `angle2` are accelerometer roll angles in degrees from IMU1 and IMU2.

## Project Structure

- `live_plotting2.py` - Main application with real-time GUI
- `cpr_depth_from_angles.py` - Depth calculation solver
- `Kalman_testing.ipynb` - Analysis and testing notebook of the IMU sensors

## Output

The live plot displays:
Computed depth profile over measurement length with IMU positions and deepest point

