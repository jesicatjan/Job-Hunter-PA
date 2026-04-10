"""
Schemas for application tracking
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel


class ApplicationCreate(BaseModel):
    job_id: Optional[str] = None
    job_title: str
    company: str
    resume_text: Optional[str] = None
    resume_keywords: Optional[List[str]] = None
    match_score: float = 0
    status: str = "TAILORED"  # SEARCHING, TAILORED, APPLIED, INTERVIEWED, OFFERED, REJECTED


class ApplicationResponse(BaseModel):
    id: str
    job_title: str
    company: str
    status: str
    match_score: float
    applied_date: Optional[datetime] = None
    interview_date: Optional[datetime] = None
    follow_up_date: Optional[datetime] = None
    notes: Optional[str] = None


class ApplicationsListResponse(BaseModel):
    applications: List[ApplicationResponse] = []
    total: int = 0
