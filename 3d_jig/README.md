# Prusa CPR Controller

 ** Proof of Concept** - This is an experimentally setup project for controlling the prusa 3D printer via a web interface, it is not to be considered a finished project.

A web-based controller for Prusa 3D printers with integrated force-controlled CPR (Compression-Pressure-Research) functionality using HX711 load cell sensors.

## Features

- Web interface for Prusa printer control via serial connection
- Real-time force measurement with Arduino HX711 load cells
- Force-controlled Z-axis positioning
- Raspberry Pi deployment support

## Quick Start

**Requirements:**
- Prusa 3D printer with USB serial connection
- Arduino with HX711 load cell module
- Python 3.7+

**Installation:**
```bash
cd prusa_web
pip install -r requirements.txt
python3 app.py
```

Access the web interface at `http://localhost:5001`

## Raspberry Pi Deployment

Edit `PI_IP` in [deploy-to-pi.sh](deploy-to-pi.sh), then run:
```bash
./deploy-to-pi.sh
```

## Usage

1. Connect to printer via web interface (default baud: 115200)
2. Tare load cell before use
3. Send G-code commands or use force-controlled positioning
4. Monitor real-time force readings

## Project Structure

```
├── app.py              # Flask application
├── requirements.txt    # Dependencies
├── deploy-to-pi.sh    # Pi deployment script
└── templates/
    └── index.html     # Web UI
```

## Troubleshooting

- **Connection issues**: Check USB cables, serial ports, and baud rate
- **Load cell not responding**: Verify Arduino connection and HX711 wiring
- **Deployment fails**: Check SSH configuration and network connectivity

