from typing import Any, Optional

from pydantic import BaseModel, Field


class JobsRequest(BaseModel):
    role: str
    location: Optional[str] = "remote"
    limit: int = Field(default=5, ge=1, le=20)


class ResumeReviseRequest(BaseModel):
    current_resume: str
    target_role: str
    key_skills: list[str] = Field(default_factory=list)


class DraftEmailRequest(BaseModel):
    purpose: str
    recipient_name: str
    context: str
    tone: str = "professional"


class InterviewPrepRequest(BaseModel):
    role: str
    company: str
    focus_areas: list[str] = Field(default_factory=list)


class TrackJobRequest(BaseModel):
    company: str
    role: str
    status: str = "Applied"
    link: Optional[str] = None
    notes: Optional[str] = None


class LLMResponse(BaseModel):
    text: str


class JobsResponse(BaseModel):
    query: dict[str, Any]
    jobs: list[dict[str, Any]]


class TrackJobResponse(BaseModel):
    message: str
    page_id: Optional[str] = None
