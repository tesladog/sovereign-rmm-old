"""
SOVEREIGN RMM — Backend API
FastAPI application serving both the agent API and the dashboard API.
"""

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from models import Base, Device, Task, TaskResult, LogEntry
from routes import devices, tasks, policies, dashboard, auth

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL    = os.getenv("REDIS_URL")
AGENT_TOKEN  = os.getenv("AGENT_TOKEN")
SERVER_IP    = os.getenv("SERVER_IP", "localhost")
SERVER_PORT  = os.getenv("BACKEND_PORT", "8000")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

redis_pool = None
active_connections: dict[str, WebSocket] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_pool
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    redis_pool = await aioredis.from_url(REDIS_URL, decode_responses=True)
    asyncio.create_task(listen_for_push_commands())
    yield
    await redis_pool.aclose()
    await engine.dispose()


app = FastAPI(title="Sovereign RMM API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def get_redis():
    return redis_pool


def verify_agent_token(x_agent_token: str = Header(None)):
    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid agent token")


# ── AGENT WEBSOCKET ──────────────────────────────────────────

@app.websocket("/ws/agent/{device_id}")
async def agent_websocket(websocket: WebSocket, device_id: str):
    token = websocket.query_params.get("token")
    if token != AGENT_TOKEN:
        await websocket.close(code=4003)
        return

    await websocket.accept()
    active_connections[device_id] = websocket

    try:
        async for raw_message in websocket.iter_text():
            message = json.loads(raw_message)
            async with AsyncSessionLocal() as db:
                t = message.get("type")
                if t == "heartbeat":
                    await handle_heartbeat(db, device_id, message)
                elif t == "task_result":
                    await handle_task_result(db, device_id, message)
                elif t == "log":
                    await handle_log(db, device_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.pop(device_id, None)
        async with AsyncSessionLocal() as db:
            await update_device_status(db, device_id, "offline")


async def handle_heartbeat(db, device_id, message):
    from sqlalchemy import update
    data = message.get("data", {})
    await db.execute(
        update(Device).where(Device.device_id == device_id).values(
            last_seen=datetime.utcnow(),
            status="online",
            battery_level=data.get("battery_level"),
            battery_charging=data.get("battery_charging", False),
            cpu_percent=data.get("cpu_percent"),
            ram_percent=data.get("ram_percent"),
            disk_percent=data.get("disk_percent"),
            ip_address=data.get("ip_address", ""),
        )
    )
    await db.commit()


async def handle_task_result(db, device_id, message):
    data = message.get("data", {})
    result = TaskResult(
        id=str(uuid.uuid4()),
        task_id=data.get("task_id"),
        device_id=device_id,
        exit_code=data.get("exit_code"),
        stdout=data.get("stdout", ""),
        stderr=data.get("stderr", ""),
        started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
        completed_at=datetime.utcnow(),
    )
    db.add(result)
    await db.commit()


async def handle_log(db, device_id, message):
    data = message.get("data", {})
    log = LogEntry(
        id=str(uuid.uuid4()),
        device_id=device_id,
        level=data.get("level", "info"),
        message=data.get("message", ""),
        timestamp=datetime.utcnow(),
    )
    db.add(log)
    await db.commit()


async def update_device_status(db, device_id, status):
    from sqlalchemy import update
    await db.execute(update(Device).where(Device.device_id == device_id).values(status=status))
    await db.commit()


# ── REDIS PUSH LISTENER ──────────────────────────────────────

async def listen_for_push_commands():
    global redis_pool
    await asyncio.sleep(3)
    pubsub = redis_pool.pubsub()
    await pubsub.subscribe("push_commands")
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            payload = json.loads(message["data"])
            target = payload.get("device_id")
            if target == "all":
                for ws in list(active_connections.values()):
                    await ws.send_text(json.dumps(payload))
            elif target and target in active_connections:
                await active_connections[target].send_text(json.dumps(payload))
        except Exception as e:
            print(f"Push error: {e}")


# ── AGENT CHECK-IN ───────────────────────────────────────────

@app.post("/api/agent/checkin", dependencies=[Depends(verify_agent_token)])
async def agent_checkin(data: dict, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from models import Policy

    device_id = data.get("device_id")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")

    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()

    if not device:
        device = Device(
            device_id=device_id,
            hostname=data.get("hostname", "Unknown"),
            platform=data.get("platform", "unknown"),
            os_info=data.get("os_info", ""),
            ip_address=data.get("ip_address", ""),
            agent_version=data.get("agent_version", "1.0.0"),
            status="online",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        db.add(device)
    else:
        device.last_seen = datetime.utcnow()
        device.status = "online"
        device.ip_address = data.get("ip_address", device.ip_address)

    await db.commit()

    policy_result = await db.execute(
        select(Policy).where(
            (Policy.device_id == device_id) | (Policy.device_id == None)
        ).order_by(Policy.device_id.nulls_last())
    )
    policy = policy_result.scalar_one_or_none()

    policy_data = {
        "checkin_plugged_seconds": policy.checkin_plugged_seconds if policy else 30,
        "checkin_battery_100_80_seconds": policy.checkin_battery_100_80_seconds if policy else 60,
        "checkin_battery_79_50_seconds": policy.checkin_battery_79_50_seconds if policy else 180,
        "checkin_battery_49_20_seconds": policy.checkin_battery_49_20_seconds if policy else 300,
        "checkin_battery_19_10_seconds": policy.checkin_battery_19_10_seconds if policy else 600,
        "checkin_battery_9_0_seconds": policy.checkin_battery_9_0_seconds if policy else 900,
    }

    return {
        "device_id": device.device_id,
        "registered": True,
        "policy": policy_data,
        "websocket_url": f"ws://{SERVER_IP}:{SERVER_PORT}/ws/agent/{device_id}",
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── ROUTERS ──────────────────────────────────────────────────

app.include_router(auth.router,      prefix="/api/auth",               tags=["Auth"])
app.include_router(devices.router,   prefix="/api/dashboard/devices",  tags=["Devices"])
app.include_router(tasks.router,     prefix="/api/dashboard/tasks",    tags=["Tasks"])
app.include_router(policies.router,  prefix="/api/dashboard/policies", tags=["Policies"])
app.include_router(dashboard.router, prefix="/api/dashboard",          tags=["Dashboard"])
