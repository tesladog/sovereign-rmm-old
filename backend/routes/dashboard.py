"""Dashboard summary endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from models import Device, Task, LogEntry
from main import get_db

router = APIRouter()


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    total    = (await db.execute(select(func.count()).select_from(Device))).scalar()
    online   = (await db.execute(select(func.count()).select_from(Device).where(Device.status == "online"))).scalar()
    offline  = (await db.execute(select(func.count()).select_from(Device).where(Device.status == "offline"))).scalar()
    pending  = (await db.execute(select(func.count()).select_from(Task).where(Task.status == "pending"))).scalar()
    return {"total_devices": total, "online_devices": online, "offline_devices": offline, "tasks_pending": pending}


@router.get("/logs")
async def logs(limit: int = 200, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(LogEntry, Device.hostname)
        .outerjoin(Device, LogEntry.device_id == Device.device_id)
        .order_by(LogEntry.timestamp.desc()).limit(limit)
    )
    return [
        {
            "id": r.LogEntry.id, "device_id": r.LogEntry.device_id,
            "hostname": r.hostname, "level": r.LogEntry.level,
            "message": r.LogEntry.message,
            "timestamp": r.LogEntry.timestamp.isoformat(),
            "source": r.LogEntry.source,
        }
        for r in result.all()
    ]
