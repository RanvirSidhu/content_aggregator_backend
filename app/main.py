from enum import Enum
from datetime import datetime, UTC
import asyncio
import httpx


class SourceType(str, Enum):
    HACKERNEWS = "HackerNews"
    DEVTO = "Dev.to"
    REDDIT = "Reddit"
    LOBSTERS = "Lobsters"


SOURCES = {
    # SourceType.HACKERNEWS : {
    #     "url":"https://hacker-news.firebaseio.com/v0/newstories.json",
    #     "category_default": "Tech News"
    # },
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


class Article:
    def __init__(self, id, title, author, url, publish_date, src):
        self.id = id
        self.title = title
        self.author = author
        self.url = url
        self.publish_date = publish_date
        self.source = src


def parseDate(src, date_str):
    if isinstance(date_str, datetime):
        return date_str

    if src == SourceType.REDDIT:
        return datetime.fromtimestamp(date_str, tz=UTC)
    elif src == SourceType.DEVTO:
        return datetime.fromisoformat(date_str[:-1] + "+00:00")
    else:
        return datetime.fromisoformat(date_str)

    return None


def generateID(src, id):
    combined = f"{src}-{id}"
    return combined
    # return hashlib.md5(combined.encode()).hexdigest()


def generateRedditURL(premalink):
    url = "https://reddit.com" + premalink
    return url


def normalizeArticle(src, article):
    try:
        if src == SourceType.REDDIT:
            article = article["data"]

        # print(article)

        id = generateID(src.value, article.get("id") or article.get("short_id"))

        title = article.get("title")

        if src == SourceType.DEVTO:
            author = article.get("user").get("username")
        else:
            author = article.get("author") or article.get("submitter_user")

        if src == SourceType.REDDIT:
            url = generateRedditURL(article.get("permalink"))
        else:
            url = article.get("url")

        publish_date = parseDate(
            src,
            (
                article.get("published_at")
                or article.get("created")
                or article.get("created_at")
            ),
        )
        source = src.name

        return Article(id, title, author, url, publish_date, source)

    except Exception as e:
        print(f"Error normalizing article from {source}: {e}")
        return None


async def fetchSource(source, url):
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


async def fetchAllSources():
    tasks = []
    for source, config in SOURCES.items():
        tasks.append(fetchSource(source, config["url"]))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_articles = []
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)

    return all_articles


async def main():
    # result = await fetchSource(SourceType.DEVTO, SOURCES[SourceType.DEVTO]["url"])
    # # result = await fetchSource(SourceType.REDDIT, SOURCES[SourceType.REDDIT]["url"])
    # # result = await fetchSource(SourceType.LOBSTERS, SOURCES[SourceType.LOBSTERS]["url"])

    result = await fetchAllSources()
    for article in result:
        print(
            article.id, article.title, article.author, article.url, article.publish_date
        )


asyncio.run(main())
