"""
Main FastAPI application module.

Initializes and configures the FastAPI application with middleware,
routes, database, and background tasks.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.db.session import init_db, AsyncSessionLocal
from app.models.database import ArticleDB, MetadataDB
from app.services.fetcher import fetch_all_sources
from app.services.scheduler import start_scheduler, stop_scheduler
from app.api.routes import router

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Handles startup and shutdown events:
    - Startup: Initialize database, check for initial data, starts scheduler
    - Shutdown: Stop scheduler gracefully

    Args:
        app: FastAPI application instance

    Yields:
        None: Control back to FastAPI
    """
    # Startup
    logger.info("=" * 70)
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info("=" * 70)

    # Initialize database
    await init_db()

    # Check if initial data fetch is needed
    async with AsyncSessionLocal() as db:
        try:
            # Count existing articles
            result = await db.execute(select(ArticleDB))
            article_count = len(result.scalars().all())

            if article_count == 0:
                logger.info("Database is empty, performing initial fetch...")
                await fetch_all_sources(db)
                logger.info("Initial fetch completed")
            else:
                logger.info(f"Database contains {article_count} articles")

                # Check if refresh is needed (> 5 minutes since last refresh)
                result = await db.execute(
                    select(MetadataDB).where(MetadataDB.key == "last_refresh")
                )
                metadata = result.scalar_one_or_none()

                if metadata:
                    last_refresh = datetime.fromisoformat(metadata.value)
                    time_since_refresh = datetime.now(timezone.utc) - last_refresh

                    if time_since_refresh > timedelta(minutes=5):
                        logger.info(
                            f"Last refresh was {time_since_refresh.seconds // 60} minutes ago, "
                            f"performing refresh..."
                        )
                        await fetch_all_sources(db)
                    else:
                        logger.info(
                            f"Last refresh was {time_since_refresh.seconds // 60} minutes ago, "
                            f"skipping initial refresh"
                        )
                else:
                    logger.warning(
                        "No last_refresh metadata found, performing fetch..."
                    )
                    await fetch_all_sources(db)

        except Exception as e:
            logger.error(f"Error during startup data check: {e}", exc_info=True)

    # Start scheduler
    start_scheduler()
    logger.info("Application startup complete")
    logger.info("=" * 70)

    yield

    # Shutdown
    logger.info("=" * 70)
    logger.info("Shutting down application...")
    stop_scheduler()
    logger.info("Application shutdown complete")
    logger.info("=" * 70)


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-source content aggregation",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

logger.info(f"FastAPI application configured: {settings.APP_NAME}")
print("Settings:", settings)
