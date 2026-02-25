"""
SOVEREIGN RMM v2 — Linux Agent (Ubuntu)
- Installs as systemd service
- All task trigger types with local JSON cache
- Smart IP selection, weekly retest
- Self-update via .deb
- Disk scan with du breakdown
"""

import asyncio, json, logging, os, platform, re, socket, subprocess, sys, uuid
from datetime import datetime, timedelta
from pathlib import Path

try: import psutil
except ImportError: subprocess.check_call([sys.executable,"-m","pip","install","psutil"]); import psutil
try: import websockets, requests
except ImportError: subprocess.check_call([sys.executable,"-m","pip","install","websockets","requests"]); import websockets, requests

# ── CONFIG ────────────────────────────────────────────────────
SERVER_IP_LOCAL = "RMM_LOCAL_IP"
SERVER_IP_VPN   = "RMM_VPN_IP"
SERVER_PORT     = "RMM_PORT"
AGENT_TOKEN     = "RMM_TOKEN"
AGENT_VERSION   = "2.0.0"

APP_DIR    = Path("/var/lib/sovereign-rmm")
TASKS_FILE = APP_DIR / "scheduled_tasks.json"
STATE_FILE = APP_DIR / "state.json"
LOG_FILE   = Path("/var/log/sovereign-rmm.log")
try: APP_DIR.mkdir(parents=True, exist_ok=True)
except: APP_DIR = Path.home() / ".sovereign-rmm"; APP_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(str(LOG_FILE),errors='ignore'), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("SovAgent")

# ── STATE ─────────────────────────────────────────────────────
def state_load():
    try: return json.loads(STATE_FILE.read_text())
    except: return {}
def state_save(d): STATE_FILE.write_text(json.dumps(d, indent=2))
def state_get(k, default=""): return state_load().get(k, default)
def state_set(k, v): s=state_load(); s[k]=v; state_save(s)
def get_device_id():
    d = state_get("device_id")
    if not d: d = str(uuid.uuid4()); state_set("device_id", d)
    return d

# ── IP SELECTION ──────────────────────────────────────────────
WEEK = 7*24*3600

def ping_ip(ip):
    try:
        s = socket.socket(); s.settimeout(3)
        ok = s.connect_ex((ip, int(SERVER_PORT))) == 0; s.close(); return ok
    except: return False

def should_retest():
    t = state_get("last_ip_test","")
    if not t: return True
    try: return (datetime.utcnow()-datetime.fromisoformat(t)).total_seconds() > WEEK
    except: return True

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80)); ip = s.getsockname()[0]; s.close(); return ip
    except: return "unknown"

def get_ssid():
    try:
        r = subprocess.run(["iwgetid","-r"],capture_output=True,text=True,timeout=5)
        return r.stdout.strip() if r.returncode==0 else "wired/unknown"
    except: return "unknown"

def select_server_ip(force=False):
    cached = state_get("active_ip","")
    if cached and not force and not should_retest(): return cached
    log.info("Testing server IPs...")
    if ping_ip(SERVER_IP_LOCAL): ip = SERVER_IP_LOCAL
    elif ping_ip(SERVER_IP_VPN): ip = SERVER_IP_VPN
    else: return cached or SERVER_IP_LOCAL
    s = state_load()
    s["active_ip"]=ip; s["last_ip_test"]=datetime.utcnow().isoformat(); state_save(s)
    log.info(f"Active IP: {ip}"); return ip

# ── TASK STORAGE ──────────────────────────────────────────────
def load_tasks():
    try: return json.loads(TASKS_FILE.read_text())
    except: return []
def save_tasks(t): TASKS_FILE.write_text(json.dumps(t, indent=2, default=str))
def add_or_update_task(task):
    tasks = [t for t in load_tasks() if t.get("task_id") != task.get("task_id")]
    tasks.append(task); save_tasks(tasks)
def remove_task(tid): save_tasks([t for t in load_tasks() if t.get("task_id") != tid])
def cancel_task_local(tid):
    tasks = load_tasks()
    for t in tasks:
        if t.get("task_id") == tid: t["cancelled"] = True
    save_tasks(tasks)

# ── POLICY ────────────────────────────────────────────────────
policy = {"checkin_plugged_seconds":30,"checkin_battery_100_80_seconds":60,
          "checkin_battery_79_50_seconds":180,"checkin_battery_49_20_seconds":300,
          "checkin_battery_19_10_seconds":600,"checkin_battery_9_0_seconds":900,
          "disk_scan_interval_hours":168}

def get_battery():
    try:
        cap = Path("/sys/class/power_supply/battery/capacity")
        sta = Path("/sys/class/power_supply/battery/status")
        if cap.exists():
            lvl = float(cap.read_text().strip())
            charging = sta.read_text().strip() in ("Charging","Full")
            return lvl, charging
    except: pass
    try:
        b = psutil.sensors_battery()
        return (round(b.percent,1), b.power_plugged) if b else (None, False)
    except: return (None, False)

def get_checkin_interval():
    lvl, charging = get_battery()
    if charging or lvl is None: return policy["checkin_plugged_seconds"]
    if lvl >= 80: return policy["checkin_battery_100_80_seconds"]
    if lvl >= 50: return policy["checkin_battery_79_50_seconds"]
    if lvl >= 20: return policy["checkin_battery_49_20_seconds"]
    if lvl >= 10: return policy["checkin_battery_19_10_seconds"]
    return policy["checkin_battery_9_0_seconds"]

def get_system_info():
    lvl, charging = get_battery()
    info = {"hostname": socket.gethostname(), "ip_address": get_local_ip(),
            "os_info": f"Ubuntu {platform.release()}", "battery_level": lvl,
            "battery_charging": charging, "agent_version": AGENT_VERSION}
    try:
        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        info["ram_percent"] = psutil.virtual_memory().percent
        info["disk_percent"] = psutil.disk_usage("/").percent
    except: pass
    return info

# ── DISK SCAN ─────────────────────────────────────────────────
async def do_disk_scan(ws, device_id):
    log.info("Running disk scan...")
    details = []
    try:
        for part in psutil.disk_partitions():
            try:
                u = psutil.disk_usage(part.mountpoint)
                details.append({"path":part.mountpoint,"size":f"{u.used/1e9:.1f}GB","pct":round(u.percent)})
            except: pass
        r = subprocess.run(["du","-sh","--max-depth=1","/"],capture_output=True,text=True,timeout=60)
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t",1)
            if len(parts)==2: details.append({"path":parts[1],"size":parts[0],"pct":0,"type":"dir"})
    except Exception as e: log.warning(f"Disk scan: {e}")
    if ws:
        try: await ws.send(json.dumps({"type":"disk_scan","data":{"details":details}}))
        except: pass
    return details

# ── TASK EXECUTION ────────────────────────────────────────────
async def execute_task(task_data, ws, device_id):
    task_id = task_data.get("task_id","?")
    script_type = task_data.get("script_type","bash")
    script_body = task_data.get("script_body","")
    started_at  = datetime.utcnow().isoformat()
    if script_type in ("bash","sh"): cmd = ["bash","-c",script_body]
    elif script_type == "python":    cmd = [sys.executable,"-c",script_body]
    else:                            cmd = ["bash","-c",script_body]
    stdout_buf, stderr_buf = [], []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        async def stream_out():
            while True:
                line = await proc.stdout.readline()
                if not line: break
                text = line.decode("utf-8","replace")
                stdout_buf.append(text)
                if ws:
                    try: await ws.send(json.dumps({"type":"task_output","task_id":task_id,"output":text,"progress":50}))
                    except: pass
        async def stream_err():
            while True:
                line = await proc.stderr.readline()
                if not line: break
                stderr_buf.append(line.decode("utf-8","replace"))
        await asyncio.gather(stream_out(), stream_err(), asyncio.wait_for(proc.wait(), timeout=300))
        exit_code = proc.returncode
    except asyncio.TimeoutError:
        proc.kill(); exit_code=-1; stderr_buf.append("Timed out")
    except Exception as e:
        exit_code=-1; stderr_buf.append(str(e))
    result = {"task_id":task_id,"exit_code":exit_code,
              "stdout":"".join(stdout_buf)[:65535],"stderr":"".join(stderr_buf)[:16383],
              "started_at":started_at}
    if ws:
        try:
            await ws.send(json.dumps({"type":"task_result","data":result}))
            await ws.send(json.dumps({"type":"task_output","task_id":task_id,"output":"","progress":100}))
        except: pass
    return result

# ── CRON HELPER ────────────────────────────────────────────────
def cron_next_run(expr):
    try:
        parts = expr.strip().split()
        if len(parts) < 5: return None
        minute, hour = int(parts[0]), int(parts[1])
        now = datetime.utcnow()
        candidate = now.replace(minute=minute, hour=hour, second=0, microsecond=0)
        if candidate <= now: candidate += timedelta(days=1)
        if parts[4] != "*":
            target_wd = int(parts[4])
            while candidate.weekday() != target_wd: candidate += timedelta(days=1)
        return candidate
    except: return None

def task_is_due(task):
    trigger = task.get("trigger_type","now")
    if trigger == "now": return True
    if trigger == "once":
        t = task.get("scheduled_at")
        return t and datetime.utcnow() >= datetime.fromisoformat(t)
    if trigger == "interval":
        last = task.get("last_run")
        if not last: return True
        return (datetime.utcnow()-datetime.fromisoformat(last)).total_seconds() >= task.get("interval_seconds",3600)
    if trigger == "cron":
        nxt = cron_next_run(task.get("cron_expression",""))
        if not nxt: return False
        last = task.get("last_run")
        return datetime.utcnow() >= nxt and (not last or datetime.fromisoformat(last) < nxt)
    return False

def check_task_still_active(task_id, server_ip):
    try:
        r = requests.get(f"http://{server_ip}:{SERVER_PORT}/api/dashboard/tasks/{task_id}",
                         headers={"X-Agent-Token":AGENT_TOKEN}, timeout=10)
        return not r.json().get("cancelled", False) if r.ok else True
    except: return True

# ── LOCAL TASK RUNNER ─────────────────────────────────────────
async def local_task_runner(ws_ref, device_id):
    while True:
        try:
            for task in [t for t in load_tasks() if not t.get("cancelled")]:
                if not task_is_due(task): continue
                tid = task.get("task_id","?")
                if task.get("trigger_type") in ("once","cron","interval"):
                    if not check_task_still_active(tid, state_get("active_ip",SERVER_IP_LOCAL)):
                        cancel_task_local(tid); continue
                await execute_task(task, ws_ref[0], device_id)
                if task.get("trigger_type") == "once":
                    remove_task(tid)
                else:
                    tasks2 = load_tasks()
                    for t in tasks2:
                        if t.get("task_id") == tid: t["last_run"] = datetime.utcnow().isoformat()
                    save_tasks(tasks2)
        except Exception as e: log.error(f"Runner: {e}")
        await asyncio.sleep(30)

# ── EVENT WATCHER ─────────────────────────────────────────────
async def event_task_watcher(ws_ref, device_id):
    last_ssid = get_ssid()
    while True:
        try:
            cur_ssid = get_ssid()
            changed  = cur_ssid != last_ssid
            if changed: last_ssid = cur_ssid; state_set("active_ip",""); log.info(f"Network changed: {cur_ssid}")
            for task in [t for t in load_tasks() if t.get("trigger_type")=="event" and not t.get("cancelled")]:
                if task.get("event_trigger") == "network_change" and changed:
                    await execute_task(task, ws_ref[0], device_id)
        except Exception as e: log.error(f"Event watcher: {e}")
        await asyncio.sleep(15)

async def weekly_ip_retest():
    while True:
        last = state_get("last_ip_test","")
        wait = WEEK
        if last:
            try: wait = max(WEEK-(datetime.utcnow()-datetime.fromisoformat(last)).total_seconds(), 3600)
            except: pass
        await asyncio.sleep(wait)
        log.info("Weekly IP retest..."); select_server_ip(force=True)

# ── WEBSOCKET LOOP ────────────────────────────────────────────
async def ws_loop(device_id, ws_ref):
    global policy
    while True:
        server_ip = select_server_ip()
        url = f"ws://{server_ip}:{SERVER_PORT}/ws/agent/{device_id}?token={AGENT_TOKEN}"
        try:
            async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                ws_ref[0] = ws; log.info("Connected!")
                async def heartbeat():
                    while True:
                        await ws.send(json.dumps({"type":"heartbeat","data":get_system_info()}))
                        await asyncio.sleep(get_checkin_interval())
                async def receive():
                    global policy
                    async for raw in ws:
                        try:
                            msg = json.loads(raw); t = msg.get("type")
                            if t == "run_task": asyncio.create_task(execute_task(msg.get("data",{}),ws,device_id))
                            elif t == "schedule_task": add_or_update_task(msg.get("data",{}))
                            elif t == "cancel_task": cancel_task_local(msg.get("task_id",""))
                            elif t == "update_policy": policy.update(msg.get("data",{}))
                            elif t == "disk_scan_request": asyncio.create_task(do_disk_scan(ws,device_id))
                        except Exception as e: log.error(f"Msg: {e}")
                await asyncio.gather(heartbeat(), receive())
        except Exception as e:
            ws_ref[0] = None; log.warning(f"Disconnected: {e} — retry 30s")
            state_set("active_ip",""); await asyncio.sleep(30)

async def main():
    device_id = get_device_id()
    log.info(f"Sovereign RMM Linux Agent v{AGENT_VERSION} — {device_id}")
    server_ip = select_server_ip()
    for _ in range(10):
        try:
            r = requests.post(f"http://{server_ip}:{SERVER_PORT}/api/agent/checkin",
                json={"device_id":device_id,"agent_version":AGENT_VERSION,"platform":"linux",**get_system_info()},
                headers={"X-Agent-Token":AGENT_TOKEN},timeout=15)
            resp = r.json()
            if "policy" in resp: policy.update(resp["policy"])
            for task in resp.get("scheduled_tasks",[]): add_or_update_task(task)
            log.info("Checked in."); break
        except: await asyncio.sleep(30); server_ip = select_server_ip()
    ws_ref = [None]
    await asyncio.gather(ws_loop(device_id,ws_ref), local_task_runner(ws_ref,device_id),
                         event_task_watcher(ws_ref,device_id), weekly_ip_retest())

if __name__ == "__main__":
    asyncio.run(main())

# ── HARDWARE SCAN (appended) ─────────────────────────────────

def get_mac_address():
    try:
        import uuid as _uuid
        mac = _uuid.UUID(int=_uuid.getnode()).hex[-12:]
        return ':'.join(mac[i:i+2] for i in range(0,12,2)).upper()
    except: return None

def collect_hardware_info():
    hw = {}
    def run(cmd): return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    try:
        cpuinfo = run(['cat','/proc/cpuinfo'])
        name_lines = [l for l in cpuinfo.splitlines() if 'model name' in l]
        name = name_lines[0].split(':',1)[-1].strip() if name_lines else 'Unknown'
        cores = len([l for l in cpuinfo.splitlines() if l.startswith('processor')])
        hw['cpu'] = {'name': name, 'cores': cores, 'threads': cores}
    except: pass
    try:
        meminfo = {l.split(':')[0]: l.split(':')[1].strip() for l in open('/proc/meminfo') if ':' in l}
        total_kb = int(meminfo.get('MemTotal','0 kB').split()[0])
        hw['ram'] = {'total_gb': round(total_kb/1048576, 1), 'slots': []}
        dmi = run(['dmidecode','-t','memory'])
        for block in dmi.split('\n\n'):
            if 'Size:' in block and 'MB' in block:
                size_line = next((l for l in block.splitlines() if 'Size:' in l), '')
                speed_line = next((l for l in block.splitlines() if 'Speed:' in l and 'MT' in l), '')
                type_line  = next((l for l in block.splitlines() if 'Type:' in l and 'DDR' in l), '')
                size_mb = int(size_line.split()[-2]) if 'MB' in size_line else 0
                hw['ram']['slots'].append({'size': round(size_mb/1024), 'speed': speed_line.split()[-2] if speed_line else '?', 'type': type_line.split()[-1] if type_line else 'DDR'})
    except: pass
    try:
        lspci = run(['lspci'])
        gpus = [l.split(': ',1)[-1] for l in lspci.splitlines() if 'VGA' in l or '3D' in l]
        if gpus: hw['gpu'] = {'name': ' / '.join(gpus)}
    except: pass
    try:
        disks = []
        for disk in Path('/sys/block').iterdir():
            if disk.name.startswith(('sd','nvme','hd')):
                size_file = disk / 'size'
                model_file = disk / 'device' / 'model'
                serial_file = disk / 'device' / 'serial'
                size_sectors = int(size_file.read_text().strip()) if size_file.exists() else 0
                disks.append({
                    'name': disk.name,
                    'model': model_file.read_text().strip() if model_file.exists() else disk.name,
                    'serial': serial_file.read_text().strip() if serial_file.exists() else '',
                    'size': f"{round(size_sectors*512/1e9)}GB"
                })
        hw['disks'] = disks
    except: pass
    try:
        dmi_board = run(['dmidecode','-t','baseboard'])
        mfr  = next((l.split(':',1)[-1].strip() for l in dmi_board.splitlines() if 'Manufacturer:' in l), '')
        prod = next((l.split(':',1)[-1].strip() for l in dmi_board.splitlines() if 'Product Name:' in l), '')
        hw['motherboard'] = {'manufacturer': mfr, 'model': prod}
    except: pass
    hw['mac'] = get_mac_address()
    return hw

async def hw_scan_loop(server_ip, device_id):
    await asyncio.sleep(60)
    while True:
        try:
            log.info("Hardware scan...")
            hw = collect_hardware_info()
            requests.post(f"http://{server_ip}:{SERVER_PORT}/api/hardware/{device_id}/report",
                json=hw, headers={"X-Agent-Token":AGENT_TOKEN}, timeout=30)
        except Exception as e: log.warning(f"HW scan: {e}")
        await asyncio.sleep(30*24*3600)
