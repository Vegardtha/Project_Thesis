#!/bin/bash
# Deploy script - Overføre til Raspberry Pi

echo "🚀 Prusa CPR - Deploy to Raspberry Pi"
echo "======================================"
echo ""

# Set Pi IP-adresse automatically
PI_IP="192.168.50.42"

# Set brukernavn (standard er 'pi')
PI_USER="pi"

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
echo "4. Checking Python environment..."
if ssh -i $SSH_KEY $PI_USER@$PI_IP "[ -d ~/prusa-cpr/venv ]"; then
    echo "✅ Virtual environment already exists, skipping setup"
    echo "   (To reinstall: ssh $PI_USER@$PI_IP 'rm -rf ~/prusa-cpr/venv')"
else
    echo "Creating new virtual environment..."
    ssh -i $SSH_KEY $PI_USER@$PI_IP "cd ~/prusa-cpr && python3 -m venv venv"
    echo ""
    echo "5. Installing dependencies..."
    ssh -i $SSH_KEY $PI_USER@$PI_IP "cd ~/prusa-cpr && source venv/bin/activate && pip install -r requirements.txt"
fi

echo ""
echo "6. Setting up start script..."
ssh -i $SSH_KEY $PI_USER@$PI_IP "chmod +x ~/prusa-cpr/start.sh"

echo ""
echo "7. Stopping any running server..."
ssh -i $SSH_KEY $PI_USER@$PI_IP "pkill -f 'python3 app.py' 2>/dev/null || true"

echo ""
echo "======================================"
echo "✅ Deployment complete!"
echo ""
echo "🚀 Starting server on Raspberry Pi..."
echo "🌐 Opening browser at http://$PI_IP:5001"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Open browser in background
sleep 2 && open "http://$PI_IP:5000" &

# Start server in foreground
ssh -i $SSH_KEY -t $PI_USER@$PI_IP "cd ~/prusa-cpr && ./start.sh"
