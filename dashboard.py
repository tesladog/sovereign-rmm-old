"""Script Library — reusable saved scripts with categories."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from models import ScriptLibrary
from main import get_db

router = APIRouter()

# Built-in starter scripts
BUILTIN_SCRIPTS = [
    {"name": "Disk Cleanup (Windows)", "category": "Maintenance", "platform": "windows", "script_type": "powershell",
     "description": "Clean temp files, empty recycle bin, run cleanmgr",
     "script_body": "Remove-Item -Path $env:TEMP\\* -Recurse -Force -ErrorAction SilentlyContinue\nClear-RecycleBin -Force -ErrorAction SilentlyContinue\nWrite-Output 'Cleanup complete'"},
    {"name": "System Info (Windows)", "category": "Monitoring", "platform": "windows", "script_type": "powershell",
     "description": "Get detailed system information",
     "script_body": "Get-ComputerInfo | Select-Object CsName,OsName,OsVersion,CsProcessors,CsTotalPhysicalMemory | Format-List"},
    {"name": "List Running Services", "category": "Monitoring", "platform": "windows", "script_type": "powershell",
     "description": "List all running Windows services",
     "script_body": "Get-Service | Where-Object {$_.Status -eq 'Running'} | Select-Object Name,DisplayName | Format-Table -AutoSize"},
    {"name": "Windows Update Check", "category": "Maintenance", "platform": "windows", "script_type": "powershell",
     "description": "Check for pending Windows updates",
     "script_body": "Install-Module PSWindowsUpdate -Force -Scope CurrentUser -ErrorAction SilentlyContinue\nGet-WindowsUpdate"},
    {"name": "Restart Explorer", "category": "Maintenance", "platform": "windows", "script_type": "powershell",
     "description": "Restart Windows Explorer process",
     "script_body": "Stop-Process -Name explorer -Force; Start-Process explorer\nWrite-Output 'Explorer restarted'"},
    {"name": "Check Disk Space (Linux)", "category": "Monitoring", "platform": "linux", "script_type": "bash",
     "description": "Show disk usage for all mounted volumes",
     "script_body": "df -h && echo '---' && du -sh /var/log/* 2>/dev/null | sort -rh | head -20"},
    {"name": "Update All Packages (Ubuntu)", "category": "Maintenance", "platform": "linux", "script_type": "bash",
     "description": "Run apt update and upgrade",
     "script_body": "apt-get update -y && apt-get upgrade -y && apt-get autoremove -y\necho 'Updates complete'"},
    {"name": "System Info (Linux)", "category": "Monitoring", "platform": "linux", "script_type": "bash",
     "description": "Show OS, CPU, RAM, uptime",
     "script_body": "uname -a && uptime && free -h && df -h"},
    {"name": "List Top Processes", "category": "Monitoring", "platform": "linux", "script_type": "bash",
     "description": "Show top CPU-consuming processes",
     "script_body": "ps aux --sort=-%cpu | head -20"},
    {"name": "Battery Status (Android)", "category": "Monitoring", "platform": "android", "script_type": "bash",
     "description": "Check battery level and charging status",
     "script_body": "cat /sys/class/power_supply/battery/capacity && cat /sys/class/power_supply/battery/status"},
    {"name": "Storage Info (Android)", "category": "Monitoring", "platform": "android", "script_type": "bash",
     "description": "Show storage usage on Android",
     "script_body": "df -h && du -sh /sdcard/* 2>/dev/null | sort -rh | head -10"},
]


@router.get("/")
async def list_scripts(category: str = None, platform: str = None, db: AsyncSession = Depends(get_db)):
    query = select(ScriptLibrary).order_by(ScriptLibrary.category, ScriptLibrary.name)
    if category:
        query = query.where(ScriptLibrary.category == category)
    if platform and platform != "all":
        query = query.where((ScriptLibrary.platform == platform) | (ScriptLibrary.platform == "all"))
    result = await db.execute(query)
    scripts = result.scalars().all()
    return [
        {"id": s.id, "name": s.name, "description": s.description,
         "category": s.category, "platform": s.platform,
         "script_type": s.script_type, "script_body": s.script_body,
         "tags": s.tags or [], "run_count": s.run_count,
         "created_at": s.created_at.isoformat()}
        for s in scripts
    ]


@router.post("/seed")
async def seed_builtin_scripts(db: AsyncSession = Depends(get_db)):
    """Seed the built-in starter scripts — call once from UI."""
    count = 0
    for s in BUILTIN_SCRIPTS:
        existing = await db.execute(select(ScriptLibrary).where(ScriptLibrary.name == s["name"]))
        if not existing.scalar_one_or_none():
            db.add(ScriptLibrary(id=str(uuid.uuid4()), **s, tags=[]))
            count += 1
    await db.commit()
    return {"seeded": count}


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary.category).distinct())
    return sorted(set(row[0] for row in result.all() if row[0]))


@router.post("/")
async def create_script(data: dict, db: AsyncSession = Depends(get_db)):
    script = ScriptLibrary(
        id=str(uuid.uuid4()),
        name=data.get("name", "Unnamed Script"),
        description=data.get("description", ""),
        category=data.get("category", "Custom"),
        platform=data.get("platform", "all"),
        script_type=data.get("script_type", "powershell"),
        script_body=data.get("script_body", ""),
        tags=data.get("tags", []),
    )
    db.add(script)
    await db.commit()
    return {"id": script.id}


@router.put("/{script_id}")
async def update_script(script_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary).where(ScriptLibrary.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    for field in ("name", "description", "category", "platform", "script_type", "script_body", "tags"):
        if field in data:
            setattr(s, field, data[field])
    s.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "updated"}


@router.delete("/{script_id}")
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary).where(ScriptLibrary.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(s)
    await db.commit()
    return {"status": "deleted"}
