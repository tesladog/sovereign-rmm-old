"""Lockdown Mode — blocks all logins, full history."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from models import LockdownEvent, Setting
from main import get_db

router = APIRouter()

LOCKDOWN_KEY = "lockdown_enabled"


async def is_lockdown_active(db: AsyncSession) -> bool:
    result = await db.execute(select(Setting).where(Setting.key == LOCKDOWN_KEY))
    s = result.scalar_one_or_none()
    return s is not None and s.value == "true"


@router.get("/status")
async def lockdown_status(db: AsyncSession = Depends(get_db)):
    active = await is_lockdown_active(db)
    # Get last event
    result = await db.execute(
        select(LockdownEvent).order_by(desc(LockdownEvent.timestamp)).limit(1)
    )
    last = result.scalar_one_or_none()
    return {
        "active": active,
        "last_event": {
            "action": last.action,
            "reason": last.reason,
            "triggered_by": last.triggered_by,
            "timestamp": last.timestamp.isoformat(),
        } if last else None
    }


@router.post("/enable")
async def enable_lockdown(data: dict, db: AsyncSession = Depends(get_db)):
    reason = data.get("reason", "No reason given")
    # Set setting
    result = await db.execute(select(Setting).where(Setting.key == LOCKDOWN_KEY))
    s = result.scalar_one_or_none()
    if s:
        s.value = "true"
    else:
        db.add(Setting(key=LOCKDOWN_KEY, value="true", label="Lockdown Mode", category="security"))
    # Log event
    db.add(LockdownEvent(
        id=str(uuid.uuid4()), action="enabled",
        reason=reason, triggered_by="admin", timestamp=datetime.utcnow()
    ))
    await db.commit()
    return {"status": "lockdown_enabled"}


@router.post("/disable")
async def disable_lockdown(data: dict, db: AsyncSession = Depends(get_db)):
    reason = data.get("reason", "")
    result = await db.execute(select(Setting).where(Setting.key == LOCKDOWN_KEY))
    s = result.scalar_one_or_none()
    if s:
        s.value = "false"
    db.add(LockdownEvent(
        id=str(uuid.uuid4()), action="disabled",
        reason=reason, triggered_by="admin", timestamp=datetime.utcnow()
    ))
    await db.commit()
    return {"status": "lockdown_disabled"}


@router.get("/history")
async def lockdown_history(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(LockdownEvent).order_by(desc(LockdownEvent.timestamp)).limit(100)
    )
    return [
        {
            "id": e.id, "action": e.action, "reason": e.reason,
            "triggered_by": e.triggered_by,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in result.scalars().all()
    ]
