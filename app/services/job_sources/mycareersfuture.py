"""
MyCareersFuture API Integration
Singapore's official government job portal
~80,000+ active listings, includes salary ranges
"""
import httpx
from datetime import datetime
from typing import Optional
import json
import logging

from . import BaseJobSource, JobPosting

logger = logging.getLogger(__name__)


class MyCareersFutureSource(BaseJobSource):
    """
    MyCareersFuture - Singapore's official government job board.
    Covers all sectors, includes salary transparency.
    No authentication required, public JSON API.
    """
    
    BASE_URL = "https://api.mycareersfuture.sg/search"
    
    def __init__(self):
        super().__init__()
        self.name = "MyCareersFuture"
        self.description = "Singapore government job portal (80K+ listings)"
    
    async def search_jobs(
        self,
        query: str,
        location: str = "singapore",
        limit: int = 20,
    ) -> list[JobPosting]:
        """
        Search MyCareersFuture API
        
        Returns:
            List of JobPosting objects
        """
        try:
            params = {
                "search": query,
                "limit": min(limit, 100),  # API max is 100
                "page": 1,
            }
            
            # MCF doesn't have location filter in easy API
            # Location filtering done post-response
            
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()
            
            jobs = []
            for result in data.get("results", [])[:limit]:
                try:
                    job = self._parse_mcf_job(result)
                    
                    # Simple location filter
                    if self._location_matches(job.location, location):
                        jobs.append(job)
                except Exception as e:
                    logger.warning(f"Error parsing MCF job: {e}")
                    continue
            
            logger.info(f"MyCareersFuture found {len(jobs)} jobs for '{query}'")
            return jobs
            
        except Exception as e:
            logger.error(f"MyCareersFuture search failed: {e}")
            return []
    
    @staticmethod
    def _parse_mcf_job(item: dict) -> JobPosting:
        """Parse MCF API response into JobPosting"""
        
        # Extract salary info (MCF provides min/max separately)
        salary_min = None
        salary_max = None
        if item.get("salaryMin") and item.get("salaryMax"):
            salary_min = float(item["salaryMin"])
            salary_max = float(item["salaryMax"])
        
        # Parse employment type
        job_type = None
        if item.get("employment"):
            job_type = item["employment"][0] if isinstance(item["employment"], list) else item["employment"]
        
        # Posted date
        posted_at = None
        if item.get("postedDate"):
            try:
                posted_at = datetime.fromisoformat(item["postedDate"].replace("Z", "+00:00"))
            except:
                pass
        
        return JobPosting(
            title=item.get("jobTitle", "Unknown"),
            company=item.get("company", "Unknown"),
            location=item.get("location", "Singapore"),
            url=item.get("listingUrl", f"https://mycareersfuture.sg/job/{item.get('id', '')}"),
            source="MyCareersFuture",
            job_type=job_type,
            salary_min=salary_min,
            salary_max=salary_max,
            currency="SGD",
            description=item.get("description"),
            requirements=item.get("requirements"),
            posted_at=posted_at,
        )
    
    @staticmethod
    def _location_matches(job_location: str, search_location: str) -> bool:
        """Check if job location matches search location"""
        job_loc = job_location.lower().strip()
        search_loc = search_location.lower().strip()
        
        # Exact match
        if job_loc == search_loc:
            return True
        
        # Singapore variations
        if search_loc in ["sg", "singapore"]:
            return "singapore" in job_loc or "sg" in job_loc
        
        # Remote matches
        if search_loc == "remote":
            return "remote" in job_loc
        
        return True  # Default: include it


# Test the source
if __name__ == "__main__":
    import asyncio
    
    async def test():
        source = MyCareersFutureSource()
        jobs = await source.search_jobs("Data Analyst", "singapore", 5)
        for job in jobs:
            print(f"✓ {job.title} at {job.company} ({job.location})")
            if job.salary_min:
                print(f"  Salary: SGD {job.salary_min:,.0f} - {job.salary_max:,.0f}")
    
    asyncio.run(test())
