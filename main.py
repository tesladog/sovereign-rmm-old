"""Wake on LAN — send magic packets from the server."""
import socket, struct, uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update
from models import WolEvent, Device
from main import get_db

router = APIRouter()


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9):
    """Send a WoL magic packet to the broadcast address."""
    mac_clean = mac.replace(":", "").replace("-", "").replace(".", "").upper()
    if len(mac_clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    mac_bytes = bytes.fromhex(mac_clean)
    magic = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic, (broadcast, port))


@router.post("/wake/{device_id}")
async def wake_device(device_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.mac_address:
        raise HTTPException(status_code=400, detail="No MAC address stored for this device. The agent reports its MAC on check-in.")

    try:
        send_magic_packet(device.mac_address)
        db.add(WolEvent(
            id=str(uuid.uuid4()), device_id=device_id,
            target=device.hostname, mac=device.mac_address,
            triggered_by="admin", timestamp=datetime.utcnow()
        ))
        await db.commit()
        return {"status": "magic_packet_sent", "mac": device.mac_address, "device": device.hostname}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wake/mac")
async def wake_by_mac(data: dict, db: AsyncSession = Depends(get_db)):
    """Wake any device by raw MAC — for devices not enrolled yet."""
    mac = data.get("mac", "")
    broadcast = data.get("broadcast", "255.255.255.255")
    if not mac:
        raise HTTPException(status_code=400, detail="mac required")
    try:
        send_magic_packet(mac, broadcast)
        db.add(WolEvent(
            id=str(uuid.uuid4()), target=mac, mac=mac,
            triggered_by="admin", timestamp=datetime.utcnow()
        ))
        await db.commit()
        return {"status": "magic_packet_sent", "mac": mac}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/device/{device_id}/mac")
async def set_mac(device_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    """Manually set a device's MAC address."""
    mac = data.get("mac", "")
    await db.execute(update(Device).where(Device.device_id == device_id).values(mac_address=mac))
    await db.commit()
    return {"status": "saved"}


@router.get("/history")
async def wol_history(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WolEvent).order_by(desc(WolEvent.timestamp)).limit(50))
    return [
        {"id": e.id, "target": e.target, "mac": e.mac,
         "triggered_by": e.triggered_by, "timestamp": e.timestamp.isoformat()}
        for e in result.scalars().all()
    ]
