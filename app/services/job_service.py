from __future__ import annotations

from typing import Any

import httpx


class JobService:
    """Simple jobs source using Remotive public API."""

    BASE_URL = "https://remotive.com/api/remote-jobs"

    async def search_jobs(self, role: str, location: str = "remote", limit: int = 5) -> list[dict[str, Any]]:
        params = {"search": f"{role} {location}".strip()}

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        jobs = []
        for item in data.get("jobs", [])[:limit]:
            jobs.append(
                {
                    "title": item.get("title"),
                    "company": item.get("company_name"),
                    "location": item.get("candidate_required_location"),
                    "url": item.get("url"),
                    "type": item.get("job_type"),
                    "published_at": item.get("publication_date"),
                }
            )

        return jobs


job_service = JobService()
