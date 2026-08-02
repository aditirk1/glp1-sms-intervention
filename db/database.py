"""SQLAlchemy engine, session factory and declarative base for GoalPost¹."""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./GoalPost¹.db")

# check_same_thread is a SQLite-only flag; FastAPI serves requests from a
# thread pool and would otherwise refuse to reuse the connection.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create every table declared on Base. Safe to call repeatedly."""
    from db import models  # noqa: F401  (import registers the mappers on Base)

    Base.metadata.create_all(bind=engine)
