"""
Database initialization and connection management
Uses SQLite locally, easily upgradeable to PostgreSQL
"""
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine
import os
from pathlib import Path

# Create data directory if it doesn't exist
DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DATA_DIR}/job_hunter.db"
)

# Create engine with appropriate settings
if DATABASE_URL.startswith("sqlite"):
    # SQLite-specific configuration
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    # PostgreSQL or other databases
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        future=True,
    )


def init_db():
    """Initialize database tables - MUST import models first!"""
    # Import all models to register them with SQLModel
    from app.models import (
        User, Resume, Job, Application, 
        CommunicationLog, SavedSearchProfile,
        EmailRecord, STARStory, JobCache
    )
    
    SQLModel.metadata.create_all(engine)
    print("✅ Database initialized successfully")


def get_session():
    """Get database session for use in API endpoints"""
    with Session(engine) as session:
        yield session


async def async_get_session():
    """Async version for async endpoints"""
    with Session(engine) as session:
        yield session


# Auto-initialize on import
if not os.path.exists(f"{DATA_DIR}/jobhunter_pa.db"):
    init_db()
