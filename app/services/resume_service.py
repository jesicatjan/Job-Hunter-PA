"""
Resume Management Service
Persistent storage of multiple resume versions with revision history
"""
import logging
from datetime import datetime
from typing import Optional
from sqlmodel import Session, select

from app.models import Resume, User

logger = logging.getLogger(__name__)


class ResumeManager:
    """
    Manage multiple resume versions
    - Master resume (comprehensive)
    - Role-specific versions
    - Full revision history
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    async def save_resume(
        self,
        user_id: int,
        content: str,
        role: Optional[str] = None,
        is_master: bool = False,
        notes: Optional[str] = None,
    ) -> Resume:
        """
        Save a new resume version
        
        Args:
            user_id: User ID
            content: Resume text content
            role: Target role (e.g., "Data Analyst", None for master)
            is_master: Whether this is the master copy
            notes: Optional notes about this version
            
        Returns:
            Saved Resume object with version number
        """
        
        # Get next version number
        statement = select(Resume).where(
            Resume.user_id == user_id,
            Resume.role == role,
        ).order_by(Resume.version.desc())
        
        last_resume = self.session.exec(statement).first()
        next_version = (last_resume.version + 1) if last_resume else 1
        
        # Create new resume record
        resume = Resume(
            user_id=user_id,
            version=next_version,
            role=role,
            content=content,
            is_master=is_master,
            notes=notes,
            created_at=datetime.utcnow(),
        )
        
        self.session.add(resume)
        self.session.commit()
        self.session.refresh(resume)
        
        logger.info(f"Saved resume v{next_version} for user {user_id}")
        return resume
    
    async def get_master_resume(self, user_id: int) -> Optional[Resume]:
        """Get the master (comprehensive) resume"""
        statement = select(Resume).where(
            Resume.user_id == user_id,
            Resume.is_master == True,
        ).order_by(Resume.version.desc())
        
        return self.session.exec(statement).first()
    
    async def get_latest_resume(
        self,
        user_id: int,
        role: Optional[str] = None,
    ) -> Optional[Resume]:
        """
        Get latest resume for a specific role.
        If role is None, returns master resume.
        If no master, returns highest version.
        """
        
        statement = select(Resume).where(
            Resume.user_id == user_id,
            Resume.role == role,
        ).order_by(Resume.version.desc())
        
        resume = self.session.exec(statement).first()
        
        if resume:
            logger.info(f"Retrieved resume v{resume.version} for user {user_id}, role={role}")
            return resume
        
        logger.warning(f"No resume found for user {user_id}, role={role}")
        return None
    
    async def get_all_resumes(self, user_id: int) -> list[Resume]:
        """Get all resume versions for a user"""
        statement = select(Resume).where(
            Resume.user_id == user_id,
        ).order_by(Resume.created_at.desc())
        
        return self.session.exec(statement).all()
    
    async def get_revision_history(
        self,
        user_id: int,
        role: Optional[str] = None,
    ) -> list[dict]:
        """
        Get revision history for a role
        Returns list of versions with metadata
        """
        
        statement = select(Resume).where(
            Resume.user_id == user_id,
            Resume.role == role,
        ).order_by(Resume.version.asc())
        
        resumes = self.session.exec(statement).all()
        
        history = [
            {
                "version": r.version,
                "created_at": r.created_at.isoformat(),
                "notes": r.notes,
                "word_count": len(r.content.split()),
                "character_count": len(r.content),
            }
            for r in resumes
        ]
        
        return history
    
    async def compare_versions(
        self,
        resume_id_1: int,
        resume_id_2: int,
    ) -> dict:
        """
        Compare two resume versions
        Returns diff of changes
        """
        
        r1 = self.session.get(Resume, resume_id_1)
        r2 = self.session.get(Resume, resume_id_2)
        
        if not r1 or not r2:
            return {"error": "Resume(s) not found"}
        
        # Simple diff: character count and line count changes
        import difflib
        
        lines1 = r1.content.splitlines()
        lines2 = r2.content.splitlines()
        
        diff = list(difflib.unified_diff(lines1, lines2, lineterm=""))
        
        return {
            "version_1": r1.version,
            "version_2": r2.version,
            "char_count_before": len(r1.content),
            "char_count_after": len(r2.content),
            "char_change": len(r2.content) - len(r1.content),
            "line_count_before": len(lines1),
            "line_count_after": len(lines2),
            "diff_summary": f"{len([l for l in diff if l.startswith('+')])} additions, "
                           f"{len([l for l in diff if l.startswith('-')])} deletions",
        }
    
    async def delete_resume_version(
        self,
        resume_id: int,
        user_id: int,
    ) -> bool:
        """
        Delete a specific resume version
        Safety: Don't allow deleting the only version
        """
        
        resume = self.session.get(Resume, resume_id)
        
        if not resume or resume.user_id != user_id:
            logger.warning(f"Unauthorized deletion attempt")
            return False
        
        # Check if this is the only version
        count_statement = select(Resume).where(
            Resume.user_id == user_id,
            Resume.role == resume.role,
        )
        count = len(self.session.exec(count_statement).all())
        
        if count <= 1:
            logger.warning("Cannot delete the only resume version")
            return False
        
        self.session.delete(resume)
        self.session.commit()
        
        logger.info(f"Deleted resume v{resume.version}")
        return True


class ResumeAnalyzer:
    """
    Analyze resume quality and provide suggestions
    """
    
    @staticmethod
    def analyze_resume(content: str) -> dict:
        """
        Analyze resume and provide scores
        """
        
        lines = content.splitlines()
        words = content.split()
        sentences = content.split(".")
        
        analysis = {
            "overall_score": 0,
            "metrics": {
                "word_count": len(words),
                "line_count": len(lines),
                "sentence_count": len(sentences),
            },
            "sections": {},
            "suggestions": [],
        }
        
        # Check for key sections
        sections = ["EDUCATION", "EXPERIENCE", "SKILLS", "PROJECT", "TECHNICAL"]
        content_upper = content.upper()
        
        for section in sections:
            if section in content_upper:
                analysis["sections"][section] = True
                analysis["overall_score"] += 20
        
        # Check for action verbs
        action_verbs = [
            "built", "developed", "created", "designed", "led", "managed",
            "improved", "optimized", "implemented", "achieved",
        ]
        action_verb_count = sum(1 for verb in action_verbs if verb in content.lower())
        
        analysis["metrics"]["action_verbs"] = action_verb_count
        if action_verb_count < 5:
            analysis["suggestions"].append("Add more action verbs to start bullet points")
        
        # Check for quantifiable metrics
        import re
        numbers = re.findall(r'\b\d+(?:%|x|times|\+)?\b', content)
        analysis["metrics"]["quantifiable_metrics"] = len(numbers)
        if len(numbers) < 5:
            analysis["suggestions"].append("Add more quantifiable metrics (percentages, numbers, etc.)")
        
        # Length check
        if len(words) < 200:
            analysis["suggestions"].append("Resume is quite short - consider expanding with more details")
        elif len(words) > 750:
            analysis["suggestions"].append("Resume is long - try to condense to 1 page (400-600 words)")
        
        return analysis
