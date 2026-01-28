"""
Scheduler service module.

Manages periodic content refresh tasks using APScheduler and Dramatiq
for distributed task execution.
"""

import asyncio
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.database import RefreshLogDB, MetadataDB
from app.services.fetcher import fetch_source, SOURCES

logger = get_logger(__name__)

# Initialize scheduler
scheduler = AsyncIOScheduler()

# Initialize Dramatiq with Redis broker
redis_broker = RedisBroker(
    host=settings.REDIS_BROKER_HOST, port=settings.REDIS_BROKER_PORT
)
dramatiq.set_broker(redis_broker)


async def scheduled_refresh_task():
    """
    Execute scheduled content refresh from all sources.

    This is the main background task that:
    1. Creates a refresh log entry
    2. Fetches from all sources concurrently
    3. Saves new articles to database
    4. Updates metadata and log with results

    Called periodically by the scheduler and can also be triggered manually.

    Raises:
        Exception: Any errors are logged but don't stop the scheduler
    """
    logger.info("=" * 70)
    logger.info("Starting scheduled content refresh task")

    async with AsyncSessionLocal() as db:
        refresh_log = None
        try:
            # Create refresh log entry
            refresh_log = RefreshLogDB(
                started_at=datetime.now(timezone.utc),
                status="running",
                sources_attempted=len(SOURCES),
            )
            db.add(refresh_log)
            await db.commit()
            logger.info(f"Created refresh log entry ID: {refresh_log.id}")

            # Fetch from all sources
            tasks = [fetch_source(source, config) for source, config in SOURCES.items()]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            logger.info("Completed fetch from all sources")

            # Process results and save articles
            total_articles = 0
            new_articles = 0
            sources_succeeded = 0
            sources_failed = 0

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Source fetch exception: {result}")
                    sources_failed += 1
                    continue

                if result["success"]:
                    sources_succeeded += 1
                    logger.info(
                        f"{result['source']}: Success - {len(result['articles'])} articles "
                        f"in {result['fetch_time']:.2f}s"
                    )

                    for article_data in result["articles"]:
                        try:
                            # Check if article exists
                            from app.models.database import ArticleDB

                            stmt = select(ArticleDB).where(
                                ArticleDB.id == article_data["id"]
                            )
                            existing = await db.execute(stmt)
                            existing_article = existing.scalar_one_or_none()

                            if not existing_article:
                                new_article = ArticleDB(**article_data)
                                db.add(new_article)
                                new_articles += 1

                            total_articles += 1

                        except Exception as e:
                            logger.error(f"Failed to save article: {e}")

                    await db.commit()
                else:
                    sources_failed += 1
                    logger.warning(
                        f"{result['source']}: Failed - {result.get('error')}"
                    )

            logger.info(
                f"Processed articles: {total_articles} total, {new_articles} new"
            )

            # Update refresh log
            refresh_log.completed_at = datetime.now(timezone.utc)
            refresh_log.total_articles_fetched = total_articles
            refresh_log.new_articles = new_articles
            refresh_log.sources_succeeded = sources_succeeded
            refresh_log.sources_failed = sources_failed
            refresh_log.status = "completed"

            # Update last refresh metadata
            metadata_stmt = select(MetadataDB).where(MetadataDB.key == "last_refresh")
            metadata_result = await db.execute(metadata_stmt)
            metadata = metadata_result.scalar_one_or_none()

            current_time = datetime.now(timezone.utc)
            if metadata:
                metadata.value = current_time.isoformat()
                metadata.update_at = current_time
            else:
                metadata = MetadataDB(
                    key="last_refresh", value=current_time.isoformat()
                )
                db.add(metadata)

            await db.commit()

            logger.info(
                f"Refresh completed successfully: {new_articles} new articles, "
                f"{sources_succeeded}/{len(SOURCES)} sources succeeded"
            )
            logger.info("=" * 70)

        except Exception as e:
            logger.error(f"Refresh task failed: {e}", exc_info=True)

            if refresh_log:
                try:
                    refresh_log.status = "failed"
                    refresh_log.error_message = str(e)
                    refresh_log.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                except Exception as commit_error:
                    logger.error(f"Failed to update error status: {commit_error}")
                    await db.rollback()


@dramatiq.actor
def scheduled_refresh_actor():
    """
    Dramatiq actor wrapper for scheduled refresh task.

    Allows the refresh task to be executed asynchronously
    in a separate worker process via the Redis broker.
    """
    logger.info("Dramatiq actor executing scheduled refresh")
    asyncio.run(scheduled_refresh_task())


def trigger_scheduled_refresh():
    """
    Trigger a scheduled refresh via Dramatiq.

    Sends a message to the Dramatiq broker to execute the refresh task.
    This allows the refresh to run asynchronously without blocking.
    """
    logger.info("Triggering scheduled refresh via Dramatiq")
    scheduled_refresh_actor.send()


def start_scheduler():
    """
    Start the APScheduler and configure periodic refresh job.

    Sets up a recurring job that triggers content refresh at the
    configured interval (default: every 15 minutes).

    This should be called during application startup.
    """
    logger.info("Starting APScheduler")
    scheduler.start()

    scheduler.add_job(
        trigger_scheduled_refresh,
        trigger=IntervalTrigger(minutes=settings.REFRESH_INTERVAL_MINUTES),
        id="periodic_refresh",
        name=f"Periodic content refresh (every {settings.REFRESH_INTERVAL_MINUTES} min)",
        replace_existing=True,
    )

    logger.info(
        f"Scheduled periodic refresh: every {settings.REFRESH_INTERVAL_MINUTES} minutes"
    )


def stop_scheduler():
    """
    Stop the APScheduler gracefully.

    Shuts down the scheduler and waits for any running jobs to complete.
    This should be called during application shutdown.
    """
    logger.info("Stopping APScheduler")
    scheduler.shutdown(wait=True)
    logger.info("Scheduler stopped")
