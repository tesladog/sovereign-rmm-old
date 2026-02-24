"""Task management and dispatch."""
import json, uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Task, TaskResult, Device
from main import get_db, get_redis

router = APIRouter()


@router.get("/")
async def list_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).order_by(Task.created_at.desc()))
    return [
        {
            "id": t.id, "name": t.name, "description": t.description,
            "script_type": t.script_type, "target_type": t.target_type,
            "target_id": t.target_id, "status": t.status,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
            "recurring": t.recurring, "cron_expression": t.cron_expression,
            "created_at": t.created_at.isoformat(),
        }
        for t in result.scalars().all()
    ]


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
        run_now=data.get("run_now", False),
        scheduled_at=datetime.fromisoformat(data["scheduled_at"]) if data.get("scheduled_at") else None,
        recurring=data.get("recurring", False),
        cron_expression=data.get("cron_expression"),
        status="pending",
    )
    db.add(task)
    await db.commit()

    if data.get("dispatch_now") or task.run_now:
        target = task.target_id if task.target_type == "device" else "all"
        await redis.publish("push_commands", json.dumps({
            "type": "run_task", "device_id": target,
            "data": {"task_id": task.id, "script_type": task.script_type,
                     "script_body": task.script_body, "name": task.name}
        }))
        task.status = "dispatched"
        await db.commit()

    return {"id": task.id, "status": task.status}


@router.post("/{task_id}/dispatch")
async def dispatch_now(task_id: str, db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    target = task.target_id if task.target_type == "device" else "all"
    await redis.publish("push_commands", json.dumps({
        "type": "run_task", "device_id": target,
        "data": {"task_id": task.id, "script_type": task.script_type,
                 "script_body": task.script_body, "name": task.name}
    }))
    task.status = "dispatched"
    await db.commit()
    return {"status": "dispatched"}


@router.get("/{task_id}/results")
async def get_results(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskResult, Device.hostname)
        .join(Device, TaskResult.device_id == Device.device_id)
        .where(TaskResult.task_id == task_id)
        .order_by(TaskResult.completed_at.desc())
    )
    return [
        {
            "id": r.TaskResult.id, "device_id": r.TaskResult.device_id,
            "hostname": r.hostname, "exit_code": r.TaskResult.exit_code,
            "stdout": r.TaskResult.stdout, "stderr": r.TaskResult.stderr,
            "started_at": r.TaskResult.started_at.isoformat() if r.TaskResult.started_at else None,
            "completed_at": r.TaskResult.completed_at.isoformat() if r.TaskResult.completed_at else None,
        }
        for r in result.all()
    ]
