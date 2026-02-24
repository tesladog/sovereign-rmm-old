"""
SOVEREIGN RMM — Windows Agent
Self-contained Python agent for Windows devices.

How it works:
  1. Generates a unique device ID on first run (stored in AppData)
  2. Checks in with the server to get its policy (check-in intervals)
  3. Opens a WebSocket to the server for instant push commands
  4. Heartbeats on the interval defined by its policy + current battery level
  5. Executes tasks received from the server (PowerShell, CMD, Python)
  6. Reports results back through the WebSocket

Deployment:
  - Embed SERVER_IP and AGENT_TOKEN at build time (set them below or via env)
  - Package with PyInstaller + Wix/NSIS to create a zero-setup MSI
  - Runs as a Windows Service via pywin32

To build MSI:
  pip install pyinstaller pywin32
  pyinstaller --onefile --noconsole windows_agent.py
  # Then use WiX or Inno Setup to wrap the .exe into an MSI
"""

import asyncio
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import uuid
import winreg
from datetime import datetime
from pathlib import Path

import psutil
import websockets
import requests

# ============================================================
# CONFIGURATION — Set these at build time for your deployment
# ============================================================
SERVER_IP   = os.getenv("RMM_SERVER_IP", "192.168.1.100")
SERVER_PORT = os.getenv("RMM_SERVER_PORT", "8000")
AGENT_TOKEN = os.getenv("RMM_AGENT_TOKEN", "CHANGE_THIS_AGENT_TOKEN")

API_BASE  = f"http://{SERVER_IP}:{SERVER_PORT}/api"
WS_BASE   = f"ws://{SERVER_IP}:{SERVER_PORT}"
AGENT_VER = "1.0.0"

# ============================================================
# PERSISTENT DEVICE ID
# Stored in HKCU\Software\SovereignRMM\DeviceID
# Survives reboots and updates, but not full reinstalls.
# ============================================================
REG_KEY  = r"Software\SovereignRMM"
REG_NAME = "DeviceID"

def get_or_create_device_id() -> str:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY)
        device_id, _ = winreg.QueryValueEx(key, REG_NAME)
        winreg.CloseKey(key)
        return device_id
    except FileNotFoundError:
        device_id = str(uuid.uuid4())
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY)
        winreg.SetValueEx(key, REG_NAME, 0, winreg.REG_SZ, device_id)
        winreg.CloseKey(key)
        return device_id

# ============================================================
# LOGGING
# Logs to AppData\Local\SovereignRMM\agent.log
# ============================================================
log_dir = Path(os.getenv("LOCALAPPDATA", ".")) / "SovereignRMM"
log_dir.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "agent.log"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("SovereignAgent")

# ============================================================
# SYSTEM INFO COLLECTION
# ============================================================
def get_battery():
    """Returns (level_percent, is_charging) or (None, False) if no battery."""
    try:
        b = psutil.sensors_battery()
        if b is None:
            return None, False
        return round(b.percent, 1), b.power_plugged
    except Exception:
        return None, False


def get_system_info() -> dict:
    """Collect current system metrics for heartbeat."""
    battery_level, charging = get_battery()
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
    except Exception:
        cpu = ram = disk = None

    return {
        "hostname": socket.gethostname(),
        "ip_address": get_local_ip(),
        "os_info": f"{platform.system()} {platform.release()} {platform.version()}",
        "battery_level": battery_level,
        "battery_charging": charging,
        "cpu_percent": cpu,
        "ram_percent": ram,
        "disk_percent": disk,
    }


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


# ============================================================
# POLICY — How often to check in based on battery
# ============================================================
# Defaults — will be overridden by server policy on first check-in
policy = {
    "checkin_plugged_seconds": 30,
    "checkin_battery_100_80_seconds": 60,
    "checkin_battery_79_50_seconds": 180,
    "checkin_battery_49_20_seconds": 300,
    "checkin_battery_19_10_seconds": 600,
    "checkin_battery_9_0_seconds": 900,
}

def get_checkin_interval() -> int:
    """Calculate the correct check-in interval based on current battery state."""
    level, charging = get_battery()
    if charging or level is None:
        return policy["checkin_plugged_seconds"]
    if level >= 80: return policy["checkin_battery_100_80_seconds"]
    if level >= 50: return policy["checkin_battery_79_50_seconds"]
    if level >= 20: return policy["checkin_battery_49_20_seconds"]
    if level >= 10: return policy["checkin_battery_19_10_seconds"]
    return policy["checkin_battery_9_0_seconds"]


# ============================================================
# TASK EXECUTION
# Runs scripts in a subprocess and returns stdout/stderr/exit_code
# ============================================================
def execute_task(task_data: dict) -> dict:
    task_id    = task_data.get("task_id", "unknown")
    script_type = task_data.get("script_type", "powershell")
    script_body = task_data.get("script_body", "")

    log.info(f"Executing task {task_id} ({script_type})")
    started_at = datetime.utcnow().isoformat()

    try:
        if script_type == "powershell":
            cmd = ["powershell", "-NonInteractive", "-NoProfile", "-Command", script_body]
        elif script_type == "cmd":
            cmd = ["cmd", "/c", script_body]
        elif script_type == "python":
            cmd = [sys.executable, "-c", script_body]
        elif script_type == "bash":
            # WSL if available, otherwise best-effort
            cmd = ["wsl", "bash", "-c", script_body]
        else:
            cmd = ["powershell", "-Command", script_body]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
        return {
            "task_id": task_id,
            "exit_code": result.returncode,
            "stdout": result.stdout[:65535],   # Cap at 64KB
            "stderr": result.stderr[:16383],
            "started_at": started_at,
        }

    except subprocess.TimeoutExpired:
        return {"task_id": task_id, "exit_code": -1, "stdout": "", "stderr": "Task timed out after 5 minutes", "started_at": started_at}
    except Exception as e:
        return {"task_id": task_id, "exit_code": -1, "stdout": "", "stderr": str(e), "started_at": started_at}


# ============================================================
# SERVER CHECK-IN — First contact, get policy, get WS URL
# ============================================================
def do_checkin(device_id: str) -> dict | None:
    info = get_system_info()
    payload = {
        "device_id": device_id,
        "agent_version": AGENT_VER,
        "platform": "windows",
        **info,
    }
    try:
        r = requests.post(
            f"{API_BASE}/agent/checkin",
            json=payload,
            headers={"X-Agent-Token": AGENT_TOKEN},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Check-in failed: {e}")
        return None


# ============================================================
# WEBSOCKET AGENT LOOP
# Maintains a persistent connection to the server.
# Sends heartbeats on the policy interval.
# Receives and executes tasks pushed from the dashboard.
# ============================================================
async def agent_loop(device_id: str):
    global policy
    ws_url = f"{WS_BASE}/ws/agent/{device_id}?token={AGENT_TOKEN}"

    while True:
        try:
            log.info(f"Connecting to server WebSocket: {ws_url}")
            async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
                log.info("WebSocket connected — agent is live")

                async def heartbeat_loop():
                    """Send periodic heartbeats on the policy interval."""
                    while True:
                        interval = get_checkin_interval()
                        data = get_system_info()
                        await ws.send(json.dumps({"type": "heartbeat", "data": data}))
                        log.debug(f"Heartbeat sent (next in {interval}s)")
                        await asyncio.sleep(interval)

                async def receive_loop():
                    """Listen for push commands from the server."""
                    async for raw in ws:
                        try:
                            message = json.loads(raw)
                            msg_type = message.get("type")

                            if msg_type == "run_task":
                                task_data = message.get("data", {})
                                log.info(f"Received task: {task_data.get('name','?')}")

                                # Run in thread pool so we don't block heartbeats
                                loop = asyncio.get_event_loop()
                                result = await loop.run_in_executor(None, execute_task, task_data)
                                await ws.send(json.dumps({"type": "task_result", "data": result}))

                            elif msg_type == "update_policy":
                                new_policy = message.get("data", {})
                                policy.update(new_policy)
                                log.info("Policy updated from server")

                        except Exception as e:
                            log.error(f"Error handling message: {e}")

                # Run both loops concurrently
                await asyncio.gather(heartbeat_loop(), receive_loop())

        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            log.warning(f"WebSocket disconnected: {e} — retrying in 30s")
            await asyncio.sleep(30)
        except Exception as e:
            log.error(f"Unexpected error: {e} — retrying in 60s")
            await asyncio.sleep(60)


# ============================================================
# MAIN ENTRY POINT
# ============================================================
async def main():
    device_id = get_or_create_device_id()
    log.info(f"Sovereign RMM Agent starting — Device ID: {device_id}")

    # Initial check-in to get policy and confirm registration
    while True:
        result = do_checkin(device_id)
        if result:
            if "policy" in result:
                policy.update(result["policy"])
                log.info(f"Policy loaded from server: plugged={policy['checkin_plugged_seconds']}s")
            break
        log.warning("Could not reach server — retrying in 30s")
        await asyncio.sleep(30)

    # Enter the main WebSocket loop
    await agent_loop(device_id)


if __name__ == "__main__":
    # Install required packages if missing
    try:
        import psutil, websockets, requests
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil", "websockets", "requests"])
        import psutil, websockets, requests

    asyncio.run(main())
