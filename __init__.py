"""Alerts — email notifications on task failure."""
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import select
from models import Setting


async def send_failure_alert(task_id: str, device_id: str, stderr: str):
    """Send email alert when a task fails. Reads SMTP settings from DB."""
    try:
        from main import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Setting))
            settings = {s.key: s.value for s in result.scalars().all()}

        alert_email = settings.get("alert_email", "")
        smtp_host   = settings.get("smtp_host", "")
        smtp_port   = int(settings.get("smtp_port", "587"))
        smtp_user   = settings.get("smtp_user", "")
        smtp_pass   = settings.get("smtp_pass", "")

        if not all([alert_email, smtp_host, smtp_user, smtp_pass]):
            return  # Email not configured

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Sovereign RMM] Task Failed on {device_id}"
        msg["From"]    = smtp_user
        msg["To"]      = alert_email

        body = f"""
Task Failure Alert
==================
Task ID:   {task_id}
Device:    {device_id}
Time:      {__import__('datetime').datetime.utcnow().isoformat()}

Error Output:
{stderr[:2000]}

---
Sovereign RMM
        """.strip()

        msg.attach(MIMEText(body, "plain"))
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, alert_email, msg.as_string())
    except Exception as e:
        print(f"Alert email failed: {e}")
