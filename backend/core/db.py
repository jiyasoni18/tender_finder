"""
Database layer — SQLAlchemy with PostgreSQL (production) or SQLite (local dev).

Set DATABASE_URL in your .env to switch between them:
  - Local dev:   (leave unset — auto-uses SQLite)
  - Production:  DATABASE_URL=postgresql://user:pass@host:5432/dbname

Tables:
  tenders  — one row per tender, tracks full lifecycle
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Float, String, Text, JSON, create_engine, text
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.logging_setup import get_logger

log = get_logger("db")

# ── Engine setup ──────────────────────────────────────────────────────────────
_DATABASE_URL = os.getenv("DATABASE_URL", "")

if not _DATABASE_URL:
    # Local development: use SQLite file next to this module
    _db_file = Path(__file__).resolve().parent.parent / ".state" / "tenders.db"
    _db_file.parent.mkdir(parents=True, exist_ok=True)
    _DATABASE_URL = f"sqlite:///{_db_file}"
    log.info("No DATABASE_URL set — using SQLite at %s", _db_file)

# Render sometimes gives postgres:// but SQLAlchemy needs postgresql://
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

_connect_args = {"check_same_thread": False} if _DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    _DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ── ORM Model ─────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class TenderRow(Base):
    __tablename__ = "tenders"

    id           = Column(String, primary_key=True)          # Tender ID
    source       = Column(String, nullable=True)             # IREPS / TenderDetail
    status       = Column(String, default="seen")            # seen | passed | rejected | completed
    value        = Column(Float,  nullable=True)             # ECV in rupees
    closing_date = Column(String, nullable=True)             # ISO date string
    detail_url   = Column(Text,   nullable=True)             # original URL
    summary      = Column(Text,   nullable=True)             # 2-line Gemini summary
    reject_reason= Column(Text,   nullable=True)
    pdf_path     = Column(Text,   nullable=True)             # local path to main PDF
    files        = Column(JSON,   nullable=True)             # list of file paths (relative)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    Base.metadata.create_all(engine)
    log.info("Database tables ready (%s)", _DATABASE_URL.split("@")[-1] if "@" in _DATABASE_URL else _DATABASE_URL)


def get_session() -> Session:
    return SessionLocal()
