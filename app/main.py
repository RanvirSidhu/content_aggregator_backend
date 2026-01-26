from enum import Enum
from datetime import datetime, timedelta, timezone, UTC
from typing import Any, Dict, List, Optional
import asyncio
import httpx
import hashlib
import logging
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import String, Integer, DateTime, select, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.job import Job

import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")


class Base(DeclarativeBase):
    pass


class ArticleDB(Base):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # md5-like hash

    title: Mapped[str] = mapped_column(String(500), nullable=False)

    author: Mapped[str | None] = mapped_column(String(100), nullable=True)

    url: Mapped[str] = mapped_column(
        String(1000), nullable=False, unique=True, index=True
    )

    source_id: Mapped[str] = mapped_column(String, nullable=False)

    publish_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    source: Mapped[str] = mapped_column(String(50), index=True, nullable=False)


class MetadataDB(Base):
    __tablename__ = "metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(String(100))
    update_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )


class RefreshLogDB(Base):
    """Log each refresh cycle"""

    __tablename__ = "refresh_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_articles_fetched: Mapped[int] = mapped_column(Integer, default=0)
    new_articles: Mapped[int] = mapped_column(Integer, default=0)
    sources_attempted: Mapped[int] = mapped_column(Integer, default=0)
    sources_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    sources_failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20))  # 'running', 'completed', 'failed'
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("Starting up application...")
    await init_db()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ArticleDB))
        article_count = len(result.scalars().all())

        if article_count == 0:
            logger.info("Database is empty, fetching initial articles...")
            await fetchAllSource(db)

        else:
            logger.info(f"Database contains {article_count} articles")

            result = await db.execute(
                select(MetadataDB).where(MetadataDB.key == "last_refresh")
            )
            metadata = result.scalar_one_or_none()

            if metadata:
                last_refresh = datetime.fromisoformat(metadata.value)
                if datetime.now(timezone.utc) - last_refresh > timedelta(minutes=5):
                    logger.info("Last refresh was > 5 minutes ago, refreshing...")
                    await fetchAllSource(db)

    scheduler.start()
    logger.info("Scheduler started")
    scheduler.add_job(
        scheduled_refresh,
        trigger=IntervalTrigger(minutes=15),
        id="periodic_refresh",
        name="Periodic content refresh (every 15 min)",
        replace_existing=True,
    )
    logger.info("Scheduled refresh job: every 15 minutes")
    yield

    logger.info("Shutting down scheduler...")
    scheduler.shutdown()
    print("Shutdown complete")


app = FastAPI(
    title="Content Aggregator API",
    description="Multi-source content aggregation with database persistence",
    version="2.0.0",
    lifespan=lifespan,
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SourceType(str, Enum):
    DEVTO = "Dev.to"
    REDDIT = "Reddit"
    LOBSTERS = "Lobsters"


SOURCES = {
    SourceType.DEVTO: {
        "url": "https://dev.to/api/articles",
        "category_default": "Development",
        "timeout": 10,
    },
    SourceType.REDDIT: {
        "url": "https://www.reddit.com/r/programming.json",
        "category_default": "Programming",
        "timeout": 10,
    },
    SourceType.LOBSTERS: {
        "url": "https://lobste.rs/active.json",
        "category_default": "Tech",
        "timeout": 10,
    },
}


def generateID(id: str, source: SourceType) -> str:
    combined = f"{source.value}-{id}"
    return hashlib.md5(combined.encode()).hexdigest()


def generateURL(url: str, source: SourceType) -> str:
    if source == SourceType.REDDIT:
        return f"https://reddit.com{url}"

    return url


def parseDate(date_str: Any, src: SourceType) -> datetime:
    if isinstance(date_str, datetime):
        return date_str

    if src == SourceType.REDDIT:
        return datetime.fromtimestamp(date_str, tz=UTC)
    elif src == SourceType.DEVTO:
        return datetime.fromisoformat(date_str[:-1] + "+00:00")
    else:
        return datetime.fromisoformat(date_str)


def normalizeArticle(src: SourceType, entry: Any) -> Optional[Dict]:
    try:
        if src == SourceType.REDDIT:
            entry = entry.get("data")

        id = entry.get("id") or entry.get("short_id")
        if not isinstance(id, str):
            id = f"{id}"

        title = entry.get("title")

        author = (
            entry.get("author")
            or entry.get("submitter_user")
            or entry.get("user").get("username")
        )

        if src == SourceType.REDDIT:
            url = entry.get("permalink")
        else:
            url = entry.get("url") or entry.get("comments_url")

        publish_date = (
            entry.get("created") or entry.get("created_at") or entry.get("published_at")
        )

        source = src.value

        return {
            "id": generateID(id, src),
            "title": title,
            "author": author,
            "url": generateURL(url, src),
            "source_id": id,
            "publish_date": parseDate(publish_date, src),
            "source": source,
        }

    except Exception as e:
        print(f"Error normalizing article from {src}\nentry:{entry}: {e}")
        return None


async def fetchSource(source: SourceType, config: Dict) -> Dict[str, Any]:
    result = {
        "source": source.value,
        "success": False,
        "articles": [],
        "error": None,
        "fetch_time": None,
    }

    start_time = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient(timeout=config.get("timeout", 10)) as client:
            res = await client.get(config["url"])
            res.raise_for_status()

        if source == SourceType.REDDIT:
            response = res.json()["data"]["children"]
        else:
            response = res.json()

        articles = []
        for entry in response:
            articles.append(normalizeArticle(source, entry))

        result["success"] = True
        result["articles"] = articles
        result["fetch_time"] = (datetime.now(timezone.utc) - start_time).total_seconds()
    except httpx.TimeoutException as e:
        result["error"] = f"Timeout after {config.get('timeout')}s"
        logger.error(f"✗ {source.value}: Timeout - {e}")

    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
        logger.error(f"✗ {source.value}: HTTP error - {e}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"✗ {source.value}: Unexpected error - {e}")

    return result


async def fetchAllSource(db: AsyncSession):
    tasks = [fetchSource(source, config) for source, config in SOURCES.items()]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Task exception: {result}")
            continue

        if result["success"]:
            articles = result.get("articles", [])
            all_articles.extend(articles)

    saved_count = 0
    for article_data in all_articles:
        stmt = select(ArticleDB).where(ArticleDB.id == article_data["id"])
        result = await db.execute(stmt)
        result = result.scalar_one_or_none()

        if not result:
            new_article = ArticleDB(**article_data)
            db.add(new_article)
            saved_count += 1

    await db.commit()

    metadata_stmt = select(MetadataDB).where(MetadataDB.key == "last_refresh")
    result = await db.execute(metadata_stmt)
    last_refresh = result.scalar_one_or_none()

    if last_refresh:
        last_refresh.value = datetime.now(timezone.utc).isoformat()
        last_refresh.update_at = datetime.now(timezone.utc)
    else:
        last_refresh = MetadataDB(
            key="last_refresh", value=datetime.now(timezone.utc).isoformat()
        )
        db.add(last_refresh)

    await db.commit()

    print(f"Fetched {len(all_articles)} articles, saved {saved_count} new articles")


async def scheduled_refresh():
    """
    Background refresh function called by APScheduler
    Runs independently of user requests every 15 minutes
    """
    async with AsyncSessionLocal() as db:
        try:
            logger.info("=" * 60)
            logger.info("Starting scheduled content refresh...")

            refresh_log = RefreshLogDB(
                started_at=datetime.now(timezone.utc),
                status="running",
                sources_attempted=len(SOURCES),
            )
            db.add(refresh_log)
            await db.commit()
            tasks = [fetchSource(source, config) for source, config in SOURCES.items()]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_articles = 0
            new_articles = 0
            sources_succeeded = 0
            sources_failed = 0

            for result in results:
                if result["success"]:
                    sources_succeeded += 1

                    for article_data in result["articles"]:
                        stmt = select(ArticleDB).where(
                            ArticleDB.id == article_data["id"]
                        )
                        existing = await db.execute(stmt)
                        existing = existing.scalar_one_or_none()

                        if not existing:
                            new_article = ArticleDB(**article_data)
                            db.add(new_article)
                            new_articles += 1

                        total_articles += 1

                    await db.commit()
                else:
                    sources_failed += 1

            refresh_log.completed_at = datetime.now(timezone.utc)
            refresh_log.total_articles_fetched = total_articles
            refresh_log.new_articles = new_articles
            refresh_log.sources_succeeded = sources_succeeded
            refresh_log.sources_failed = sources_failed
            refresh_log.status = "completed"

            metadata_stmt = select(MetadataDB).where(MetadataDB.key == "last_refresh")
            metadata_result = await db.execute(metadata_stmt)
            metadata = metadata_result.scalar_one_or_none()

            if metadata:
                metadata.value = datetime.now(timezone.utc).isoformat()
                metadata.update_at = datetime.now(timezone.utc)
            else:
                metadata = MetadataDB(
                    key="last_refresh", value=datetime.now(timezone.utc).isoformat()
                )
                db.add(metadata)

            await db.commit()

            logger.info(
                f"Refresh completed: {new_articles} new articles, {sources_succeeded}/{len(SOURCES)} sources succeeded"
            )
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            refresh_log.status = "failed"
            refresh_log.error_message = str(e)
            refresh_log.completed_at = datetime.now(timezone.utc)
            await db.commit()


@app.get("/")
async def root():
    """API health check"""
    return {
        "message": "Content Aggregator API with Database",
        "status": "healthy",
        "version": "2.0.0",
        "database": "Connected",
    }


@app.get("/api/articles", tags=["Articles"])
async def get_articles(
    source: Optional[SourceType] = None,
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregated articles from database

    - **source**: Filter by specific source (optional)
    """
    stmt = select(ArticleDB)

    if source:
        stmt = stmt.where(ArticleDB.source == source.value)

    stmt = stmt.order_by(ArticleDB.publish_date.desc())
    result = await db.execute(stmt)
    articles = result.scalars().all()

    unique_sources = list({a.source for a in articles})

    metdata_stmt = select(MetadataDB.update_at).where(MetadataDB.key == "last_refresh")
    result = await db.execute(metdata_stmt)
    last_update = result.scalar_one_or_none()
    print("Last Update: ", last_update)
    return {
        "articles": articles,
        "unique_sources": unique_sources,
        "last_update": last_update,
    }


@app.post("/api/refresh/trigger", tags=["Refresh"])
async def trigger_manual_refresh():
    """Manually trigger a refresh (still runs in background)"""
    scheduler.add_job(
        scheduled_refresh,
        trigger="date",  # Run once immediately
        id=f"manual_refresh_{datetime.now(timezone.utc).timestamp()}",
        replace_existing=False,
    )
    print("Trigger Manual refresh.")
    return {"message": "Manual refresh triggered", "status": "scheduled"}


@app.post("/api/refresh/disable")
async def disable_refresh_job():
    job = scheduler.get_job("periodic_refresh")
    if not job:
        raise HTTPException(status_code=404, detail="Scheduler job not found")

    print("Request received to disable backend job")
    scheduler.pause_job("periodic_refresh")

    return {
        "status": "disabled",
        "job_id": "periodic_refresh",
        "next_run": None,
    }


@app.post("/api/refresh/enable")
async def enable_refresh_job():
    job = scheduler.get_job("periodic_refresh")
    if not job:
        raise HTTPException(status_code=404, detail="Scheduler job not found")

    print("Request received to enable backend job")
    scheduler.resume_job("periodic_refresh")

    return {
        "status": "enabled",
        "job_id": "periodic_refresh",
        "next_run": str(job.next_run_time),
    }
