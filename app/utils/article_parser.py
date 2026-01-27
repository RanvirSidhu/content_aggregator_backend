"""
Article parsing and normalization utilities.

Provides functions to parse dates, generate IDs, normalize URLs,
and transform articles from different sources into a unified format.
"""

import hashlib
from datetime import datetime, UTC
from typing import Any, Optional, Dict
from app.models.schemas import SourceType
from app.core.logging import get_logger

logger = get_logger(__name__)


def generate_article_id(source_id: str, source: SourceType) -> str:
    """
    Generate a unique MD5 hash identifier for an article.

    Combines source name and source ID to create a unique identifier
    that remains consistent across fetches.

    Args:
        source_id: Original article ID from the source platform
        source: Source platform type

    Returns:
        str: 32-character MD5 hash

    Example:
        >>> generate_article_id("12345", SourceType.DEVTO)
        'a1b2c3d4e5f6...'
    """
    combined = f"{source.value}-{source_id}"
    hash_id = hashlib.md5(combined.encode()).hexdigest()
    logger.debug(f"Generated ID {hash_id} for {source.value}:{source_id}")
    return hash_id


def generate_full_url(url: str, source: SourceType) -> str:
    """
    Generate the full URL for an article.

    Some sources (like Reddit) provide relative URLs that need
    to be converted to absolute URLs.

    Args:
        url: Original URL from source (may be relative)
        source: Source platform type

    Returns:
        str: Full absolute URL

    Example:
        >>> generate_full_url("/r/programming/comments/xyz", SourceType.REDDIT)
        'https://reddit.com/r/programming/comments/xyz'
    """
    if source == SourceType.REDDIT:
        full_url = f"https://reddit.com{url}"
        logger.debug(f"Converted Reddit URL: {url} -> {full_url}")
        return full_url

    return url


def parse_publish_date(date_str: Any, source: SourceType) -> datetime:
    """
    Parse publication date from different source formats.

    Each source provides dates in different formats:
    - Reddit: Unix timestamp
    - Dev.to: ISO format string with 'Z' suffix
    - Lobsters: Standard ISO format

    Args:
        date_str: Date in source-specific format
        source: Source platform type

    Returns:
        datetime: Timezone-aware datetime object (UTC)

    Raises:
        ValueError: If date cannot be parsed

    Example:
        >>> parse_publish_date(1704067200, SourceType.REDDIT)
        datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    """
    # If already a datetime, return as-is
    if isinstance(date_str, datetime):
        return date_str

    try:
        if source == SourceType.REDDIT:
            # Unix timestamp
            parsed_date = datetime.fromtimestamp(date_str, tz=UTC)
        elif source == SourceType.DEVTO:
            # ISO format with 'Z' suffix: "2024-01-01T12:00:00Z"
            parsed_date = datetime.fromisoformat(date_str[:-1] + "+00:00")
        else:
            # Standard ISO format
            parsed_date = datetime.fromisoformat(date_str)

        logger.debug(f"Parsed date from {source.value}: {date_str} -> {parsed_date}")
        return parsed_date

    except Exception as e:
        logger.error(f"Failed to parse date '{date_str}' from {source.value}: {e}")
        raise ValueError(f"Invalid date format for {source.value}: {date_str}")


def normalize_article(source: SourceType, entry: Any) -> Optional[Dict]:
    """
    Normalize an article from source-specific format to unified format.

    Transforms articles from different platforms into a consistent structure
    with standardized field names and formats.

    Args:
        source: Source platform type
        entry: Raw article data from source API

    Returns:
        dict: Normalized article data with keys:
            - id: Unique identifier
            - title: Article title
            - author: Author name
            - url: Full article URL
            - source_id: Original source ID
            - publish_date: Publication datetime
            - source: Source platform name
        None: If article cannot be normalized

    Example:
        >>> normalize_article(SourceType.DEVTO, {"id": 123, "title": "Test"})
        {"id": "abc123...", "title": "Test", ...}
    """
    try:
        # Reddit wraps data in "data" object
        if source == SourceType.REDDIT:
            entry = entry.get("data")

        # Extract source ID
        source_id = entry.get("id") or entry.get("short_id")
        if not isinstance(source_id, str):
            source_id = str(source_id)

        # Extract title
        title = entry.get("title")
        if not title:
            logger.warning(f"Article from {source.value} missing title, skipping")
            return None

        # Extract author (different field names per source)
        author = (
            entry.get("author")
            or entry.get("submitter_user")
            or (entry.get("user", {}).get("username") if entry.get("user") else None)
        )

        # Extract and normalize URL
        if source == SourceType.REDDIT:
            raw_url = entry.get("permalink")
        else:
            raw_url = entry.get("url") or entry.get("comments_url")

        if not raw_url:
            logger.warning(f"Article from {source.value} missing URL, skipping")
            return None

        url = generate_full_url(raw_url, source)

        # Extract and parse publish date
        if source == SourceType.REDDIT:
            date_field = entry.get("created_utc")
        elif source == SourceType.DEVTO:
            date_field = entry.get("published_at")
        else:
            date_field = entry.get("created_at")

        publish_date = parse_publish_date(date_field, source)

        # Generate unique ID
        article_id = generate_article_id(source_id, source)

        normalized = {
            "id": article_id,
            "title": title,
            "author": author,
            "url": url,
            "source_id": source_id,
            "publish_date": publish_date,
            "source": source.value,
        }

        logger.debug(f"Normalized article: {title[:50]}... from {source.value}")
        return normalized

    except Exception as e:
        logger.error(
            f"Failed to normalize article from {source.value}: {e}", exc_info=True
        )
        return None
