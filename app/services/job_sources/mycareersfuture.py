"""
MyCareersFuture – Singapore government job portal.
Uses the public JSON API (no auth required, 80K+ listings, includes salary).
Endpoint discovered via community reverse-engineering (stable since 2023).
"""
import httpx
import logging
from datetime import datetime
from . import BaseJobSource, JobPosting

logger = logging.getLogger(__name__)

BASE = "https://api.mycareersfuture.gov.sg/v2/jobs"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobHunterPA/1.0)",
    "Accept": "application/json",
}


class MyCareersFutureSource(BaseJobSource):
    name = "MyCareersFuture"

    async def search_jobs(self, query: str, location: str = "singapore", limit: int = 20) -> list[JobPosting]:
        params = {
            "search": query,
            "limit": min(limit, 100),
            "page": 0,
            "sortBy": "new_posting_date",
        }
        try:
            async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
                r = await client.get(BASE, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.error(f"MCF error: {e}")
            return []

        jobs = []
        for item in (data.get("results") or [])[:limit]:
            try:
                jobs.append(self._parse(item))
            except Exception as e:
                logger.debug(f"MCF parse error: {e}")
        logger.info(f"MCF: {len(jobs)} jobs for '{query}'")
        return jobs

    @staticmethod
    def _parse(item: dict) -> JobPosting:
        salary = item.get("salary") or {}
        sal_min = float(salary.get("minimum", 0)) or None
        sal_max = float(salary.get("maximum", 0)) or None

        posted_at = None
        if item.get("metadata", {}).get("newPostingDate"):
            try:
                posted_at = datetime.fromisoformat(item["metadata"]["newPostingDate"][:10])
            except Exception:
                pass

        job_id = item.get("uuid", "")
        url = f"https://www.mycareersfuture.gov.sg/job/{job_id}" if job_id else ""

        emp_types = item.get("employmentTypes") or []
        job_type = emp_types[0].get("employmentType") if emp_types else None

        return JobPosting(
            title=item.get("title", "Unknown"),
            company=(item.get("postedCompany") or {}).get("name", "Unknown"),
            location="Singapore",
            url=url,
            source="MyCareersFuture",
            job_type=job_type,
            salary_min=sal_min,
            salary_max=sal_max,
            currency="SGD",
            description=(item.get("description") or "")[:500],
            posted_at=posted_at,
        )
