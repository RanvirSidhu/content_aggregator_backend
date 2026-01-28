"""
Database models module.

Defines all SQLAlchemy ORM models for the application including
articles, metadata, and refresh logs.
"""

from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class ArticleDB(Base):
    """
    Article database model.

    Stores aggregated articles from multiple sources with metadata
    including title, author, publication date, and source information.

    Attributes:
        id: Unique MD5 hash identifier (source + source_id)
        title: Article title (max 500 chars)
        author: Article author name (optional)
        url: Full URL to the article (unique)
        source_id: Original ID from the source platform
        publish_date: Article publication timestamp
        source: Source platform name (Dev.to, Reddit, Lobsters)
    """

    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
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

    def as_dict(self):
        return {c.name: str(getattr(self, c.name)) for c in self.__table__.columns}


class MetadataDB(Base):
    """
    Metadata database model.

    Stores key-value pairs for application metadata such as
    last refresh timestamp and other system state information.

    Attributes:
        id: Auto-incrementing primary key
        key: Metadata key (unique)
        value: Metadata value
        update_at: Last update timestamp
    """

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
    """
    Refresh log database model.

    Tracks each content refresh cycle with detailed statistics
    including success/failure counts and timing information.

    Attributes:
        id: Auto-incrementing primary key
        started_at: Refresh cycle start timestamp
        completed_at: Refresh cycle completion timestamp
        total_articles_fetched: Total number of articles fetched
        new_articles: Number of new articles added to database
        sources_attempted: Number of sources attempted
        sources_succeeded: Number of sources that succeeded
        sources_failed: Number of sources that failed
        status: Refresh status (running, completed, failed)
        error_message: Error details if refresh failed
    """

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
    status: Mapped[str] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
