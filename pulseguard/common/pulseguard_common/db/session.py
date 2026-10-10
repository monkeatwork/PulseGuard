"""Database session factory shared by every service that reads/writes
Postgres (ingestion, detection_engine, mitigation -- their APIs and their
background workers). Connection parameters come from the env vars
docker-compose.yml sets (POSTGRES_HOST/PORT/USER/PASSWORD/DB), or a full
DATABASE_URL when given.
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    user = os.environ.get("POSTGRES_USER", "pulseguard")
    password = os.environ.get("POSTGRES_PASSWORD", "pulseguard_dev_password")
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "pulseguard")
    return f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db}"


_engine = None
_SessionLocal = None


def get_session_factory() -> sessionmaker:
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = create_engine(build_database_url(), pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal


def get_db() -> Session:
    """FastAPI dependency: yields a session, closes it after the request."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
