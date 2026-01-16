# Master's Project Thesis Code

This repository contains code developed for a project thesis focused on CPR compression measurement systems and triboelectric nanogenerator (TENG) experiments.

## Project Components

### 1. **Kalman Testing** (`Kalman_testing/`)
Real-time CPR depth measurement system using dual IMU sensors.
- Calculates compression depth from accelerometer roll angles
- Full-cosine displacement model for accurate depth calculation
- Live visualization and demo mode available

**Quick start:**
```bash
cd Kalman_testing
pip install -r requirements.txt
python live_plotting2.py --port /dev/cu.usbmodem1201
```

### 2. **Prusa Web Controller** (`prusa_web/`)
Web-based controller for Prusa 3D printers with integrated force measurement (Proof of Concept).
- Real-time force monitoring using HX711 load cells
- Force-controlled Z-axis positioning
- Raspberry Pi deployment support

**Quick start:**
```bash
cd prusa_web
pip install -r requirements.txt
python app.py
```

### 3. **TENG Data Acquisition** (`TENG/`)
Automated data acquisition system for Triboelectric Nanogenerator experiments.
- Trigger-based voltage signal capture via Digilent oscilloscopes
- Configurable sampling rates and trigger levels
- Includes noise analysis tools

**Quick start:**
```bash
cd TENG
pip install -r requirements.txt
python run_experiment.py
```

## Requirements

Each subfolder contains its own `requirements.txt` file. Main dependencies include:

## Hardware

- IMU sensors (for CPR depth measurement)
- Prusa 3D printer (for mechanical CPR testing)
- Arduino with HX711 load cell module
- Digilent Analog Discovery oscilloscope

## Documentation

Detailed documentation for each component can be found in the respective subdirectory README files:
- [Kalman_testing/README.md](Kalman_testing/README.md)
- [prusa_web/README.md](prusa_web/README.md)
- [TENG/README.md](TENG/README.md)
