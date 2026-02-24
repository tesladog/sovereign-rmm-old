"""Auth — dashboard login."""
import hashlib, os, uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt
from models import AdminUser
from main import get_db

router = APIRouter()
SECRET = os.getenv("API_SECRET_KEY", "changeme")
ALGO   = "HS256"


def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()
def make_token(u): return jwt.encode({"sub": u, "exp": datetime.utcnow() + timedelta(hours=12)}, SECRET, algorithm=ALGO)


@router.post("/login")
async def login(data: dict, db: AsyncSession = Depends(get_db)):
    username = data.get("username", "")
    password = data.get("password", "")
    result = await db.execute(select(AdminUser).where(AdminUser.username == username))
    user = result.scalar_one_or_none()
    if not user:
        env_u = os.getenv("ADMIN_USERNAME", "admin")
        env_p = os.getenv("ADMIN_PASSWORD", "changeme")
        if username == env_u and password == env_p:
            user = AdminUser(id=str(uuid.uuid4()), username=username, hashed_password=hash_pw(password))
            db.add(user)
            await db.commit()
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.hashed_password != hash_pw(password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user.last_login = datetime.utcnow()
    await db.commit()
    return {"token": make_token(username), "username": username}
