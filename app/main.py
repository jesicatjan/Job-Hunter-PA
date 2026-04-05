from fastapi import FastAPI, HTTPException

from app.schemas import (
    DraftEmailRequest,
    InterviewPrepRequest,
    JobsRequest,
    JobsResponse,
    LLMResponse,
    ResumeReviseRequest,
    TrackJobRequest,
    TrackJobResponse,
)
from app.services.job_service import job_service
from app.services.notion_service import notion_service
from app.services.openclaw_client import openclaw_client

app = FastAPI(title="Job Hunter Personal Assistant API", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs/search", response_model=JobsResponse)
async def search_jobs(payload: JobsRequest) -> JobsResponse:
    jobs = await job_service.search_jobs(payload.role, payload.location or "remote", payload.limit)
    return JobsResponse(
        query={"role": payload.role, "location": payload.location, "limit": payload.limit},
        jobs=jobs,
    )


@app.post("/resume/revise", response_model=LLMResponse)
async def revise_resume(payload: ResumeReviseRequest) -> LLMResponse:
    system = "You are an expert career coach and resume reviewer."
    user = (
        f"Target role: {payload.target_role}\n"
        f"Key skills: {', '.join(payload.key_skills) if payload.key_skills else 'N/A'}\n"
        "Please revise this resume for impact and ATS friendliness.\n"
        "Return:\n"
        "1) Improved resume text\n"
        "2) Top 5 changes made\n\n"
        f"Resume:\n{payload.current_resume}"
    )
    text = await openclaw_client.complete(system, user)
    return LLMResponse(text=text)


@app.post("/email/draft", response_model=LLMResponse)
async def draft_email(payload: DraftEmailRequest) -> LLMResponse:
    system = "You are a professional communication assistant specialized in job search emails."
    user = (
        f"Purpose: {payload.purpose}\n"
        f"Recipient name: {payload.recipient_name}\n"
        f"Tone: {payload.tone}\n"
        f"Context: {payload.context}\n\n"
        "Draft a polished email with a clear subject line and call to action."
    )
    text = await openclaw_client.complete(system, user)
    return LLMResponse(text=text)


@app.post("/interview/prepare", response_model=LLMResponse)
async def prepare_interview(payload: InterviewPrepRequest) -> LLMResponse:
    system = "You are a job interview preparation coach."
    focus = ", ".join(payload.focus_areas) if payload.focus_areas else "general interview readiness"
    user = (
        f"Role: {payload.role}\n"
        f"Company: {payload.company}\n"
        f"Focus areas: {focus}\n\n"
        "Create a practical interview prep plan including:\n"
        "1) likely questions with strong sample answers\n"
        "2) technical and behavioral prep checklist\n"
        "3) 3 smart questions to ask interviewer\n"
        "4) 24-hour prep timeline"
    )
    text = await openclaw_client.complete(system, user)
    return LLMResponse(text=text)


@app.post("/notion/track", response_model=TrackJobResponse)
async def track_job(payload: TrackJobRequest) -> TrackJobResponse:
    try:
        message, page_id = await notion_service.track_job(
            company=payload.company,
            role=payload.role,
            status=payload.status,
            link=payload.link,
            notes=payload.notes,
        )
        return TrackJobResponse(message=message, page_id=page_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to track job: {exc}") from exc
