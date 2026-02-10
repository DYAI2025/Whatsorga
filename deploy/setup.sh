#!/usr/bin/env bash
set -euo pipefail

# Beziehungs-Radar: Oracle Cloud ARM VM Bootstrap
# Run as: bash setup.sh

echo "=== Beziehungs-Radar Server Setup ==="

# 1. System updates
echo "[1/6] Updating system..."
sudo apt-get update -qq && sudo apt-get upgrade -y -qq

# 2. Install Docker
if ! command -v docker &>/dev/null; then
    echo "[2/6] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "    Docker installed. You may need to re-login for group changes."
else
    echo "[2/6] Docker already installed."
fi

# 3. Install Docker Compose plugin
if ! docker compose version &>/dev/null; then
    echo "[3/6] Installing Docker Compose plugin..."
    sudo apt-get install -y -qq docker-compose-plugin
else
    echo "[3/6] Docker Compose already installed."
fi

# 4. Create .env from template if not exists
if [ ! -f .env ]; then
    echo "[4/6] Creating .env from template..."
    cp .env.template .env
    echo "    IMPORTANT: Edit .env with your actual credentials before starting!"
    echo "    nano .env"
else
    echo "[4/6] .env already exists, skipping."
fi

# 5. Open firewall ports
echo "[5/6] Configuring firewall..."
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || true
# Persist iptables rules
if command -v netfilter-persistent &>/dev/null; then
    sudo netfilter-persistent save 2>/dev/null || true
fi

# 6. Pull images and start
echo "[6/6] Pulling Docker images..."
docker compose pull

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your credentials:  nano .env"
echo "  2. Start the stack:                  docker compose up -d"
echo "  3. Pull Ollama models:               docker compose exec ollama ollama pull llama3.1:8b"
echo "  4. Verify health:                    curl https://\$RADAR_DOMAIN/health"
echo ""
echo "  Monitor logs:  docker compose logs -f radar-api"
