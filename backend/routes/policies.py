"""Check-in policy management."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Policy
from main import get_db

router = APIRouter()
FIELDS = [
    "checkin_plugged_seconds", "checkin_battery_100_80_seconds",
    "checkin_battery_79_50_seconds", "checkin_battery_49_20_seconds",
    "checkin_battery_19_10_seconds", "checkin_battery_9_0_seconds",
    "low_battery_alert_threshold",
]


@router.get("/default")
async def get_default(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Policy).where(Policy.device_id == None))
    p = result.scalar_one_or_none()
    if not p:
        return {f: getattr(Policy, f).default.arg for f in FIELDS}
    return {f: getattr(p, f) for f in FIELDS}


@router.put("/default")
async def update_default(data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Policy).where(Policy.device_id == None))
    p = result.scalar_one_or_none()
    if not p:
        p = Policy(id=str(uuid.uuid4()), device_id=None)
        db.add(p)
    for f in FIELDS:
        if f in data:
            setattr(p, f, data[f])
    p.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "updated"}


@router.put("/device/{device_id}")
async def update_device_policy(device_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Policy).where(Policy.device_id == device_id))
    p = result.scalar_one_or_none()
    if not p:
        p = Policy(id=str(uuid.uuid4()), device_id=device_id)
        db.add(p)
    for f in FIELDS:
        if f in data:
            setattr(p, f, data[f])
    p.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "updated"}
