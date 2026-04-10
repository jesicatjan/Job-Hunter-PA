"""
SQLModel schema for Job Hunter PA
Defines all persistent data structures
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum


# ===================== ENUMS =====================

class JobStatus(str, Enum):
    """Job application status"""
    BOOKMARKED = "bookmarked"
    APPLIED = "applied"
    INTERVIEWED = "interviewed"
    OFFERED = "offered"
    REJECTED = "rejected"


class ApplicationStatus(str, Enum):
    """Application workflow status"""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    FIRST_ROUND = "first_round"
    TECHNICAL = "technical"
    FINAL = "final"
    OFFER = "offer"
    REJECTED = "rejected"


# ===================== CORE MODELS =====================

class User(SQLModel, table=True):
    """User profile"""
    id: Optional[int] = Field(default=None, primary_key=True)
    telegram_user_id: int = Field(unique=True, index=True)
    name: str
    email: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    resumes: list["Resume"] = Relationship(back_populates="user")
    jobs: list["Job"] = Relationship(back_populates="user")
    applications: list["Application"] = Relationship(back_populates="user")
    search_profiles: list["SavedSearchProfile"] = Relationship(back_populates="user")
    emails_sent: list["EmailRecord"] = Relationship(back_populates="user")
    star_stories: list["STARStory"] = Relationship(back_populates="user")


class Resume(SQLModel, table=True):
    """Persistent resume storage with versioning"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    version: int = Field(ge=1)  # v1, v2, v3, etc.
    role: Optional[str] = None  # e.g., "Data Analyst", "Software Engineer"
    content: str  # Full resume text
    is_master: bool = False  # Master copy vs. role-specific
    created_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None
    
    user: Optional[User] = Relationship(back_populates="resumes")
    
    class Config:
        index_fields = ["user_id", "role", "version"]


class Job(SQLModel, table=True):
    """Job posting deduplication & tracking"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    # Core job data
    title: str
    company: str
    location: str
    url: str = Field(unique=True)  # Unique URL for deduplication
    
    # Metadata
    source: str  # "MyCareersFuture", "Indeed", "GitHub", etc.
    job_type: Optional[str] = None  # "Full-time", "Contract", etc.
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: Optional[str] = "SGD"
    
    # Job details
    description: Optional[str] = None
    requirements: Optional[str] = None
    
    # Tracking
    status: JobStatus = JobStatus.BOOKMARKED
    posted_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    relevance_score: Optional[float] = None  # 0-100
    
    user: Optional[User] = Relationship(back_populates="jobs")
    application: Optional["Application"] = Relationship(back_populates="job")


class Application(SQLModel, table=True):
    """Job application tracking"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    job_id: int = Field(foreign_key="job.id")
    
    # Application details
    status: ApplicationStatus = ApplicationStatus.DRAFT
    applied_at: Optional[datetime] = None
    resume_version_used: Optional[int] = None
    
    # Tracking
    notion_page_id: Optional[str] = None
    follow_up_date: Optional[datetime] = None
    interview_date: Optional[datetime] = None
    notes: Optional[str] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: Optional[User] = Relationship(back_populates="applications")
    job: Optional[Job] = Relationship(back_populates="application")
    communication_logs: list["CommunicationLog"] = Relationship(back_populates="application")


class CommunicationLog(SQLModel, table=True):
    """Track all communication for an application"""
    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id")
    
    type: str  # "email", "phone", "linkedin", "interview"
    direction: str  # "outbound", "inbound"
    subject: Optional[str] = None
    content: Optional[str] = None
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None
    
    application: Optional[Application] = Relationship(back_populates="communication_logs")


class SavedSearchProfile(SQLModel, table=True):
    """Saved search preferences for daily digest"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    name: str  # e.g., "Data Analyst Remote", "Singapore Tech"
    
    # Search criteria
    job_title: str
    location: str
    max_results: int = 10
    
    # Filters
    min_salary: Optional[float] = None
    max_salary: Optional[float] = None
    employment_type: Optional[str] = None  # "Full-time", "Contract", etc.
    
    # Digest settings
    enabled: bool = True
    send_daily_digest: bool = True
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: Optional[User] = Relationship(back_populates="search_profiles")


class EmailRecord(SQLModel, table=True):
    """Track sent emails for follow-up automation"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    to_email: str
    to_name: str
    subject: str
    body: str
    
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    opened: bool = False
    opened_at: Optional[datetime] = None
    
    follow_up_scheduled: bool = False
    follow_up_date: Optional[datetime] = None
    follow_up_sent: bool = False
    
    company: Optional[str] = None
    role: Optional[str] = None
    
    user: Optional[User] = Relationship(back_populates="emails_sent")


class STARStory(SQLModel, table=True):
    """Stored STAR (Situation, Task, Action, Result) interview stories"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    title: str  # e.g., "Led analytics project at Skyworks"
    
    situation: str  # The context
    task: str  # What you had to accomplish
    action: str  # What you did
    result: str  # What happened (with metrics)
    lessons_learned: Optional[str] = None
    
    # Tagging
    themes: str  # Comma-separated: "leadership,analytics,technical"
    roles_relevant_to: str  # "Data Analyst,Product Manager"
    
    use_count: int = 0  # Track which stories are most used
    last_used: Optional[datetime] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: Optional[User] = Relationship(back_populates="star_stories")


class JobCache(SQLModel, table=True):
    """Cache for job search results to minimize API calls"""
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Search query (unique key)
    source: str  # "MyCareersFuture", "Indeed", etc.
    query: str  # Search term
    location: str
    
    # Cache data
    raw_response: str  # JSON blob of results
    result_count: int
    cached_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime  # When to refresh
    
    class Config:
        index_fields = ["source", "query", "location", "expires_at"]


# ===================== RELATIONSHIP SUMMARY =====================
"""
User (1) -> (N) Resumes
User (1) -> (N) Jobs
User (1) -> (N) Applications
User (1) -> (N) SavedSearchProfiles
User (1) -> (N) EmailRecords
User (1) -> (N) STARStories

Job (1) -> (1) Application
Application (1) -> (N) CommunicationLogs
"""
