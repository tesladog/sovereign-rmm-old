# Sovereign RMM

Self-hosted Remote Management & Monitoring platform. No cloud. No domain. Local IP only.

Built for Dockge — deploy the entire stack with two files: `compose.yaml` + `.env`.

## Features

- 🖥️ **Windows, Android (LineageOS), Linux** device management
- ⚡ **Instant task push** via WebSocket — scripts run immediately on demand
- 🔋 **Adaptive check-in** — agents check in less frequently on low battery
- 📊 **Live dashboard** — CPU, RAM, disk, battery per device
- 🖱️ **Browser remote desktop** — RDP/VNC/SSH via Apache Guacamole
- 🔐 **Self-hosted VPN** — Netbird issues WireGuard keys locally
- 📋 **Script scheduler** — PowerShell, Bash, Python, one-time or recurring
- 📁 **File transfer** — push files to devices
- 🌑 **Dark mode only** — no light mode, ever

## Quick Deploy

### 1. Create the GitHub repo (already done if you're reading this)

### 2. Set up Dockge on your Ubuntu server

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
mkdir -p /opt/stacks /opt/dockge
curl "https://dockge.kuma.pet/compose.yaml" --output /opt/dockge/compose.yaml
cd /opt/dockge && docker compose up -d
# Open http://YOUR_SERVER_IP:5001
```

### 3. Deploy in Dockge

1. Open Dockge → New Stack → name it `sovereign-rmm`
2. Paste `compose.yaml` into the compose editor
3. Paste `.env` into the env editor
4. **Edit `.env`**: set `SERVER_IP` to your server's local IP, change all `CHANGE_THIS` values
5. Hit **Start** — Docker builds everything from this repo automatically

### 4. Access

| Service | URL |
|---------|-----|
| Dashboard | `http://YOUR_IP:8080` |
| Remote Desktop | `http://YOUR_IP:8090/guacamole` |
| VPN Management | `http://YOUR_IP:8081` |

---

## Windows Agent Deployment

```powershell
# Option A — Run directly (dev/testing)
$env:RMM_SERVER_IP    = "192.168.1.100"
$env:RMM_AGENT_TOKEN  = "your-agent-token"
pip install psutil websockets requests
python agent/windows_agent.py

# Option B — Build .exe for deployment
pip install pyinstaller
pyinstaller --onefile --noconsole agent/windows_agent.py
# Wrap dist/windows_agent.exe in Inno Setup for zero-setup MSI
```

## Android Agent (LineageOS — no Play Store)

```bash
# Install Termux from F-Droid: https://f-droid.org/packages/com.termux/
pkg install python
pip install psutil websockets requests
export RMM_SERVER_IP="192.168.1.100"
export RMM_AGENT_TOKEN="your-agent-token"
python agent/android_agent.py
```

---

## Stack Services

| Container | Purpose |
|-----------|---------|
| `postgres` | Database |
| `redis` | Task queue + WebSocket pub/sub |
| `backend` | FastAPI agent + dashboard API |
| `frontend` | Nginx serving the dashboard |
| `guacd` | Guacamole protocol daemon |
| `guacamole` | Browser remote desktop |
| `guacamole-init` | One-time DB schema init |
| `netbird-mgmt` | VPN key management |
| `netbird-signal` | VPN peer discovery |
| `netbird-relay` | VPN TURN relay |

---

## Security Checklist

- [ ] Change all `CHANGE_THIS` values in `.env`
- [ ] Generate `API_SECRET_KEY` and `AGENT_TOKEN` with `openssl rand -hex 32`
- [ ] Change Guacamole default password (`guacadmin/guacadmin`) after first login
- [ ] Never commit `.env` to GitHub (it's in `.gitignore`)
