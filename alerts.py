"""SOVEREIGN RMM v2 — Database Models"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass

class Setting(Base):
    __tablename__ = "settings"
    key        = Column(String, primary_key=True)
    value      = Column(Text, nullable=False)
    label      = Column(String, nullable=True)
    category   = Column(String, default="general")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Device(Base):
    __tablename__ = "devices"
    device_id           = Column(String, primary_key=True)
    hostname            = Column(String, nullable=False)
    label               = Column(String, nullable=True)
    platform            = Column(String, nullable=False)
    os_info             = Column(String, default="")
    ip_address          = Column(String, default="")
    mac_address         = Column(String, nullable=True)
    agent_version       = Column(String, default="2.0.0")
    status              = Column(String, default="offline")
    battery_level       = Column(Float,   nullable=True)
    battery_charging    = Column(Boolean, default=False)
    cpu_percent         = Column(Float,   nullable=True)
    ram_percent         = Column(Float,   nullable=True)
    disk_percent        = Column(Float,   nullable=True)
    disk_details        = Column(JSON,    nullable=True)
    disk_scanned_at     = Column(DateTime, nullable=True)
    hardware_info       = Column(JSON,    nullable=True)
    hardware_scanned_at = Column(DateTime, nullable=True)
    group_name          = Column(String, nullable=True)
    tags                = Column(JSON, default=list)
    asset_tag           = Column(String, nullable=True, index=True)
    first_seen          = Column(DateTime, default=datetime.utcnow)
    last_seen           = Column(DateTime, default=datetime.utcnow)
    task_results        = relationship("TaskResult", back_populates="device", lazy="dynamic")
    logs                = relationship("LogEntry",   back_populates="device", lazy="dynamic")
    policy              = relationship("Policy",     back_populates="device", uselist=False)

class AgentVersion(Base):
    __tablename__ = "agent_versions"
    id          = Column(String, primary_key=True)
    platform    = Column(String, nullable=False)
    version     = Column(String, nullable=False)
    filename    = Column(String, nullable=False)
    notes       = Column(Text,   default="")
    auto_update = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

class Task(Base):
    __tablename__ = "tasks"
    id               = Column(String, primary_key=True)
    name             = Column(String, nullable=False)
    description      = Column(Text,   default="")
    script_type      = Column(String, default="powershell")
    script_body      = Column(Text,   nullable=False)
    target_type      = Column(String, default="all")
    target_id        = Column(String, nullable=True)
    target_platform  = Column(String, nullable=True)
    trigger_type     = Column(String, default="now")
    scheduled_at     = Column(DateTime, nullable=True)
    interval_seconds = Column(Integer,  nullable=True)
    cron_expression  = Column(String,   nullable=True)
    event_trigger    = Column(String,   nullable=True)
    status           = Column(String, default="pending")
    cancelled        = Column(Boolean, default=False)
    from_library     = Column(String, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    created_by       = Column(String, default="admin")
    results          = relationship("TaskResult", back_populates="task", lazy="dynamic")

class TaskResult(Base):
    __tablename__ = "task_results"
    id           = Column(String, primary_key=True)
    task_id      = Column(String, ForeignKey("tasks.id"), nullable=False)
    device_id    = Column(String, ForeignKey("devices.device_id"), nullable=False)
    exit_code    = Column(Integer, nullable=True)
    stdout       = Column(Text,    default="")
    stderr       = Column(Text,    default="")
    progress     = Column(Integer, default=0)
    status       = Column(String,  default="running")
    started_at   = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    task         = relationship("Task",   back_populates="results")
    device       = relationship("Device", back_populates="task_results")

class ScriptLibrary(Base):
    __tablename__ = "script_library"
    id          = Column(String, primary_key=True)
    name        = Column(String, nullable=False)
    description = Column(Text,   default="")
    category    = Column(String, default="General")
    platform    = Column(String, default="all")
    script_type = Column(String, default="powershell")
    script_body = Column(Text,   nullable=False)
    tags        = Column(JSON,   default=list)
    run_count   = Column(Integer, default=0)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Policy(Base):
    __tablename__ = "policies"
    id                             = Column(String, primary_key=True)
    name                           = Column(String, default="Default Policy")
    device_id                      = Column(String, ForeignKey("devices.device_id"), nullable=True, unique=True)
    checkin_plugged_seconds        = Column(Integer, default=30)
    checkin_battery_100_80_seconds = Column(Integer, default=60)
    checkin_battery_79_50_seconds  = Column(Integer, default=180)
    checkin_battery_49_20_seconds  = Column(Integer, default=300)
    checkin_battery_19_10_seconds  = Column(Integer, default=600)
    checkin_battery_9_0_seconds    = Column(Integer, default=900)
    low_battery_alert_threshold    = Column(Integer, default=15)
    disk_scan_interval_hours       = Column(Integer, default=168)
    hw_scan_interval_hours         = Column(Integer, default=720)
    created_at                     = Column(DateTime, default=datetime.utcnow)
    updated_at                     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    device                         = relationship("Device", back_populates="policy")

class Asset(Base):
    __tablename__ = "assets"
    id              = Column(String, primary_key=True)
    asset_tag       = Column(String, unique=True, nullable=False, index=True)
    name            = Column(String, nullable=False)
    model           = Column(String, nullable=True)
    owner           = Column(String, nullable=True)
    location        = Column(String, nullable=True)
    category        = Column(String, nullable=True)
    serial_number   = Column(String, nullable=True)
    purchase_date   = Column(DateTime, nullable=True)
    notes           = Column(Text,    default="")
    status          = Column(String, default="active")
    google_form_url = Column(String, nullable=True)
    device_id       = Column(String, ForeignKey("devices.device_id"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class LockdownEvent(Base):
    __tablename__ = "lockdown_events"
    id           = Column(String, primary_key=True)
    action       = Column(String, nullable=False)
    reason       = Column(Text,   default="")
    triggered_by = Column(String, default="admin")
    timestamp    = Column(DateTime, default=datetime.utcnow)

class WolEvent(Base):
    __tablename__ = "wol_events"
    id           = Column(String, primary_key=True)
    device_id    = Column(String, nullable=True)
    target       = Column(String, nullable=False)
    mac          = Column(String, nullable=False)
    triggered_by = Column(String, default="admin")
    timestamp    = Column(DateTime, default=datetime.utcnow)

class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id         = Column(String, primary_key=True)
    name       = Column(String, nullable=False)
    subject    = Column(String, nullable=False)
    body_html  = Column(Text,   nullable=False)
    trigger    = Column(String, nullable=True)
    active     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class LogEntry(Base):
    __tablename__ = "logs"
    id        = Column(String, primary_key=True)
    device_id = Column(String, ForeignKey("devices.device_id"), nullable=True)
    level     = Column(String, default="info")
    message   = Column(Text,   nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    source    = Column(String, default="agent")
    device    = relationship("Device", back_populates="logs")

class AdminUser(Base):
    __tablename__ = "admin_users"
    id              = Column(String, primary_key=True)
    username        = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)
    last_login      = Column(DateTime, nullable=True)
