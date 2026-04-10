"""
Indeed RSS Feed Parser
Indeed exposes public RSS feeds per search query - completely legitimate, not scraping
Covers 200K+ jobs globally, including Singapore
"""
import httpx
import feedparser
from datetime import datetime
from typing import Optional
import logging

from . import BaseJobSource, JobPosting

logger = logging.getLogger(__name__)


class IndeedRSSSource(BaseJobSource):
    """
    Indeed job listings via public RSS feeds.
    Uses Indeed's official RSS feature - no scraping, completely legitimate.
    """
    
    BASE_URL = "https://www.indeed.com/rss"
    
    def __init__(self):
        super().__init__()
        self.name = "Indeed"
        self.description = "Indeed job listings via RSS feed"
    
    async def search_jobs(
        self,
        query: str,
        location: str = "singapore",
        limit: int = 20,
    ) -> list[JobPosting]:
        """
        Search Indeed RSS feed
        
        Indeed RSS URL format:
        https://www.indeed.com/rss?q=python&l=singapore
        
        Returns:
            List of JobPosting objects
        """
        try:
            # Build RSS feed URL
            feed_url = self._build_feed_url(query, location)
            
            # Fetch RSS feed
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(feed_url)
                response.raise_for_status()
            
            # Parse feed
            feed = feedparser.parse(response.content)
            
            jobs = []
            for entry in feed.entries[:limit]:
                try:
                    job = self._parse_indeed_entry(entry)
                    jobs.append(job)
                except Exception as e:
                    logger.warning(f"Error parsing Indeed entry: {e}")
                    continue
            
            logger.info(f"Indeed found {len(jobs)} jobs for '{query}' in {location}")
            return jobs
            
        except Exception as e:
            logger.error(f"Indeed RSS search failed: {e}")
            return []
    
    @staticmethod
    def _build_feed_url(query: str, location: str = "singapore") -> str:
        """Build Indeed RSS feed URL with proper URL encoding"""
        import urllib.parse
        
        # Map location names to Indeed location codes
        location_map = {
            "singapore": "singapore",
            "sg": "singapore",
            "remote": "remote",
            "anywhere": "remote",
        }
        
        location_code = location_map.get(location.lower(), location)
        
        params = {
            "q": query,
            "l": location_code,
            "sort": "date",  # Sort by newest first
            "limit": 50,  # RSS max
        }
        
        query_string = urllib.parse.urlencode(params)
        return f"https://www.indeed.com/rss?{query_string}"
    
    @staticmethod
    def _parse_indeed_entry(entry: dict) -> JobPosting:
        """Parse RSS entry into JobPosting"""
        
        # Extract salary from description (Indeed embeds salary in HTML)
        salary_min, salary_max = None, None
        if "summary" in entry:
            salary_min, salary_max = BaseJobSource.normalize_salary(entry.summary)
        
        # Parse published date
        posted_at = None
        try:
            if "published_parsed" in entry:
                posted_at = datetime(*entry.published_parsed[:6])
        except:
            pass
        
        return JobPosting(
            title=entry.get("title", "Unknown"),
            company=entry.get("author", "Unknown"),  # Indeed uses 'author' for company
            location="Singapore",  # RSS doesn't always include location
            url=entry.get("link", ""),
            source="Indeed",
            salary_min=salary_min,
            salary_max=salary_max,
            currency="SGD",
            description=entry.get("summary", ""),
            requirements=None,  # Indeed doesn't provide structured requirements in RSS
            posted_at=posted_at,
        )


# Test the source
if __name__ == "__main__":
    import asyncio
    
    async def test():
        source = IndeedRSSSource()
        jobs = await source.search_jobs("data analyst", "singapore", 3)
        for job in jobs:
            print(f"✓ {job.title} at {job.company}")
            print(f"  Link: {job.url}")
    
    asyncio.run(test())
