"""
SOVEREIGN RMM — Android / LineageOS Agent
Pure Python agent designed for LineageOS devices with no Play Store.

DEPLOYMENT:
  This runs as a background Python script via Termux or a custom APK shell.
  For a proper sideloadable APK, wrap this with Buildozer (Kivy) or
  use SL4A (Scripting Layer for Android).

  Recommended deployment path:
    1. Install Termux APK (sideloaded from f-droid.org)
    2. pkg install python
    3. pip install psutil websockets requests
    4. Copy this file to /data/data/com.termux/files/home/
    5. Run: python android_agent.py &
    6. Add to Termux:Boot for auto-start on reboot

  For a true zero-setup APK, build with Buildozer:
    buildozer android debug deploy run

NOTES ON LINEAGEOS:
  - Battery info available via /sys/class/power_supply/battery/
  - No Google APIs needed
  - ADB shell can also run scripts if USB debugging enabled
  - Root not required for basic stats, but helps for some operations
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

try:
    import websockets
except ImportError:
    websockets = None

try:
    import requests
except ImportError:
    requests = None

# ============================================================
# CONFIGURATION
# ============================================================
SERVER_IP   = os.getenv("RMM_SERVER_IP", "192.168.1.100")
SERVER_PORT = os.getenv("RMM_SERVER_PORT", "8000")
AGENT_TOKEN = os.getenv("RMM_AGENT_TOKEN", "CHANGE_THIS_AGENT_TOKEN")

API_BASE = f"http://{SERVER_IP}:{SERVER_PORT}/api"
WS_BASE  = f"ws://{SERVER_IP}:{SERVER_PORT}"
AGENT_VER = "1.0.0"

# Device ID stored in app's home directory
ID_FILE = Path.home() / ".sovereign_rmm_id"

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path.home() / "sovereign_agent.log"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("SovereignAndroid")

# ============================================================
# PERSISTENT DEVICE ID
# ============================================================
def get_or_create_device_id() -> str:
    if ID_FILE.exists():
        return ID_FILE.read_text().strip()
    device_id = str(uuid.uuid4())
    ID_FILE.write_text(device_id)
    return device_id

# ============================================================
# ANDROID BATTERY — Read directly from sysfs (no Play Store needed)
# Works on LineageOS and most AOSP-based ROMs
# ============================================================
BATTERY_PATH = Path("/sys/class/power_supply/battery")

def get_battery():
    """Read battery level and charging state from sysfs."""
    try:
        level = int((BATTERY_PATH / "capacity").read_text().strip())
        status = (BATTERY_PATH / "status").read_text().strip().lower()
        charging = status in ("charging", "full")
        return float(level), charging
    except Exception:
        # Fallback to psutil if sysfs path doesn't exist
        try:
            if psutil:
                b = psutil.sensors_battery()
                if b:
                    return round(b.percent, 1), b.power_plugged
        except Exception:
            pass
        return None, False


def get_android_info() -> dict:
    """Get device model, Android version, etc. via Android properties."""
    props = {}
    try:
        result = subprocess.run(["getprop"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            if any(k in line for k in ["ro.product.model", "ro.build.version.release", "ro.product.manufacturer"]):
                key, _, val = line.partition("]: [")
                key = key.strip("[")
                val = val.strip("]")
                props[key] = val
    except Exception:
        pass

    model = props.get("ro.product.model", "Android Device")
    android_ver = props.get("ro.build.version.release", "Unknown")
    manufacturer = props.get("ro.product.manufacturer", "")

    return {
        "model": f"{manufacturer} {model}".strip(),
        "android_version": f"Android {android_ver} (LineageOS)",
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


def get_system_info() -> dict:
    battery_level, charging = get_battery()
    android = get_android_info()

    cpu = None
    ram = None
    disk = None
    try:
        if psutil:
            cpu  = psutil.cpu_percent(interval=0.5)
            ram  = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
    except Exception:
        pass

    return {
        "hostname": socket.gethostname() or android["model"],
        "ip_address": get_local_ip(),
        "os_info": android["android_version"],
        "battery_level": battery_level,
        "battery_charging": charging,
        "cpu_percent": cpu,
        "ram_percent": ram,
        "disk_percent": disk,
    }


# ============================================================
# POLICY
# ============================================================
policy = {
    "checkin_plugged_seconds": 30,
    "checkin_battery_100_80_seconds": 60,
    "checkin_battery_79_50_seconds": 180,
    "checkin_battery_49_20_seconds": 300,
    "checkin_battery_19_10_seconds": 600,
    "checkin_battery_9_0_seconds": 900,
}

def get_checkin_interval() -> int:
    level, charging = get_battery()
    if charging or level is None:
        return policy["checkin_plugged_seconds"]
    if level >= 80: return policy["checkin_battery_100_80_seconds"]
    if level >= 50: return policy["checkin_battery_79_50_seconds"]
    if level >= 20: return policy["checkin_battery_49_20_seconds"]
    if level >= 10: return policy["checkin_battery_19_10_seconds"]
    return policy["checkin_battery_9_0_seconds"]


# ============================================================
# TASK EXECUTION — Android / Shell commands
# ============================================================
def execute_task(task_data: dict) -> dict:
    task_id     = task_data.get("task_id", "unknown")
    script_type = task_data.get("script_type", "bash")
    script_body = task_data.get("script_body", "")

    log.info(f"Executing task {task_id} ({script_type})")
    started_at = datetime.utcnow().isoformat()

    try:
        if script_type in ("bash", "sh"):
            cmd = ["sh", "-c", script_body]
        elif script_type == "python":
            cmd = [sys.executable, "-c", script_body]
        elif script_type == "adb":
            # ADB shell commands (if USB debugging enabled)
            cmd = ["adb", "shell", script_body]
        else:
            cmd = ["sh", "-c", script_body]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "task_id": task_id,
            "exit_code": result.returncode,
            "stdout": result.stdout[:65535],
            "stderr": result.stderr[:16383],
            "started_at": started_at,
        }
    except subprocess.TimeoutExpired:
        return {"task_id": task_id, "exit_code": -1, "stdout": "", "stderr": "Timed out", "started_at": started_at}
    except Exception as e:
        return {"task_id": task_id, "exit_code": -1, "stdout": "", "stderr": str(e), "started_at": started_at}


# ============================================================
# APK PUSH — Install a sideloaded APK
# ============================================================
def install_apk(apk_url: str, apk_name: str = "install.apk") -> dict:
    """Download and install an APK. Requires 'Unknown Sources' enabled."""
    import urllib.request
    tmp = Path("/tmp") / apk_name
    try:
        log.info(f"Downloading APK from {apk_url}")
        urllib.request.urlretrieve(apk_url, tmp)
        result = subprocess.run(
            ["pm", "install", "-r", str(tmp)],
            capture_output=True, text=True, timeout=120
        )
        return {"success": result.returncode == 0, "output": result.stdout + result.stderr}
    except Exception as e:
        return {"success": False, "output": str(e)}
    finally:
        tmp.unlink(missing_ok=True)


# ============================================================
# CHECK-IN
# ============================================================
def do_checkin(device_id: str) -> dict | None:
    android = get_android_info()
    info = get_system_info()
    payload = {
        "device_id": device_id,
        "agent_version": AGENT_VER,
        "platform": "android",
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
# WEBSOCKET LOOP
# ============================================================
async def agent_loop(device_id: str):
    global policy
    ws_url = f"{WS_BASE}/ws/agent/{device_id}?token={AGENT_TOKEN}"

    while True:
        try:
            log.info(f"Connecting WebSocket: {ws_url}")
            async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
                log.info("Connected to Sovereign RMM server")

                async def heartbeat_loop():
                    while True:
                        interval = get_checkin_interval()
                        data = get_system_info()
                        await ws.send(json.dumps({"type": "heartbeat", "data": data}))
                        log.debug(f"Heartbeat sent (next in {interval}s)")
                        await asyncio.sleep(interval)

                async def receive_loop():
                    async for raw in ws:
                        try:
                            message = json.loads(raw)
                            msg_type = message.get("type")

                            if msg_type == "run_task":
                                task_data = message.get("data", {})
                                log.info(f"Task received: {task_data.get('name','?')}")
                                loop = asyncio.get_event_loop()
                                result = await loop.run_in_executor(None, execute_task, task_data)
                                await ws.send(json.dumps({"type": "task_result", "data": result}))

                            elif msg_type == "install_apk":
                                data = message.get("data", {})
                                log.info(f"APK install requested: {data.get('url')}")
                                result = await asyncio.get_event_loop().run_in_executor(
                                    None, lambda: install_apk(data["url"], data.get("name","install.apk"))
                                )
                                await ws.send(json.dumps({"type": "log", "data": {
                                    "level": "info" if result["success"] else "error",
                                    "message": f"APK install: {result['output']}"
                                }}))

                            elif msg_type == "update_policy":
                                policy.update(message.get("data", {}))
                                log.info("Policy updated")

                        except Exception as e:
                            log.error(f"Message error: {e}")

                await asyncio.gather(heartbeat_loop(), receive_loop())

        except Exception as e:
            log.warning(f"Connection lost: {e} — retrying in 30s")
            await asyncio.sleep(30)


# ============================================================
# MAIN
# ============================================================
async def main():
    # Auto-install dependencies if missing
    missing = []
    if not psutil: missing.append("psutil")
    if not websockets: missing.append("websockets")
    if not requests: missing.append("requests")
    if missing:
        log.info(f"Installing missing packages: {missing}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        log.info("Packages installed — restarting")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    device_id = get_or_create_device_id()
    log.info(f"Sovereign Android Agent — Device ID: {device_id}")

    while True:
        result = do_checkin(device_id)
        if result:
            if "policy" in result:
                policy.update(result["policy"])
            break
        log.warning("Server unreachable — retrying in 30s")
        await asyncio.sleep(30)

    await agent_loop(device_id)


if __name__ == "__main__":
    asyncio.run(main())
