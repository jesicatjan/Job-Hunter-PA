"""
Jora RSS Feed Parser
Jora has public RSS feeds similar to Indeed
Covers 100K+ listings globally
"""
import httpx
import feedparser
from datetime import datetime
from typing import Optional
import logging

from . import BaseJobSource, JobPosting

logger = logging.getLogger(__name__)


class JoraRSSSource(BaseJobSource):
    """
    Jora job listings via public RSS feeds.
    """
    
    BASE_URL = "https://jora.com/rss"
    
    def __init__(self):
        super().__init__()
        self.name = "Jora"
        self.description = "Jora job listings via RSS feed"
    
    async def search_jobs(
        self,
        query: str,
        location: str = "singapore",
        limit: int = 20,
    ) -> list[JobPosting]:
        """
        Search Jora RSS feed
        """
        try:
            feed_url = self._build_feed_url(query, location)
            
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(feed_url)
                response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            jobs = []
            for entry in feed.entries[:limit]:
                try:
                    job = self._parse_jora_entry(entry)
                    jobs.append(job)
                except Exception as e:
                    logger.warning(f"Error parsing Jora entry: {e}")
                    continue
            
            logger.info(f"Jora found {len(jobs)} jobs for '{query}'")
            return jobs
            
        except Exception as e:
            logger.error(f"Jora RSS search failed: {e}")
            return []
    
    @staticmethod
    def _build_feed_url(query: str, location: str = "singapore") -> str:
        """Build Jora RSS feed URL"""
        import urllib.parse
        
        params = {
            "k": query,
            "l": location,
        }
        
        query_string = urllib.parse.urlencode(params)
        return f"https://jora.com/rss?{query_string}"
    
    @staticmethod
    def _parse_jora_entry(entry: dict) -> JobPosting:
        """Parse Jora RSS entry"""
        
        salary_min, salary_max = None, None
        if "summary" in entry:
            salary_min, salary_max = BaseJobSource.normalize_salary(entry.summary)
        
        posted_at = None
        try:
            if "published_parsed" in entry:
                posted_at = datetime(*entry.published_parsed[:6])
        except:
            pass
        
        return JobPosting(
            title=entry.get("title", "Unknown"),
            company=entry.get("author", "Unknown"),
            location=entry.get("location", "Singapore"),
            url=entry.get("link", ""),
            source="Jora",
            salary_min=salary_min,
            salary_max=salary_max,
            currency="SGD",
            description=entry.get("summary", ""),
            requirements=None,
            posted_at=posted_at,
        )


# Test
if __name__ == "__main__":
    import asyncio
    
    async def test():
        source = JoraRSSSource()
        jobs = await source.search_jobs("python developer", "singapore", 3)
        for job in jobs:
            print(f"✓ {job.title} at {job.company}")
    
    asyncio.run(test())
