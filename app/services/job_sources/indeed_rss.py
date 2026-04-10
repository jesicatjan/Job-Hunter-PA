"""
Indeed – public RSS feed (no scraping, no auth, fully legitimate).
URL: https://www.indeed.com/rss?q={query}&l={location}&sort=date
"""
import httpx
import feedparser
import logging
from datetime import datetime
from . import BaseJobSource, JobPosting

logger = logging.getLogger(__name__)


class IndeedRSSSource(BaseJobSource):
    name = "Indeed"

    async def search_jobs(self, query: str, location: str = "singapore", limit: int = 20) -> list[JobPosting]:
        import urllib.parse
        loc = "Singapore" if location.lower() in ("sg", "singapore") else location
        url = f"https://www.indeed.com/rss?{urllib.parse.urlencode({'q': query, 'l': loc, 'sort': 'date', 'limit': 50})}"
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
                r = await client.get(url)
                r.raise_for_status()
            feed = feedparser.parse(r.content)
        except Exception as e:
            logger.error(f"Indeed RSS error: {e}")
            return []

        jobs = []
        for entry in feed.entries[:limit]:
            try:
                posted_at = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    posted_at = datetime(*entry.published_parsed[:6])
                jobs.append(JobPosting(
                    title=entry.get("title", "Unknown"),
                    company=entry.get("author", "Unknown"),
                    location=loc,
                    url=entry.get("link", ""),
                    source="Indeed",
                    description=(entry.get("summary") or "")[:500],
                    posted_at=posted_at,
                ))
            except Exception as e:
                logger.debug(f"Indeed parse: {e}")
        logger.info(f"Indeed: {len(jobs)} jobs for '{query}'")
        return jobs
