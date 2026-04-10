"""
✅ IMPROVED RESUME SERVICE
Handle PDF uploads, text extraction, and AI-powered tailoring
"""
import re
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class ResumeProcessor:
    """Extract keywords from resume text"""
    
    @staticmethod
    def extract_keywords(resume_text: str) -> list[str]:
        """
        Extract important keywords from resume
        Looks for: skills, tools, languages, frameworks, etc.
        """
        # Common technical keywords to look for
        tech_keywords = {
            # Languages
            'python', 'java', 'javascript', 'sql', 'r', 'scala', 'c++', 'go', 'rust',
            'typescript', 'kotlin', 'php', 'ruby', 'swift', 'objective-c',
            
            # Databases
            'mysql', 'postgresql', 'mongodb', 'redis', 'cassandra', 'dynamodb',
            'elasticsearch', 'snowflake', 'bigquery', 'oracle', 'sqlite',
            
            # Tools & Platforms
            'aws', 'gcp', 'azure', 'docker', 'kubernetes', 'jenkins', 'git',
            'tableau', 'power bi', 'grafana', 'datadog', 'splunk',
            'jira', 'confluence', 'slack', 'github', 'gitlab',
            
            # Frameworks & Libraries
            'tensorflow', 'pytorch', 'scikit-learn', 'pandas', 'numpy', 'keras',
            'react', 'angular', 'vue', 'node', 'express', 'django', 'flask',
            'spark', 'hadoop', 'kafka', 'airflow',
            
            # Methodologies
            'agile', 'scrum', 'kanban', 'devops', 'ci/cd', 'tdd', 'machine learning',
            'nlp', 'deep learning', 'data science', 'analytics', 'etl',
            
            # Soft skills
            'leadership', 'communication', 'teamwork', 'project management',
            'problem solving', 'analytical', 'critical thinking'
        }
        
        # Convert resume to lowercase for matching
        resume_lower = resume_text.lower()
        
        # Find all matching keywords
        found_keywords = []
        for keyword in tech_keywords:
            if keyword in resume_lower:
                found_keywords.append(keyword)
        
        return found_keywords
    
    @staticmethod
    def extract_experience_bullets(resume_text: str) -> list[str]:
        """Extract experience bullet points from resume"""
        bullets = []
        lines = resume_text.split('\n')
        
        # Look for bullet-like lines
        for line in lines:
            line_stripped = line.strip()
            # Lines that start with common bullet points
            if line_stripped.startswith(('-', '•', '*', '◦')) or line_stripped.endswith(':'):
                bullets.append(line_stripped)
        
        return bullets[:10]  # Return top 10


class ResumeTailor:
    """AI-powered resume tailoring"""
    
    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url
        self.model = "mistral"
    
    async def tailor_resume(
        self,
        resume_text: str,
        job_description: str,
        job_title: str,
        company: str
    ) -> dict:
        """
        Tailor resume to job description using AI
        Returns suggestions and tailored version
        """
        # Extract keywords from resume
        resume_keywords = ResumeProcessor.extract_keywords(resume_text)
        
        # Build prompt
        prompt = f"""You are an expert resume writer. Tailor this resume for the job.

JOB TITLE: {job_title}
COMPANY: {company}

JOB DESCRIPTION:
{job_description}

CURRENT RESUME:
{resume_text}

CURRENT RESUME KEYWORDS: {', '.join(resume_keywords)}

TASK:
1. Identify 5-7 key requirements from the job description
2. Extract matching experience from the resume
3. Rewrite experience bullets to emphasize relevant skills
4. Keep ALL experience factual - never invent skills
5. Use action verbs that match job description language
6. Quantify achievements where possible

Return ONLY valid JSON (no markdown, no code blocks):
{{
  "job_requirements": ["requirement1", "requirement2", ...],
  "matching_experience": ["bullet1", "bullet2", ...],
  "rewritten_bullets": [
    {{"original": "old bullet", "rewritten": "new bullet", "reason": "why this is better"}}
  ],
  "keywords_to_add": ["keyword1", "keyword2"],
  "match_score": 85,
  "missing_skills": ["skill1", "skill2"],
  "overall_advice": "General advice about tailoring"
}}"""
        
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "temperature": 0.5,
                    }
                )
            
            data = response.json()
            raw_response = data.get("response", "")
            
            # Clean response (remove markdown)
            clean = re.sub(r"```json|```|`", "", raw_response).strip()
            
            import json
            parsed = json.loads(clean)
            
            return {
                "success": True,
                "tailor_data": parsed
            }
        
        except Exception as e:
            logger.error(f"Tailor error: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class ApplicationTracker:
    """Track application workflow"""
    
    def __init__(self, db_session=None):
        self.session = db_session
    
    async def start_application(
        self,
        job_id: int,
        resume_version: Optional[int] = None
    ) -> dict:
        """Start tracking application for a job"""
        return {
            "job_id": job_id,
            "status": "tailored",
            "resume_version": resume_version,
            "created_at": datetime.utcnow().isoformat()
        }
    
    async def update_application_status(
        self,
        app_id: int,
        new_status: str,
        notes: Optional[str] = None
    ) -> dict:
        """Update application status (Applied, Interviewed, etc.)"""
        return {
            "app_id": app_id,
            "status": new_status,
            "updated_at": datetime.utcnow().isoformat(),
            "notes": notes
        }
    
    def get_application_summary(self) -> dict:
        """Get summary of all applications"""
        return {
            "total": 0,
            "by_status": {
                "searching": 0,
                "tailored": 0,
                "applied": 0,
                "interviewed": 0,
                "offered": 0,
                "rejected": 0
            }
        }


from datetime import datetime
