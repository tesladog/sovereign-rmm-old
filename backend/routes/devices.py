"""Device management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from models import Device
from main import get_db

router = APIRouter()


@router.get("/")
async def list_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device).order_by(Device.last_seen.desc()))
    return [
        {
            "device_id": d.device_id, "hostname": d.hostname,
            "label": d.label or d.hostname, "platform": d.platform,
            "os_info": d.os_info, "ip_address": d.ip_address,
            "status": d.status, "battery_level": d.battery_level,
            "battery_charging": d.battery_charging, "cpu_percent": d.cpu_percent,
            "ram_percent": d.ram_percent, "disk_percent": d.disk_percent,
            "group_name": d.group_name, "tags": d.tags or [],
            "first_seen": d.first_seen.isoformat() if d.first_seen else None,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
        }
        for d in result.scalars().all()
    ]


@router.patch("/{device_id}")
async def update_device(device_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    for field in ("label", "group_name", "tags"):
        if field in data:
            setattr(device, field, data[field])
    await db.commit()
    return {"status": "updated"}


@router.delete("/{device_id}")
async def delete_device(device_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Device).where(Device.device_id == device_id))
    await db.commit()
    return {"status": "deleted"}
