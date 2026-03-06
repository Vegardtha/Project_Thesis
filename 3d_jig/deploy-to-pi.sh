#!/bin/bash
# Deploy script - Overføre til Raspberry Pi

echo "🚀 Prusa CPR - Deploy to Raspberry Pi"
echo "======================================"
echo ""

# Set Pi IP-adresse automatically
PI_IP="192.168.50.233"

# Set brukernavn (standard er 'pi')
PI_USER="trollpi"

# SSH key path
SSH_KEY="~/.ssh/pi_rsa"

echo ""
echo "Deploying to: $PI_USER@$PI_IP"
echo ""

# Test SSH-forbindelse
echo "1. Testing SSH connection..."
if ssh -i $SSH_KEY -o ConnectTimeout=5 $PI_USER@$PI_IP "echo 'SSH OK'" 2>/dev/null; then
    echo "✅ SSH connection successful"
else
    echo "❌ Cannot connect to $PI_USER@$PI_IP"
    echo "Please check:"
    echo "  - IP address is correct"
    echo "  - Raspberry Pi is powered on"
    echo "  - SSH is enabled on Pi"
    echo "  - Both devices are on same network"
    echo "  - SSH key is properly set up"
    exit 1
fi

echo ""
echo "2. Creating directory on Pi..."
ssh -i $SSH_KEY $PI_USER@$PI_IP "mkdir -p ~/prusa-cpr"

echo ""
echo "3. Transferring files..."
rsync -avz --progress \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'venv' \
    -e "ssh -i $SSH_KEY" \
    ./ $PI_USER@$PI_IP:~/prusa-cpr/

echo ""
echo "4. Running setup on Pi (dependencies, autostart, USB gadget)..."
ssh -i $SSH_KEY $PI_USER@$PI_IP "chmod +x ~/prusa-cpr/setup-pi.sh && ~/prusa-cpr/setup-pi.sh"

echo ""
echo "======================================"
echo "✅ Deployment complete!"
echo ""
echo "🌐 App is now running at: http://$PI_IP:5001"
echo "   Also reachable via:    http://trollpi.local:5001"
echo ""
echo "⚠️  If this was the first deploy, reboot the Pi for USB gadget to activate:"
echo "   ssh -i $SSH_KEY $PI_USER@$PI_IP 'sudo reboot'"
echo "======================================"
