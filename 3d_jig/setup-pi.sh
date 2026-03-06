#!/bin/bash
# Run this on the Raspberry Pi to set up auto-start and USB networking
set -e

APP_DIR=~/prusa-cpr
SERVICE_NAME=prusa-cpr

echo "======================================"
echo "  TrollPi Setup Script"
echo "======================================"
echo ""

# ── 1. Python dependencies ────────────────────────────────────────────────────
echo "1. Installing Python dependencies..."
if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
echo "   ✅ Dependencies installed"

# ── 2. Systemd service ────────────────────────────────────────────────────────
echo ""
echo "2. Setting up systemd service (auto-start on boot)..."

sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=Prusa CPR Web Controller
After=network.target

[Service]
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/app.py
WorkingDirectory=${APP_DIR}
Restart=always
RestartSec=5
User=$(whoami)
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}
echo "   ✅ Service enabled and started"

# ── 3. USB gadget (ethernet over USB) ─────────────────────────────────────────
echo ""
echo "3. Configuring USB ethernet gadget..."

BOOT_CONFIG=/boot/firmware/config.txt   # Pi 4/5 path
[ -f /boot/config.txt ] && BOOT_CONFIG=/boot/config.txt   # Pi 3 path

if ! grep -q "dtoverlay=dwc2" "$BOOT_CONFIG"; then
    echo "dtoverlay=dwc2" | sudo tee -a "$BOOT_CONFIG" > /dev/null
    echo "   Added dtoverlay=dwc2 to $BOOT_CONFIG"
fi

if ! grep -q "^dwc2" /etc/modules; then
    echo "dwc2" | sudo tee -a /etc/modules > /dev/null
fi
if ! grep -q "^g_ether" /etc/modules; then
    echo "g_ether" | sudo tee -a /etc/modules > /dev/null
fi
echo "   ✅ USB gadget configured (takes effect after reboot)"

# ── 4. Avahi / mDNS (trollpi.local) ──────────────────────────────────────────
echo ""
echo "4. Ensuring mDNS (avahi) is running..."
sudo systemctl enable avahi-daemon 2>/dev/null || true
sudo systemctl start avahi-daemon 2>/dev/null || true
echo "   ✅ mDNS active – Pi is reachable as $(hostname).local"

echo ""
echo "======================================"
echo "  Setup complete!"
echo ""
echo "  App running now:  http://$(hostname -I | awk '{print $1}'):5001"
echo "  After reboot:     http://$(hostname).local:5001"
echo ""
echo "  ⚠️  Reboot required for USB gadget to activate."
echo "======================================"
