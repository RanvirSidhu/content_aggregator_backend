"""
API routes module.

Defines all FastAPI endpoints for article retrieval, refresh management,
and health checks.
"""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.database import ArticleDB, MetadataDB
from app.models.schemas import SourceType
from app.services.scheduler import scheduler, trigger_scheduled_refresh
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/")
async def health_check():
    """
    API health check endpoint.

    Returns basic information about the API status, version, and
    database connectivity.

    Returns:
        HealthCheckResponse: API health status information
    """
    logger.debug("Health check endpoint called")
    return {
        "message": settings.APP_NAME,
        "status": "healthy",
        "version": settings.APP_VERSION,
        "database": "Connected",
    }


@router.get("/api/articles", tags=["Articles"])
async def get_articles(
    source: Optional[SourceType] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregated articles from database.

    Retrieves articles with optional filtering by source, pagination,
    and returns metadata about unique sources and last update time.

    Args:
        source: Filter by specific source (optional)
        db: Database session (injected)

    Returns:
        ArticlesListResponse: Articles list with metadata

    Example:
        GET /api/articles?source=Dev.to&limit=10
    """
    logger.info(f"Fetching articles - source: {source}")

    try:
        # Build query
        stmt = select(ArticleDB)

        if source:
            stmt = stmt.where(ArticleDB.source == source.value)
            logger.debug(f"Filtering by source: {source.value}")

        stmt = stmt.order_by(ArticleDB.publish_date.desc())

        # Execute query
        result = await db.execute(stmt)
        articles = result.scalars().all()

        logger.info(f"Retrieved {len(articles)} articles from database")

        # Get unique sources
        unique_sources = list({article.source for article in articles})
        logger.debug(f"Unique sources in results: {unique_sources}")

        # Get last update time
        metadata_stmt = select(MetadataDB.update_at).where(
            MetadataDB.key == "last_refresh"
        )
        metadata_result = await db.execute(metadata_stmt)
        last_update = metadata_result.scalar_one_or_none()

        logger.debug(f"Last update time: {last_update}")

        return {
            "articles": articles,
            "unique_sources": unique_sources,
            "last_update": last_update,
        }

    except Exception as e:
        logger.error(f"Failed to fetch articles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve articles")


@router.post("/api/refresh/trigger", tags=["Refresh"])
async def trigger_manual_refresh():
    """
    Manually trigger a content refresh.

    Schedules an immediate one-time refresh task that runs in the background.
    Does not block the response - refresh happens asynchronously.

    Returns:
        RefreshTriggerResponse: Confirmation that refresh was scheduled

    Example:
        POST /api/refresh/trigger
    """
    logger.info("Manual refresh triggered via API")

    try:
        # Schedule immediate one-time job
        job_id = f"manual_refresh_{datetime.now(timezone.utc).timestamp()}"
        scheduler.add_job(
            trigger_scheduled_refresh,
            trigger="date",  # Run once immediately
            id=job_id,
            replace_existing=False,
        )

        logger.info(f"Manual refresh scheduled with job ID: {job_id}")

        return {"message": "Manual refresh triggered", "status": "scheduled"}

    except Exception as e:
        logger.error(f"Failed to trigger manual refresh: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to trigger refresh")


@router.post("/api/refresh/disable", tags=["Refresh"])
async def disable_refresh_job():
    """
    Disable the periodic refresh job.

    Pauses the automatic content refresh without removing the job.
    Can be re-enabled later without reconfiguration.

    Returns:
        JobStatusResponse: Job status after disabling

    Raises:
        HTTPException: If the job doesn't exist

    Example:
        POST /api/refresh/disable
    """
    logger.info("Request to disable periodic refresh job")

    job = scheduler.get_job("periodic_refresh")
    if not job:
        logger.error("Periodic refresh job not found")
        raise HTTPException(status_code=404, detail="Scheduler job not found")

    try:
        scheduler.pause_job("periodic_refresh")
        logger.info("Periodic refresh job disabled")

        return {
            "status": "disabled",
            "job_id": "periodic_refresh",
            "next_run": None,
        }

    except Exception as e:
        logger.error(f"Failed to disable refresh job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to disable job")


@router.post("/api/refresh/enable", tags=["Refresh"])
async def enable_refresh_job():
    """
    Enable the periodic refresh job.

    Resumes the automatic content refresh if it was previously disabled.

    Returns:
        JobStatusResponse: Job status after enabling

    Raises:
        HTTPException: If the job doesn't exist

    Example:
        POST /api/refresh/enable
    """
    logger.info("Request to enable periodic refresh job")

    job = scheduler.get_job("periodic_refresh")
    if not job:
        logger.error("Periodic refresh job not found")
        raise HTTPException(status_code=404, detail="Scheduler job not found")

    try:
        scheduler.resume_job("periodic_refresh")
        logger.info("Periodic refresh job enabled")

        return {
            "status": "enabled",
            "job_id": "periodic_refresh",
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        }

    except Exception as e:
        logger.error(f"Failed to enable refresh job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to enable job")
