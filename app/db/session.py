"""
Database connection and session management module.

Handles SQLAlchemy async engine creation, session management,
and database initialization.
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings
from app.core.logging import get_logger
from app.models.database import Base

logger = get_logger(__name__)

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    future=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    """
    Initialize database tables.
    
    Creates all tables defined in the Base metadata if they don't exist.
    This function is called during application startup.
    
    Raises:
        Exception: If database initialization fails
    """
    logger.info("Initializing database...")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


async def get_db():
    """
    Dependency function to get database session.
    
    Yields an async database session for use in FastAPI endpoints.
    The session is automatically closed after use.
    
    Yields:
        AsyncSession: Database session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
