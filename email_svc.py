"""Import / Export — full server backup as JSON zip."""
import io, json, uuid, zipfile
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from models import (Device, Asset, Task, TaskResult, ScriptLibrary, Policy,
                    Setting, LockdownEvent, EmailTemplate, LogEntry)
from main import get_db

router = APIRouter()

EXPORT_TABLES = [
    ("settings",       Setting),
    ("devices",        Device),
    ("assets",         Asset),
    ("tasks",          Task),
    ("task_results",   TaskResult),
    ("script_library", ScriptLibrary),
    ("policies",       Policy),
    ("lockdown_events",LockdownEvent),
    ("email_templates",EmailTemplate),
    ("logs",           LogEntry),
]


def row_to_dict(row) -> dict:
    result = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col.name] = val
    return result


@router.get("/export")
async def export_backup(db: AsyncSession = Depends(get_db)):
    """Export everything to a timestamped zip containing a single JSON file."""
    export = {
        "sovereign_rmm_export": True,
        "version": "2.0.0",
        "exported_at": datetime.utcnow().isoformat(),
        "tables": {}
    }
    for table_name, model in EXPORT_TABLES:
        result = await db.execute(select(model))
        rows = result.scalars().all()
        export["tables"][table_name] = [row_to_dict(r) for r in rows]

    json_bytes = json.dumps(export, indent=2, default=str).encode("utf-8")
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"sovereign_rmm_backup_{ts}.json", json_bytes)
    zip_buf.seek(0)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=sovereign_rmm_backup_{ts}.zip"}
    )


@router.post("/import")
async def import_backup(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Import a backup zip or JSON file. Merges — does not wipe existing data."""
    content = await file.read()
    if file.filename.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            json_name = [n for n in zf.namelist() if n.endswith(".json")][0]
            data = json.loads(zf.read(json_name))
    else:
        data = json.loads(content)

    if not data.get("sovereign_rmm_export"):
        raise HTTPException(400, "Not a valid Sovereign RMM backup file")

    stats = {}
    tables = data.get("tables", {})

    MODEL_MAP = {t[0]: t[1] for t in EXPORT_TABLES}
    SKIP_FIELDS = {"task_results", "logs"}  # Skip verbose history on import

    for table_name, rows in tables.items():
        if table_name in SKIP_FIELDS:
            continue
        model = MODEL_MAP.get(table_name)
        if not model:
            continue
        imported = 0
        for row_data in rows:
            # Check if already exists by primary key
            pk_col = model.__table__.primary_key.columns.keys()[0]
            pk_val = row_data.get(pk_col)
            if pk_val:
                existing = await db.execute(
                    select(model).where(getattr(model, pk_col) == pk_val)
                )
                if existing.scalar_one_or_none():
                    continue  # Skip existing
            # Clean up datetime fields
            for col in model.__table__.columns:
                if col.type.__class__.__name__ == "DateTime" and row_data.get(col.name):
                    try:
                        row_data[col.name] = datetime.fromisoformat(row_data[col.name])
                    except:
                        row_data[col.name] = None
                if col.name not in row_data:
                    row_data.pop(col.name, None)
            # Only keep valid columns
            valid = {c.name for c in model.__table__.columns}
            clean = {k: v for k, v in row_data.items() if k in valid}
            try:
                db.add(model(**clean))
                imported += 1
            except Exception as e:
                pass
        stats[table_name] = imported

    await db.commit()
    return {"status": "imported", "records_added": stats}
