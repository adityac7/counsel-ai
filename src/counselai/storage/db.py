"""Database engine, session factory, and base model."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from counselai.settings import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Session:  # type: ignore[misc]
    """Yield a database session, closing it after use.

    Usage as a FastAPI dependency::

        @router.get("/")
        def index(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db  # type: ignore[misc]
    finally:
        db.close()
