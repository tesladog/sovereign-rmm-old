"""SOVEREIGN RMM — Database Models"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"
    device_id        = Column(String, primary_key=True)
    hostname         = Column(String, nullable=False)
    platform         = Column(String, nullable=False)
    os_info          = Column(String, default="")
    ip_address       = Column(String, default="")
    agent_version    = Column(String, default="1.0.0")
    status           = Column(String, default="offline")
    battery_level    = Column(Float,   nullable=True)
    battery_charging = Column(Boolean, default=False)
    cpu_percent      = Column(Float,   nullable=True)
    ram_percent      = Column(Float,   nullable=True)
    disk_percent     = Column(Float,   nullable=True)
    first_seen       = Column(DateTime, default=datetime.utcnow)
    last_seen        = Column(DateTime, default=datetime.utcnow)
    label            = Column(String, nullable=True)
    group_name       = Column(String, nullable=True)
    tags             = Column(JSON, default=list)
    task_results     = relationship("TaskResult", back_populates="device", lazy="dynamic")
    logs             = relationship("LogEntry",   back_populates="device", lazy="dynamic")
    policy           = relationship("Policy",     back_populates="device", uselist=False)


class Task(Base):
    __tablename__ = "tasks"
    id              = Column(String, primary_key=True)
    name            = Column(String, nullable=False)
    description     = Column(Text, default="")
    script_type     = Column(String, default="powershell")
    script_body     = Column(Text, nullable=False)
    target_type     = Column(String, default="device")
    target_id       = Column(String, nullable=True)
    run_now         = Column(Boolean, default=False)
    scheduled_at    = Column(DateTime, nullable=True)
    recurring       = Column(Boolean, default=False)
    cron_expression = Column(String, nullable=True)
    status          = Column(String, default="pending")
    created_at      = Column(DateTime, default=datetime.utcnow)
    created_by      = Column(String, default="admin")
    results         = relationship("TaskResult", back_populates="task", lazy="dynamic")


class TaskResult(Base):
    __tablename__ = "task_results"
    id           = Column(String, primary_key=True)
    task_id      = Column(String, ForeignKey("tasks.id"), nullable=False)
    device_id    = Column(String, ForeignKey("devices.device_id"), nullable=False)
    exit_code    = Column(Integer, nullable=True)
    stdout       = Column(Text, default="")
    stderr       = Column(Text, default="")
    started_at   = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    task         = relationship("Task",   back_populates="results")
    device       = relationship("Device", back_populates="task_results")


class Policy(Base):
    __tablename__ = "policies"
    id                              = Column(String, primary_key=True)
    name                            = Column(String, default="Default Policy")
    device_id                       = Column(String, ForeignKey("devices.device_id"), nullable=True, unique=True)
    checkin_plugged_seconds         = Column(Integer, default=30)
    checkin_battery_100_80_seconds  = Column(Integer, default=60)
    checkin_battery_79_50_seconds   = Column(Integer, default=180)
    checkin_battery_49_20_seconds   = Column(Integer, default=300)
    checkin_battery_19_10_seconds   = Column(Integer, default=600)
    checkin_battery_9_0_seconds     = Column(Integer, default=900)
    low_battery_alert_threshold     = Column(Integer, default=15)
    created_at                      = Column(DateTime, default=datetime.utcnow)
    updated_at                      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    device                          = relationship("Device", back_populates="policy")


class LogEntry(Base):
    __tablename__ = "logs"
    id        = Column(String, primary_key=True)
    device_id = Column(String, ForeignKey("devices.device_id"), nullable=True)
    level     = Column(String, default="info")
    message   = Column(Text, nullable=False)
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
