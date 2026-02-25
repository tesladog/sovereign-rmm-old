"""Email Service — SMTP config, test send, templates, alerts."""
import smtplib, ssl, uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Setting, EmailTemplate
from main import get_db

router = APIRouter()

DEFAULT_TEMPLATES = [
    {
        "name": "Task Failed",
        "trigger": "task_failed",
        "subject": "[Sovereign RMM] Task Failed — {task_name} on {device}",
        "body_html": """<h2 style="color:#ff5252">⚠ Task Failed</h2>
<p><b>Task:</b> {task_name}<br>
<b>Device:</b> {device}<br>
<b>Time:</b> {timestamp}</p>
<pre style="background:#111;color:#ff5252;padding:12px;border-radius:6px">{stderr}</pre>
<hr><small>Sovereign RMM</small>"""
    },
    {
        "name": "Device Offline",
        "trigger": "device_offline",
        "subject": "[Sovereign RMM] Device Offline — {device}",
        "body_html": """<h2 style="color:#ff9100">📴 Device Offline</h2>
<p><b>Device:</b> {device}<br>
<b>Last Seen:</b> {last_seen}<br>
<b>IP:</b> {ip}</p>
<hr><small>Sovereign RMM</small>"""
    },
    {
        "name": "Lockdown Enabled",
        "trigger": "lockdown_enabled",
        "subject": "[Sovereign RMM] 🔒 LOCKDOWN MODE ACTIVATED",
        "body_html": """<h2 style="color:#ff5252">🔒 Lockdown Mode Activated</h2>
<p><b>Reason:</b> {reason}<br>
<b>By:</b> {triggered_by}<br>
<b>Time:</b> {timestamp}</p>
<p>All logins are now blocked. Disable lockdown mode in the RMM dashboard.</p>
<hr><small>Sovereign RMM</small>"""
    },
    {
        "name": "Low Battery Alert",
        "trigger": "low_battery",
        "subject": "[Sovereign RMM] Low Battery — {device} at {level}%",
        "body_html": """<h2 style="color:#ffd740">🔋 Low Battery Warning</h2>
<p><b>Device:</b> {device}<br>
<b>Battery:</b> {level}%<br>
<b>Time:</b> {timestamp}</p>
<hr><small>Sovereign RMM</small>"""
    },
]


async def get_smtp_settings(db: AsyncSession) -> dict:
    result = await db.execute(select(Setting))
    return {s.key: s.value for s in result.scalars().all()}


async def send_email_raw(smtp: dict, to: str, subject: str, body_html: str):
    if not all([smtp.get("smtp_host"), smtp.get("smtp_user"), smtp.get("smtp_pass")]):
        raise ValueError("SMTP not configured — fill in Settings → Email Alerts")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp.get("smtp_user", "")
    msg["To"]      = to
    msg.attach(MIMEText(body_html, "html"))
    port = int(smtp.get("smtp_port", "587"))
    ctx  = ssl.create_default_context()
    with smtplib.SMTP(smtp.get("smtp_host"), port, timeout=15) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.login(smtp.get("smtp_user"), smtp.get("smtp_pass"))
        server.sendmail(smtp.get("smtp_user"), to, msg.as_string())


async def send_alert(trigger: str, variables: dict, db=None):
    """Send an alert email by trigger name. Called from other routes."""
    if db is None:
        from main import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            return await send_alert(trigger, variables, db)

    smtp = await get_smtp_settings(db)
    to   = smtp.get("alert_email", "")
    if not to:
        return

    # Find active template for this trigger
    tpl_result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.trigger == trigger, EmailTemplate.active == True)
    )
    tpl = tpl_result.scalar_one_or_none()
    if not tpl:
        return

    subject  = tpl.subject.format(**variables)
    body     = tpl.body_html.format(**variables)
    try:
        await send_email_raw(smtp, to, subject, body)
    except Exception as e:
        print(f"[Email] Failed to send {trigger} alert: {e}")


# ── ROUTES ───────────────────────────────────────────────────

@router.post("/test")
async def test_email(data: dict, db: AsyncSession = Depends(get_db)):
    smtp = await get_smtp_settings(db)
    to   = data.get("to") or smtp.get("alert_email", "")
    if not to:
        raise HTTPException(400, "No recipient — set Alert Email in Settings")
    try:
        await send_email_raw(smtp, to,
            "[Sovereign RMM] Test Email ✓",
            "<h2>✓ Email is working!</h2><p>Your Sovereign RMM email alerts are configured correctly.</p><hr><small>Sovereign RMM</small>")
        return {"status": "sent", "to": to}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(EmailTemplate))
    return [
        {"id": t.id, "name": t.name, "trigger": t.trigger,
         "subject": t.subject, "body_html": t.body_html, "active": t.active}
        for t in result.scalars().all()
    ]


@router.post("/templates/seed")
async def seed_templates(db: AsyncSession = Depends(get_db)):
    count = 0
    for tpl in DEFAULT_TEMPLATES:
        existing = await db.execute(select(EmailTemplate).where(EmailTemplate.trigger == tpl["trigger"]))
        if not existing.scalar_one_or_none():
            db.add(EmailTemplate(id=str(uuid.uuid4()), **tpl))
            count += 1
    await db.commit()
    return {"seeded": count}


@router.put("/templates/{tpl_id}")
async def update_template(tpl_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.id == tpl_id))
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Template not found")
    for field in ("name", "subject", "body_html", "active"):
        if field in data:
            setattr(tpl, field, data[field])
    await db.commit()
    return {"status": "updated"}
