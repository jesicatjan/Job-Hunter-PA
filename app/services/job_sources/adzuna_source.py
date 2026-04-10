"""
Adzuna – official REST API, free tier (250 calls/day).
Best for Singapore salary data.
"""
import httpx
import logging
from datetime import datetime
from app.config import settings
from . import BaseJobSource, JobPosting

logger = logging.getLogger(__name__)
BASE = "https://api.adzuna.com/v1/api/jobs/sg/search/1"


class AdzunaSource(BaseJobSource):
    name = "Adzuna"

    async def search_jobs(self, query: str, location: str = "singapore", limit: int = 20) -> list[JobPosting]:
        if not settings.adzuna_app_id or not settings.adzuna_app_key:
            return []
        params = {
            "app_id": settings.adzuna_app_id,
            "app_key": settings.adzuna_app_key,
            "results_per_page": min(limit, 50),
            "what": query,
            "where": "Singapore",
            "content-type": "application/json",
            "sort_by": "date",
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(BASE, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.error(f"Adzuna error: {e}")
            return []

        jobs = []
        for item in (data.get("results") or [])[:limit]:
            try:
                sal_min = float(item.get("salary_min", 0)) or None
                sal_max = float(item.get("salary_max", 0)) or None
                posted_at = None
                if item.get("created"):
                    try:
                        posted_at = datetime.fromisoformat(item["created"][:10])
                    except Exception:
                        pass
                jobs.append(JobPosting(
                    title=item.get("title", "Unknown"),
                    company=(item.get("company") or {}).get("display_name", "Unknown"),
                    location=(item.get("location") or {}).get("display_name", "Singapore"),
                    url=item.get("redirect_url", ""),
                    source="Adzuna",
                    job_type=item.get("contract_time"),
                    salary_min=sal_min,
                    salary_max=sal_max,
                    currency="SGD",
                    description=(item.get("description") or "")[:500],
                    posted_at=posted_at,
                ))
            except Exception as e:
                logger.debug(f"Adzuna parse: {e}")
        logger.info(f"Adzuna: {len(jobs)} jobs for '{query}'")
        return jobs
