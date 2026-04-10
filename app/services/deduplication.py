"""
Job Deduplication System
Ensures users don't see the same job twice across different sources
"""
import hashlib
import logging
from datetime import datetime, timedelta
from sqlmodel import Session, select

from app.models import Job, JobCache
from app.services.job_sources import JobPosting

logger = logging.getLogger(__name__)


class JobDeduplicator:
    """
    Smart deduplication system that:
    1. Checks if job URL already exists in database
    2. Identifies similar jobs from different sources
    3. Handles URL variations (trailing slashes, parameters, etc.)
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    async def deduplicate_jobs(
        self,
        new_jobs: list[JobPosting],
        user_id: int,
    ) -> list[JobPosting]:
        """
        Filter out jobs user has already seen
        
        Args:
            new_jobs: List of JobPosting from sources
            user_id: User ID to check against
            
        Returns:
            Filtered list with only genuinely new jobs
        """
        
        # Get all existing job URLs for this user
        existing_urls = self._get_existing_urls(user_id)
        
        # Get normalized URLs from existing jobs
        normalized_existing = {self._normalize_url(url) for url in existing_urls}
        
        # Filter new jobs
        unique_jobs = []
        for job in new_jobs:
            normalized_new_url = self._normalize_url(job.url)
            
            # Check if we've seen this URL before
            if normalized_new_url not in normalized_existing:
                unique_jobs.append(job)
                normalized_existing.add(normalized_new_url)
            else:
                logger.info(f"Skipping duplicate: {job.title} at {job.company}")
        
        logger.info(f"Deduplicated {len(new_jobs)} jobs -> {len(unique_jobs)} unique")
        return unique_jobs
    
    def _get_existing_urls(self, user_id: int) -> set[str]:
        """Get all job URLs user has already seen"""
        statement = select(Job.url).where(Job.user_id == user_id)
        results = self.session.exec(statement).all()
        return set(results)
    
    @staticmethod
    def _normalize_url(url: str) -> str:
        """
        Normalize URLs to handle variations
        - Remove tracking parameters
        - Standardize domain
        - Remove trailing slashes
        """
        if not url:
            return ""
        
        url = url.lower().strip()
        
        # Remove common tracking parameters
        tracking_params = [
            "utm_source", "utm_medium", "utm_campaign",
            "fbclid", "gclid", "msclkid",
        ]
        
        for param in tracking_params:
            if f"?{param}=" in url:
                url = url.split(f"?{param}=")[0]
            if f"&{param}=" in url:
                url = url.split(f"&{param}=")[0]
        
        # Remove trailing slashes and query strings
        url = url.rstrip("/").split("?")[0]
        
        return url
    
    @staticmethod
    def _get_url_hash(url: str) -> str:
        """Generate consistent hash for URL (useful for similarity detection)"""
        return hashlib.md5(url.encode()).hexdigest()


class JobRanker:
    """
    Rank jobs by relevance based on multiple factors
    """
    
    @staticmethod
    def score_job(
        job: JobPosting,
        query: str,
        user_history: dict = None,
    ) -> float:
        """
        Calculate relevance score 0-100 for a job
        
        Factors:
        - Keyword match in title/description (0-40)
        - Salary competitiveness (0-20)
        - Company reputation (0-20)
        - Recency (0-20)
        """
        score = 0
        
        # 1. Keyword matching (0-40)
        query_lower = query.lower()
        title_lower = job.title.lower()
        
        if query_lower in title_lower:
            score += 40  # Exact match in title
        elif any(word in title_lower for word in query_lower.split()):
            score += 25  # Partial match
        
        # 2. Salary (0-20) - preference for higher salaries
        if job.salary_max:
            # Assuming ~8000-12000 SGD is competitive for entry roles
            if 8000 <= job.salary_max <= 15000:
                score += 20
            elif job.salary_max > 15000:
                score += 15
            elif job.salary_max > 5000:
                score += 10
        
        # 3. Source credibility (0-20)
        source_scores = {
            "MyCareersFuture": 20,  # Official government source
            "Indeed": 18,  # Largest job board
            "LinkedIn": 17,
            "Jora": 15,
            "GitHub": 15,
            "HackerNews": 12,
        }
        score += source_scores.get(job.source, 10)
        
        # 4. Recency (0-20)
        if job.posted_at:
            days_old = (datetime.utcnow() - job.posted_at).days
            if days_old <= 1:
                score += 20
            elif days_old <= 7:
                score += 15
            elif days_old <= 30:
                score += 10
        
        return min(score, 100)  # Cap at 100


class JobCache:
    """Cache job search results to minimize API calls"""
    
    def __init__(self, session: Session):
        self.session = session
        self.cache_ttl_hours = 6  # Refresh every 6 hours
    
    async def get_cached_results(
        self,
        source: str,
        query: str,
        location: str,
    ) -> list[JobPosting] | None:
        """Retrieve cached results if still valid"""
        
        now = datetime.utcnow()
        statement = select(JobCache).where(
            JobCache.source == source,
            JobCache.query == query,
            JobCache.location == location,
            JobCache.expires_at > now,
        )
        
        cached = self.session.exec(statement).first()
        
        if cached:
            logger.info(f"Cache HIT for {source}: {query}")
            # Note: In production, you'd deserialize the JSON response
            return None  # Placeholder
        
        logger.info(f"Cache MISS for {source}: {query}")
        return None
    
    async def cache_results(
        self,
        source: str,
        query: str,
        location: str,
        jobs: list[JobPosting],
    ):
        """Store search results in cache"""
        
        cache_entry = JobCache(
            source=source,
            query=query,
            location=location,
            raw_response="{}",  # TODO: Serialize jobs to JSON
            result_count=len(jobs),
            cached_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=self.cache_ttl_hours),
        )
        
        self.session.add(cache_entry)
        self.session.commit()
        logger.info(f"Cached {len(jobs)} results from {source}")
