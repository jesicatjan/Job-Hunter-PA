"""
Jobicy – free public API, good for remote + Singapore roles.
"""
import httpx
import logging
from datetime import datetime
from . import BaseJobSource, JobPosting

logger = logging.getLogger(__name__)
BASE = "https://jobicy.com/api/v2/remote-jobs"


class JobicySource(BaseJobSource):
    name = "Jobicy"

    async def search_jobs(self, query: str, location: str = "singapore", limit: int = 20) -> list[JobPosting]:
        geo = "singapore" if location.lower() in ("sg", "singapore") else location
        params = {"count": min(limit, 50), "geo": geo, "tag": query}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(BASE, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.error(f"Jobicy error: {e}")
            return []

        jobs = []
        for item in (data.get("jobs") or [])[:limit]:
            try:
                posted_at = None
                if item.get("pubDate"):
                    try:
                        posted_at = datetime.fromisoformat(item["pubDate"][:10])
                    except Exception:
                        pass
                jobs.append(JobPosting(
                    title=item.get("jobTitle", "Unknown"),
                    company=item.get("companyName", "Unknown"),
                    location=item.get("jobGeo", location),
                    url=item.get("url", ""),
                    source="Jobicy",
                    job_type=", ".join(item.get("jobType", [])) if isinstance(item.get("jobType"), list) else item.get("jobType"),
                    description=(item.get("jobDescription") or "")[:500],
                    posted_at=posted_at,
                ))
            except Exception as e:
                logger.debug(f"Jobicy parse: {e}")
        logger.info(f"Jobicy: {len(jobs)} jobs for '{query}'")
        return jobs
