"""
Base class for all job sources
Provides common interface for different job APIs/feeds
"""
from abc import ABC, abstractmethod
from typing import Any
from datetime import datetime
from dataclasses import dataclass


@dataclass
class JobPosting:
    """Standardized job posting format"""
    title: str
    company: str
    location: str
    url: str  # Must be globally unique for deduplication
    source: str
    job_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str = "SGD"
    description: str | None = None
    requirements: str | None = None
    posted_at: datetime | None = None


class BaseJobSource(ABC):
    """
    Abstract base class for job sources.
    All sources must implement search_jobs()
    """
    
    name: str
    description: str
    
    def __init__(self):
        self.name = self.__class__.__name__
        self.description = self.__class__.__doc__ or ""
    
    @abstractmethod
    async def search_jobs(
        self,
        query: str,
        location: str = "singapore",
        limit: int = 20,
    ) -> list[JobPosting]:
        """
        Search for jobs matching criteria.
        
        Args:
            query: Job title/skills to search
            location: Location (Singapore, remote, etc.)
            limit: Max results to return
            
        Returns:
            List of standardized JobPosting objects
        """
        pass
    
    @staticmethod
    def normalize_salary(salary_str: str | None) -> tuple[float | None, float | None]:
        """
        Parse salary strings like "$5000 - $8000" into (min, max) tuple
        """
        if not salary_str:
            return None, None
        
        try:
            # Remove currency symbols and whitespace
            salary_str = salary_str.replace("SGD", "").replace("$", "").strip()
            
            # Handle ranges
            if "-" in salary_str:
                parts = salary_str.split("-")
                min_sal = float(parts[0].strip().replace(",", ""))
                max_sal = float(parts[1].strip().replace(",", ""))
                return min_sal, max_sal
            else:
                # Single value
                sal = float(salary_str.replace(",", ""))
                return sal, sal
        except (ValueError, IndexError):
            return None, None
    
    @staticmethod
    def normalize_location(location: str) -> str:
        """Normalize location names (Singapore, SG, sg -> singapore)"""
        location = location.lower().strip()
        
        location_map = {
            "sg": "singapore",
            "sentosa": "singapore",
            "marina bay": "singapore",
            "CBD": "singapore",
            "bukit merah": "singapore",
            "paya lebar": "singapore",
        }
        
        return location_map.get(location, location)
    
    def __repr__(self):
        return f"{self.name}(description='{self.description}')"
