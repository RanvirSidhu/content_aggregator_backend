"""
Content fetching service module.

Handles fetching articles from external sources with timeout handling,
error management, and result aggregation.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import SourceType
from app.models.database import ArticleDB, MetadataDB
from app.utils.article_parser import normalize_article
from app.core.logging import get_logger

logger = get_logger(__name__)

# Source configurations
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


async def fetch_source(source: SourceType, config: Dict) -> Dict:
    """
    Fetch articles from a single content source.
    
    Makes an HTTP request to the source API, handles errors and timeouts,
    and normalizes the returned articles into a unified format.
    
    Args:
        source: The content source to fetch from
        config: Source configuration containing URL and timeout settings
        
    Returns:
        dict: Result dictionary containing:
            - source: Source name
            - success: Whether fetch succeeded (bool)
            - articles: List of normalized articles (if successful)
            - error: Error message (if failed)
            - fetch_time: Time taken to fetch (seconds)
            
    Example:
        >>> await fetch_source(SourceType.DEVTO, SOURCES[SourceType.DEVTO])
        {"source": "Dev.to", "success": True, "articles": [...], "fetch_time": 1.23}
    """
    logger.info(f"Starting fetch from {source.value}")
    start_time = datetime.now(timezone.utc)
    
    result = {
        "source": source.value,
        "success": False,
        "articles": [],
        "error": None,
        "fetch_time": 0,
    }
    
    try:
        async with httpx.AsyncClient() as client:
            logger.debug(f"Sending request to {config.get('url')}")
            
            response = await client.get(
                config.get("url"),
                timeout=config.get("timeout", 10),
                follow_redirects=True,
            )
            response.raise_for_status()
            
            logger.info(f"Successfully fetched from {source.value}, status: {response.status_code}")
            
            # Parse response based on source
            if source == SourceType.REDDIT:
                data = response.json()
                raw_articles = data.get("data", {}).get("children", [])
            else:
                raw_articles = response.json()
            
            logger.debug(f"Received {len(raw_articles)} raw articles from {source.value}")
            
            # Normalize articles
            articles = []
            for entry in raw_articles:
                normalized = normalize_article(source, entry)
                if normalized:
                    articles.append(normalized)
            
            result["success"] = True
            result["articles"] = articles
            result["fetch_time"] = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            logger.info(
                f"Completed fetch from {source.value}: "
                f"{len(articles)} articles normalized in {result['fetch_time']:.2f}s"
            )
    
    except httpx.TimeoutException as e:
        result["error"] = f"Timeout after {config.get('timeout')}s"
        logger.error(f"{source.value}: Request timeout - {e}")
    
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
        logger.error(f"{source.value}: HTTP error {e.response.status_code} - {e}")
    
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"{source.value}: Unexpected error - {e}", exc_info=True)
    
    return result


async def fetch_all_sources(db: AsyncSession) -> Dict[str, Any]:
    """
    Fetch articles from all configured sources concurrently.
    
    Executes fetch operations for all sources in parallel, saves new articles
    to the database, and updates the last refresh metadata.
    
    Args:
        db: Async database session
        
    Returns:
        dict: Summary containing:
            - total_fetched: Total articles fetched
            - new_saved: Number of new articles saved
            - sources_succeeded: Number of successful sources
            - sources_failed: Number of failed sources
            
    Example:
        >>> await fetch_all_sources(db_session)
        {"total_fetched": 150, "new_saved": 25, "sources_succeeded": 3, "sources_failed": 0}
    """
    logger.info(f"Starting concurrent fetch from {len(SOURCES)} sources")
    start_time = datetime.now(timezone.utc)
    
    # Create fetch tasks for all sources
    tasks = [fetch_source(source, config) for source, config in SOURCES.items()]
    
    # Execute all fetches concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_articles = []
    sources_succeeded = 0
    sources_failed = 0
    
    # Process results
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Task exception: {result}")
            sources_failed += 1
            continue
        
        if result["success"]:
            articles = result.get("articles", [])
            all_articles.extend(articles)
            sources_succeeded += 1
            logger.info(f"{result['source']}: Added {len(articles)} articles to batch")
        else:
            sources_failed += 1
            logger.warning(f"{result['source']}: Failed - {result.get('error')}")
    
    # Save new articles to database
    logger.info(f"Saving {len(all_articles)} articles to database")
    saved_count = 0
    
    for article_data in all_articles:
        try:
            # Check if article already exists
            stmt = select(ArticleDB).where(ArticleDB.id == article_data["id"])
            existing = await db.execute(stmt)
            existing_article = existing.scalar_one_or_none()
            
            if not existing_article:
                new_article = ArticleDB(**article_data)
                db.add(new_article)
                saved_count += 1
        except Exception as e:
            logger.error(f"Failed to save article {article_data.get('title', 'Unknown')}: {e}")
    
    await db.commit()
    logger.info(f"Saved {saved_count} new articles to database")
    
    # Update last refresh metadata
    try:
        metadata_stmt = select(MetadataDB).where(MetadataDB.key == "last_refresh")
        result = await db.execute(metadata_stmt)
        last_refresh = result.scalar_one_or_none()
        
        current_time = datetime.now(timezone.utc)
        if last_refresh:
            last_refresh.value = current_time.isoformat()
            last_refresh.update_at = current_time
            logger.debug("Updated last_refresh metadata")
        else:
            last_refresh = MetadataDB(
                key="last_refresh",
                value=current_time.isoformat()
            )
            db.add(last_refresh)
            logger.debug("Created last_refresh metadata")
        
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to update metadata: {e}")
    
    total_time = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    summary = {
        "total_fetched": len(all_articles),
        "new_saved": saved_count,
        "sources_succeeded": sources_succeeded,
        "sources_failed": sources_failed,
        "fetch_time": total_time,
    }
    
    logger.info(
        f"Fetch all sources completed in {total_time:.2f}s: "
        f"{summary['total_fetched']} fetched, {summary['new_saved']} new, "
        f"{summary['sources_succeeded']}/{len(SOURCES)} sources succeeded"
    )
    
    return summary
