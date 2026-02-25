"""Tasks — all trigger types, scheduling, live progress."""
import json, uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from models import Task, TaskResult, Device, ScriptLibrary
from main import get_db, get_redis, dispatch_task

router = APIRouter()


@router.get("/")
async def list_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).order_by(desc(Task.created_at)).limit(200))
    tasks = result.scalars().all()
    out = []
    for t in tasks:
        # Get result counts
        res = await db.execute(select(TaskResult).where(TaskResult.task_id == t.id))
        results = res.scalars().all()
        success = sum(1 for r in results if r.exit_code == 0)
        failed  = sum(1 for r in results if r.exit_code != 0 and r.exit_code is not None)
        out.append({
            "id": t.id, "name": t.name, "description": t.description,
            "script_type": t.script_type, "target_type": t.target_type,
            "target_id": t.target_id, "target_platform": t.target_platform,
            "trigger_type": t.trigger_type, "status": t.status,
            "cancelled": t.cancelled,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
            "interval_seconds": t.interval_seconds,
            "cron_expression": t.cron_expression,
            "event_trigger": t.event_trigger,
            "created_at": t.created_at.isoformat(),
            "result_count": len(results),
            "success_count": success,
            "failed_count": failed,
        })
    return out


@router.post("/")
async def create_task(data: dict, db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    task = Task(
        id=str(uuid.uuid4()),
        name=data.get("name", "Unnamed Task"),
        description=data.get("description", ""),
        script_type=data.get("script_type", "powershell"),
        script_body=data.get("script_body", ""),
        target_type=data.get("target_type", "all"),
        target_id=data.get("target_id"),
        target_platform=data.get("target_platform", "all"),
        trigger_type=data.get("trigger_type", "now"),
        scheduled_at=datetime.fromisoformat(data["scheduled_at"]) if data.get("scheduled_at") else None,
        interval_seconds=data.get("interval_seconds"),
        cron_expression=data.get("cron_expression"),
        event_trigger=data.get("event_trigger"),
        from_library=data.get("from_library"),
        status="pending",
    )
    db.add(task)

    # If from script library, increment run count
    if task.from_library:
        res = await db.execute(select(ScriptLibrary).where(ScriptLibrary.id == task.from_library))
        lib = res.scalar_one_or_none()
        if lib:
            lib.run_count += 1

    await db.commit()

    # Dispatch immediately if trigger is 'now'
    if task.trigger_type == "now":
        # Create pending result records for targeted devices
        await _create_result_stubs(db, task)
        await dispatch_task(db, task)

    return {"id": task.id, "status": task.status}


async def _create_result_stubs(db, task: Task):
    """Pre-create TaskResult rows so we can track progress before results come back."""
    if task.target_type == "device" and task.target_id:
        device_ids = [task.target_id]
    else:
        result = await db.execute(select(Device.device_id).where(Device.status == "online"))
        device_ids = [row[0] for row in result.all()]

    for did in device_ids:
        db.add(TaskResult(
            id=str(uuid.uuid4()), task_id=task.id, device_id=did,
            status="running", started_at=datetime.utcnow(), progress=0,
        ))
    await db.commit()


@router.post("/{task_id}/dispatch")
async def dispatch_now(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.cancelled:
        raise HTTPException(status_code=400, detail="Task is cancelled")
    await _create_result_stubs(db, task)
    await dispatch_task(db, task)
    return {"status": "dispatched"}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.cancelled = True
    task.status    = "cancelled"
    await db.commit()
    return {"status": "cancelled"}


@router.get("/{task_id}/results")
async def get_results(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskResult, Device.hostname, Device.label)
        .join(Device, TaskResult.device_id == Device.device_id)
        .where(TaskResult.task_id == task_id)
        .order_by(desc(TaskResult.started_at))
    )
    return [
        {
            "id": r.TaskResult.id, "device_id": r.TaskResult.device_id,
            "hostname": r.label or r.hostname, "exit_code": r.TaskResult.exit_code,
            "stdout": r.TaskResult.stdout, "stderr": r.TaskResult.stderr,
            "status": r.TaskResult.status, "progress": r.TaskResult.progress,
            "started_at": r.TaskResult.started_at.isoformat() if r.TaskResult.started_at else None,
            "completed_at": r.TaskResult.completed_at.isoformat() if r.TaskResult.completed_at else None,
        }
        for r in result.all()
    ]


@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(task)
    await db.commit()
    return {"status": "deleted"}
