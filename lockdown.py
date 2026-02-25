"""Agent Builder — generates Windows .exe, Linux .deb/.sh, Android zip."""
import os, shutil, subprocess, sys, textwrap, uuid, zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
AGENT_TOKEN = os.getenv("AGENT_TOKEN","")
BUILD_DIR   = Path("/app/agent-builds")
BUILD_DIR.mkdir(parents=True, exist_ok=True)

WIN_TEMPLATE     = Path("/app/agent/windows_agent.py")
LINUX_TEMPLATE   = Path("/app/agent-linux/linux_agent.py")
ANDROID_TEMPLATE = Path("/app/agent-android/android_agent.py")

def bake(template, local_ip, vpn_ip, port, token):
    src = template.read_text()
    return src.replace('"RMM_LOCAL_IP"',f'"{local_ip}"').replace('"RMM_VPN_IP"',f'"{vpn_ip}"').replace('"RMM_PORT"',f'"{port}"').replace('"RMM_TOKEN"',f'"{token}"')

@router.post("/build/windows")
async def build_windows(data: dict):
    local_ip=data.get("local_ip",os.getenv("SERVER_IP","192.168.5.199"))
    vpn_ip=data.get("vpn_ip","100.125.120.81")
    port=data.get("port",os.getenv("BACKEND_PORT","8000"))
    build_id=str(uuid.uuid4())[:8]
    tmp=Path(f"/tmp/sov-w-{build_id}"); tmp.mkdir(parents=True)
    try:
        code=bake(WIN_TEMPLATE,local_ip,vpn_ip,port,AGENT_TOKEN)
        (tmp/"windows_agent.py").write_text(code)
        subprocess.run([sys.executable,"-m","pip","install","--quiet","pyinstaller","psutil","websockets","requests"],check=True,capture_output=True)
        r=subprocess.run([sys.executable,"-m","PyInstaller","--onefile","--noconsole","--name","SovereignAgent","--distpath",str(tmp/"dist"),"--workpath",str(tmp/"work"),"--specpath",str(tmp),str(tmp/"windows_agent.py")],capture_output=True,text=True,timeout=300)
        if r.returncode!=0: raise HTTPException(500,f"Build failed: {r.stderr[-2000:]}")
        exe=tmp/"dist"/"SovereignAgent.exe"
        if not exe.exists(): raise HTTPException(500,"EXE not produced")
        final=BUILD_DIR/f"SovereignRMM-Windows-{build_id}.exe"
        shutil.copy(exe,final)
        return {"status":"success","download_url":f"/api/builds/download/{final.name}","filename":final.name}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500,str(e))
    finally: shutil.rmtree(tmp,ignore_errors=True)

@router.post("/build/linux")
async def build_linux(data: dict):
    local_ip=data.get("local_ip",os.getenv("SERVER_IP","192.168.5.199"))
    vpn_ip=data.get("vpn_ip","100.125.120.81")
    port=data.get("port",os.getenv("BACKEND_PORT","8000"))
    build_id=str(uuid.uuid4())[:8]
    tmp=Path(f"/tmp/sov-l-{build_id}"); tmp.mkdir(parents=True)
    try:
        code=bake(LINUX_TEMPLATE,local_ip,vpn_ip,port,AGENT_TOKEN)
        install_script=f"""#!/bin/bash
set -e
echo "Installing Sovereign RMM Agent..."
which pip3 || apt-get install -y python3-pip 2>/dev/null
pip3 install --quiet psutil websockets requests
mkdir -p /usr/lib/sovereign-rmm /var/lib/sovereign-rmm
cat > /usr/lib/sovereign-rmm/agent.py << 'AGEOF'
{code}
AGEOF
cat > /etc/systemd/system/sovereign-rmm.service << 'SVCEOF'
[Unit]
Description=Sovereign RMM Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/lib/sovereign-rmm/agent.py
Restart=always
RestartSec=30
StandardOutput=append:/var/log/sovereign-rmm.log
StandardError=append:/var/log/sovereign-rmm.log
[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload && systemctl enable sovereign-rmm && systemctl start sovereign-rmm
echo "Done! Agent running as systemd service."
echo "Check status: systemctl status sovereign-rmm"
echo "View logs:    journalctl -u sovereign-rmm -f"
"""
        sh_file=tmp/f"install.sh"; sh_file.write_text(install_script)
        final=BUILD_DIR/f"SovereignRMM-Linux-{build_id}.sh"
        shutil.copy(sh_file,final)
        return {"status":"success","download_url":f"/api/builds/download/{final.name}","filename":final.name,
                "note":f"Run on your Ubuntu machine: sudo bash {final.name}"}
    except Exception as e: raise HTTPException(500,str(e))
    finally: shutil.rmtree(tmp,ignore_errors=True)

@router.post("/build/android")
async def build_android(data: dict):
    local_ip=data.get("local_ip",os.getenv("SERVER_IP","192.168.5.199"))
    vpn_ip=data.get("vpn_ip","100.125.120.81")
    port=data.get("port",os.getenv("BACKEND_PORT","8000"))
    build_id=str(uuid.uuid4())[:8]
    tmp=Path(f"/tmp/sov-a-{build_id}"); tmp.mkdir(parents=True)
    try:
        code=bake(ANDROID_TEMPLATE,local_ip,vpn_ip,port,AGENT_TOKEN)
        (tmp/"sovereign_agent.py").write_text(code)
        (tmp/"install_termux.sh").write_text(f"""#!/data/data/com.termux/files/usr/bin/sh
pkg update -y && pkg install python -y
pip install psutil websockets requests --quiet
mkdir -p ~/.sovereign-rmm ~/.termux/boot
cp sovereign_agent.py ~/.sovereign-rmm/agent.py
printf '#!/data/data/com.termux/files/usr/bin/sh\\npython ~/.sovereign-rmm/agent.py &\\n' > ~/.termux/boot/sovereign-rmm.sh
chmod +x ~/.termux/boot/sovereign-rmm.sh
python ~/.sovereign-rmm/agent.py &
echo "Agent installed and running. Get Termux:Boot from F-Droid for auto-start."
""")
        (tmp/"README.txt").write_text(f"SOVEREIGN RMM Android Agent\nServer: {local_ip} / {vpn_ip}\nInstall Termux from F-Droid, then run: sh install_termux.sh")
        zip_file=BUILD_DIR/f"SovereignRMM-Android-{build_id}.zip"
        with zipfile.ZipFile(zip_file,"w") as zf:
            for f in tmp.iterdir(): zf.write(f,f.name)
        return {"status":"success","download_url":f"/api/builds/download/{zip_file.name}","filename":zip_file.name}
    except Exception as e: raise HTTPException(500,str(e))
    finally: shutil.rmtree(tmp,ignore_errors=True)

@router.get("/download/{filename}")
async def download(filename: str):
    if "/" in filename or ".." in filename: raise HTTPException(400,"Invalid")
    f=BUILD_DIR/filename
    if not f.exists(): raise HTTPException(404,"Not found")
    return FileResponse(str(f),filename=filename,media_type="application/octet-stream")
