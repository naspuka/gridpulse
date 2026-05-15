#!/usr/bin/env bash
# Post-deploy host setup. Idempotent — safe to re-run.
#
# Run from your laptop after `terraform apply`:
#   bash terraform/post-deploy.sh <server-ip>
# or:
#   make post-deploy IP=<server-ip>
#
# Installs Docker, ufw, fail2ban, unattended-upgrades; prepares /opt/gridpulse
# for CI rsync; configures the unattended-upgrades reboot policy.

set -euo pipefail

IP="${1:?usage: $0 <server-ip>}"
SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 ubuntu@${IP}"

echo "[post-deploy] target: ubuntu@${IP}"
echo "[post-deploy] running host setup over SSH…"

# Run remotely with all-in-one heredoc; -e ensures we stop on any error.
$SSH 'bash -se' <<'REMOTE'
set -euo pipefail

echo "==> Docker repo + engine"
sudo install -m 0755 -d /etc/apt/keyrings
if [ ! -s /etc/apt/keyrings/docker.asc ]; then
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
fi
ARCH=$(dpkg --print-architecture)
CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
    ufw fail2ban unattended-upgrades rsync

sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu

echo "==> ufw (host firewall)"
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH        # idempotent
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status numbered

echo "==> fail2ban"
sudo tee /etc/fail2ban/jail.d/sshd.local >/dev/null <<'EOF'
[sshd]
enabled  = true
port     = ssh
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
sudo systemctl enable --now fail2ban
sudo systemctl restart fail2ban

echo "==> unattended-upgrades reboot policy"
sudo tee /etc/apt/apt.conf.d/52unattended-upgrades-reboot >/dev/null <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
EOF
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> /opt/gridpulse (CI rsync target)"
sudo install -d -o ubuntu -g ubuntu -m 0755 /opt/gridpulse

echo "==> done. quick summary:"
docker --version
docker compose version
sudo ufw status | head -3
sudo systemctl is-active docker fail2ban
REMOTE

echo "[post-deploy] complete."
