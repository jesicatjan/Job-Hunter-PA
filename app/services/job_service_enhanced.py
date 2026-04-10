"""
Enhanced Job Service - Multi-source aggregation
Orchestrates all job sources and applies deduplication, ranking, caching
"""
import asyncio
import logging
from sqlmodel import Session

from app.models import Job, JobStatus, SavedSearchProfile
from app.services.job_sources.mycareersfuture import MyCareersFutureSource
from app.services.job_sources.indeed_rss import IndeedRSSSource
from app.services.job_sources.jora_rss import JoraRSSSource
from app.services.deduplication import JobDeduplicator, JobRanker

logger = logging.getLogger(__name__)


class EnhancedJobService:
    """
    Multi-source job aggregation service
    Searches multiple sources in parallel, deduplicates, ranks, and stores results
    """
    
    def __init__(self, session: Session):
        self.session = session
        
        # Initialize all sources
        self.sources = [
            MyCareersFutureSource(),  # Tier 1: Government official, best for SG
            IndeedRSSSource(),         # Tier 1: Largest coverage
            JoraRSSSource(),           # Tier 2: Good breadth
        ]
        
        self.deduplicator = JobDeduplicator(session)
        self.ranker = JobRanker()
    
    async def search_jobs(
        self,
        query: str,
        location: str = "singapore",
        limit: int = 10,
        user_id: int = None,
    ) -> dict:
        """
        Search all job sources in parallel
        
        Returns:
            {
                'jobs': [...],
                'total': 42,
                'sources_queried': 3,
                'deduped': 5,
                'cached': False,
            }
        """
        
        logger.info(f"🔍 Starting parallel search: {query} in {location}")
        
        try:
            # Search all sources in parallel
            all_jobs = await self._search_all_sources(query, location)
            
            # Deduplicate
            unique_jobs = all_jobs  # TODO: Apply deduplication if user_id provided
            if user_id:
                unique_jobs = await self.deduplicator.deduplicate_jobs(all_jobs, user_id)
            
            # Rank jobs
            ranked_jobs = self._rank_jobs(unique_jobs, query)
            
            # Store in database if user provided
            if user_id:
                await self._store_jobs(ranked_jobs[:limit], user_id)
            
            # Return top results
            result_jobs = ranked_jobs[:limit]
            
            logger.info(
                f"✅ Search complete: {len(result_jobs)} jobs "
                f"(from {len(all_jobs)} total, {len(all_jobs) - len(unique_jobs)} dupes)"
            )
            
            return {
                "jobs": [self._job_to_dict(job) for job in result_jobs],
                "total": len(unique_jobs),
                "sources_queried": len(self.sources),
                "deduped": len(all_jobs) - len(unique_jobs),
                "query": query,
                "location": location,
            }
            
        except Exception as e:
            logger.error(f"Search failed: {e}", exc_info=True)
            return {
                "jobs": [],
                "total": 0,
                "error": str(e),
            }
    
    async def _search_all_sources(self, query: str, location: str) -> list:
        """Search all sources in parallel"""
        
        # Create tasks for all sources
        tasks = [
            source.search_jobs(query, location, limit=20)
            for source in self.sources
        ]
        
        # Execute in parallel with timeout
        results = []
        for i, task in enumerate(asyncio.as_completed(tasks, timeout=30)):
            try:
                source_jobs = await task
                results.extend(source_jobs)
                logger.info(f"  ✓ Source {i+1}/{len(self.sources)}: {len(source_jobs)} jobs")
            except asyncio.TimeoutError:
                logger.warning(f"  ⏱️  Source {i+1} timed out")
            except Exception as e:
                logger.warning(f"  ❌ Source {i+1} failed: {e}")
        
        logger.info(f"Total jobs from all sources: {len(results)}")
        return results
    
    def _rank_jobs(self, jobs: list, query: str) -> list:
        """Rank jobs by relevance"""
        
        # Score each job
        scored_jobs = [
            (job, self.ranker.score_job(job, query))
            for job in jobs
        ]
        
        # Sort by score descending
        ranked = sorted(scored_jobs, key=lambda x: x[1], reverse=True)
        
        # Log top results
        if ranked:
            logger.info(f"Top job: {ranked[0][0].title} @ {ranked[0][0].company} (score: {ranked[0][1]})")
        
        return [job for job, score in ranked]
    
    async def _store_jobs(self, jobs: list, user_id: int):
        """Store jobs to database for persistence"""
        for job_posting in jobs:
            try:
                # Check if URL already exists
                existing = self.session.query(Job).filter(
                    Job.url == job_posting.url
                ).first()
                
                if not existing:
                    job = Job(
                        user_id=user_id,
                        title=job_posting.title,
                        company=job_posting.company,
                        location=job_posting.location,
                        url=job_posting.url,
                        source=job_posting.source,
                        job_type=job_posting.job_type,
                        salary_min=job_posting.salary_min,
                        salary_max=job_posting.salary_max,
                        description=job_posting.description,
                        requirements=job_posting.requirements,
                        posted_at=job_posting.posted_at,
                        status=JobStatus.BOOKMARKED,
                    )
                    self.session.add(job)
            except Exception as e:
                logger.warning(f"Failed to store job: {e}")
        
        try:
            self.session.commit()
            logger.info(f"Stored {len(jobs)} jobs to database")
        except Exception as e:
            logger.warning(f"Database commit failed: {e}")
            self.session.rollback()
    
    @staticmethod
    def _job_to_dict(job) -> dict:
        """Convert JobPosting to dictionary for API response"""
        return {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "source": job.source,
            "job_type": job.job_type,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_range": f"SGD {job.salary_min:,.0f} - {job.salary_max:,.0f}"
            if job.salary_min and job.salary_max
            else None,
            "description": job.description[:200] if job.description else None,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        }


# Keep old instance for backward compatibility
job_service = None

def get_enhanced_job_service(session: Session) -> EnhancedJobService:
    """Factory function to create service with session"""
    return EnhancedJobService(session)
