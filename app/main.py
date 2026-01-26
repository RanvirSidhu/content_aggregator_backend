from enum import Enum
from datetime import datetime, timedelta, timezone, UTC
from typing import Any, Dict, List, Optional
import asyncio
import httpx
import hashlib
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from fastapi import FastAPI, Depends
from sqlalchemy import String, Integer, DateTime, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from contextlib import asynccontextmanager

DATABASE_URL = "postgresql+asyncpg://{user}:{password}@localhost/content_aggregator"


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


engine = create_async_engine(
    DATABASE_URL,
    # echo=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- STARTUP ----
    await init_db()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ArticleDB))
        article_count = len(result.scalars().all())

        if article_count == 0:
            print("Database is empty, fetching initial articles...")
            await fetchAllSource(db)

        else:
            print(f"Database contains {article_count} articles")

            result = await db.execute(
                select(MetadataDB).where(MetadataDB.key == "last_refresh")
            )
            metadata = result.scalar_one_or_none()

            if metadata:
                last_refresh = datetime.fromisoformat(metadata.value)
                if datetime.now(timezone.utc) - last_refresh > timedelta(minutes=5):
                    print("Last refresh was > 5 minutes ago, refreshing...")
                    await fetchAllSource(db)

    yield
    # ---- SHUTDOWN ----
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
    },
    SourceType.REDDIT: {
        "url": "https://www.reddit.com/r/programming.json",
        "category_default": "Programming",
    },
    SourceType.LOBSTERS: {
        "url": "https://lobste.rs/active.json",
        "category_default": "Tech",
    },
}


def generateID(id: str, source: SourceType) -> str:
    """Generate unique ID from URL and source"""
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
        print(f"Error normalizing article from {src}: {e}")
        return None


async def fetchSource(source: SourceType, url: str) -> List[Dict]:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            res.raise_for_status()

        if source == SourceType.REDDIT:
            response = res.json()["data"]["children"]
        else:
            response = res.json()

        articles = []
        for entry in response:
            articles.append(normalizeArticle(source, entry))

        return articles
    except Exception as e:
        print("HTTP error occured: ", e)
        return []


async def fetchAllSource(db: AsyncSession):
    tasks = [fetchSource(source, config["url"]) for source, config in SOURCES.items()]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)

    saved_count = 0
    for article_data in all_articles:
        stmt = select(ArticleDB).where(ArticleDB.id == article_data["id"])
        result = await db.execute(stmt)
        result = result.first()

        if result:
            pass
        else:
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

    if len(articles) == 0:
        await fetchAllSource(db)

    unique_sources = list({a.source for a in articles})

    return {
        "articles": articles,
        "unique_sources": unique_sources,
    }
