"""Database configuration for the PMO system."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# SQLAlchemy Base — all models inherit from this
Base = declarative_base()

# Database engine — explicit pool tuning for production scalability:
# pool_pre_ping recycles connections dropped by DB restarts/failovers
# (prevents transient 500s); pool_size + max_overflow sized for a
# multi-worker deployment.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
