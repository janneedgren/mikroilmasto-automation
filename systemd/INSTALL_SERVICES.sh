#!/bin/bash
# Install systemd services for automatic startup

set -e

echo "🚀 Installing CFD MikroilmastoCFD services..."
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root (use sudo)"
    exit 1
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 1. Copy service files
echo "📋 Copying service files to /etc/systemd/system/..."
cp "$SCRIPT_DIR/cfd-results-server.service" /etc/systemd/system/
cp "$SCRIPT_DIR/cloudflared.service" /etc/systemd/system/

# 2. Set correct permissions
chmod 644 /etc/systemd/system/cfd-results-server.service
chmod 644 /etc/systemd/system/cloudflared.service

# 3. Reload systemd
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload

# 4. Enable services (start on boot)
echo "✅ Enabling services for automatic startup..."
systemctl enable cfd-results-server.service
systemctl enable cloudflared.service

# 5. Start services now
echo "▶️  Starting services..."
systemctl start cfd-results-server.service
systemctl start cloudflared.service

echo ""
echo "✅ Installation complete!"
echo ""
echo "Services installed:"
echo "  - cfd-results-server.service (HTTP server on port 8080)"
echo "  - cloudflared.service (Cloudflare Tunnel)"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status cfd-results-server"
echo "  sudo systemctl status cloudflared"
echo "  sudo systemctl restart cfd-results-server"
echo "  sudo systemctl restart cloudflared"
echo "  sudo journalctl -u cfd-results-server -f"
echo "  sudo journalctl -u cloudflared -f"
echo ""
echo "Services will now start automatically on boot! 🎉"
