"""
Careers@Gov – Singapore government & statutory board jobs.
Public JSON search API, no auth required.
"""
import httpx
import logging
from datetime import datetime
from . import BaseJobSource, JobPosting

logger = logging.getLogger(__name__)
BASE = "https://careers.pageuppeople.com/688/cw/en/listing/"
SEARCH_BASE = "https://api.careers.gov.sg/v1/search"


class CareersGovSource(BaseJobSource):
    name = "Careers@Gov"

    async def search_jobs(self, query: str, location: str = "singapore", limit: int = 20) -> list[JobPosting]:
        # Careers@Gov search endpoint (used by community scrapers)
        params = {
            "keyword": query,
            "pageNo": 1,
            "pageSize": min(limit, 50),
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.careers.gov.sg/",
        }
        try:
            async with httpx.AsyncClient(timeout=15, headers=headers) as client:
                r = await client.get(SEARCH_BASE, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.error(f"Careers@Gov error: {e}")
            return []

        jobs = []
        for item in (data.get("data") or data.get("results") or [])[:limit]:
            try:
                jobs.append(JobPosting(
                    title=item.get("jobTitle") or item.get("title", "Unknown"),
                    company=item.get("agencyName") or item.get("agency", "Singapore Government"),
                    location="Singapore",
                    url=item.get("jobPostUrl") or f"https://www.careers.gov.sg/job/{item.get('jobPostId','')}",
                    source="Careers@Gov",
                    description=(item.get("jobDescription") or "")[:500],
                    posted_at=None,
                ))
            except Exception as e:
                logger.debug(f"Careers@Gov parse: {e}")
        logger.info(f"Careers@Gov: {len(jobs)} jobs for '{query}'")
        return jobs
