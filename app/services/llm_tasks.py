"""
All LLM-powered features:
  - resume_revise()
  - resume_tailor()      ← uses keyword gap analysis
  - draft_email()
  - draft_outreach()
  - interview_prep()
  - company_brief()
  - practice_interview() ← interactive
"""
import json
import re
import logging
from app import llm_client
from app.resume_utils import extract_keywords, gap_analysis, extract_jd_requirements

logger = logging.getLogger(__name__)


async def resume_revise(resume_text: str, target_role: str) -> str:
    system = (
        "You are a senior career coach and resume expert. "
        "Give specific, actionable feedback. Be concise but thorough. "
        "Format with clear sections using emoji bullets."
    )
    user = f"""Target role: {target_role}

Resume:
{resume_text}

Please provide:
1. **Overall Score** (X/10) with one-line verdict
2. **Top 5 Improvements** – specific changes to make, with before/after examples where useful
3. **ATS Issues** – formatting problems, missing sections, keyword gaps
4. **Strengths** – what to keep and highlight
5. **Revised Summary/Objective** – write a 2-3 line tailored summary for the role

Be specific and reference actual content from their resume."""
    return await llm_client.complete(system, user, max_tokens=1500)


async def resume_tailor(resume_text: str, jd_text: str, job_title: str, company: str) -> str:
    """
    Deep tailoring using keyword gap analysis first, then LLM rewriting.
    """
    gap = gap_analysis(resume_text, jd_text)
    jd_info = extract_jd_requirements(jd_text)

    matched_str  = ", ".join(gap["matched"])  or "none identified"
    missing_str  = ", ".join(gap["missing"])  or "none"
    required_str = "\n".join(f"  • {r}" for r in jd_info["required"]) or "  Not specified"

    system = (
        "You are an expert resume writer. "
        "Tailor the resume to maximise interview chances for the target role. "
        "NEVER invent experience. Only rewrite/reframe existing content."
    )
    user = f"""Job: {job_title} at {company}

--- KEYWORD GAP ANALYSIS ---
Matched ({gap['match_pct']}% match): {matched_str}
Missing from resume: {missing_str}

--- JD REQUIREMENTS ---
{required_str}

--- JOB DESCRIPTION ---
{jd_text[:2000]}

--- CANDIDATE RESUME ---
{resume_text}

Return a JSON object ONLY (no markdown fences):
{{
  "match_score": 78,
  "missing_keywords": ["sql", "stakeholder"],
  "rewritten_bullets": [
    {{"original": "Built dashboards", "improved": "Developed interactive Power BI dashboards tracking 5 KPIs, enabling data-driven decisions for 3 business units", "reason": "Quantified impact and added KPI language from JD"}}
  ],
  "tailored_summary": "2-3 line tailored summary for this specific role",
  "ats_tips": ["Add 'stakeholder management' to skills section", "Rename 'Work Experience' to 'Professional Experience'"],
  "overall_advice": "Short paragraph on the biggest gaps and how to address them"
}}"""

    raw = await llm_client.complete(system, user, max_tokens=2000)
    # Try to parse JSON, fallback to raw text
    try:
        clean = re.sub(r"```json|```", "", raw).strip()
        parsed = json.loads(clean)
        # Format nicely for Telegram
        lines = []
        lines.append(f"🎯 *Match Score: {parsed.get('match_score', gap['match_pct'])}%*")
        lines.append(f"\n✅ *Matched keywords:* {matched_str}")
        lines.append(f"❌ *Missing keywords:* {', '.join(parsed.get('missing_keywords', gap['missing']))}")

        lines.append(f"\n📝 *Tailored Summary:*\n_{parsed.get('tailored_summary', '')}_")

        bullets = parsed.get("rewritten_bullets", [])
        if bullets:
            lines.append(f"\n💡 *Top Rewrites ({len(bullets)} bullets):*")
            for b in bullets[:5]:
                lines.append(f"\n*Before:* {b.get('original', '')}")
                lines.append(f"*After:* {b.get('improved', '')}")
                lines.append(f"_Why: {b.get('reason', '')}_")

        tips = parsed.get("ats_tips", [])
        if tips:
            lines.append(f"\n⚡ *ATS Tips:*")
            for t in tips:
                lines.append(f"  • {t}")

        lines.append(f"\n📌 *Advice:* {parsed.get('overall_advice', '')}")
        return "\n".join(lines)
    except Exception:
        return raw  # return raw LLM text if JSON parsing fails


async def draft_email(purpose: str, recipient_name: str, context: str, tone: str = "professional") -> str:
    system = (
        "You are a professional communication coach specialised in job search. "
        "Write emails that are warm, specific, and get responses. "
        "Always include a clear subject line starting with 'Subject:'"
    )
    user = f"""Write a {tone} job search email.

Purpose: {purpose}
Recipient name: {recipient_name}
Context: {context}

Requirements:
- Start with 'Subject: [your subject line]'
- Then a blank line
- Then the email body
- Keep it concise (under 200 words)
- End with a clear call-to-action
- Sign off professionally"""
    return await llm_client.complete(system, user, max_tokens=600)


async def draft_outreach(
    recipient_name: str,
    role: str,
    company: str,
    sender_name: str,
    resume_highlights: str = "",
) -> tuple[str, str]:
    """Returns (subject, body)."""
    system = (
        "You are an outreach email expert. Write concise, personalised cold emails "
        "that hiring managers actually read. Under 180 words. Warm but professional."
    )
    user = f"""Write a cold outreach email for a job application.

To: {recipient_name} at {company}
Role: {role}
From: {sender_name}
Resume highlights: {resume_highlights or 'see attached resume'}

Format EXACTLY as:
Subject: [subject line]

[email body – no 'Subject:' line in body]

Rules:
- Reference the company specifically
- Mention 1-2 concrete achievements from resume highlights
- Ask for a 15-min call (not a job)
- End: Best regards,\n{sender_name}
- Attach resume line: 'I've attached my resume for reference.'"""

    raw = await llm_client.complete(system, user, max_tokens=500)
    lines = raw.strip().splitlines()
    subject = "Application Interest"
    body_lines = []
    for i, line in enumerate(lines):
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
        else:
            body_lines.extend(lines[i:])
            break
    body = "\n".join(body_lines).strip()
    if not body:
        body = raw
    return subject, body


async def interview_prep(role: str, company: str, focus_areas: list[str] = None) -> str:
    focus = ", ".join(focus_areas) if focus_areas else "general behavioural and technical"
    system = "You are a top-tier interview coach. Be specific and practical."
    user = f"""Prepare me for an interview:

Role: {role}
Company: {company}
Focus: {focus}

Provide:
1. 🏢 **Company Brief** – 3 bullets: what they do, culture, recent news
2. ❓ **10 Likely Questions** – mix of behavioural and technical for this role
3. ✅ **Strong Answer Framework** – STAR method reminder + 2 example answers
4. 🧠 **Technical Prep** – top 5 technical areas to revise for this role
5. 💬 **3 Smart Questions to Ask** – shows strategic thinking
6. 📅 **24-Hour Prep Plan** – hour-by-hour schedule

Be specific to {role} at {company}. No generic advice."""
    return await llm_client.complete(system, user, max_tokens=2000)


async def practice_question(role: str, company: str, question_type: str = "behavioural") -> str:
    """Generate a single interview question for practice."""
    system = "You are an interviewer. Ask ONE question only."
    user = f"Generate a realistic {question_type} interview question for a {role} role at {company}. Return only the question."
    return await llm_client.complete(system, user, max_tokens=100)


async def evaluate_answer(question: str, answer: str, role: str) -> str:
    """Evaluate a practice interview answer."""
    system = "You are an expert interviewer giving constructive feedback."
    user = f"""Question: {question}
Candidate's answer: {answer}
Role: {role}

Give feedback in this format:
⭐ Score: X/10
✅ What worked: [2-3 specific points]
⚡ Improve: [2-3 specific improvements]
💡 Better version: [rewrite the answer using STAR method, 3-4 sentences]"""
    return await llm_client.complete(system, user, max_tokens=500)


async def company_brief(company: str) -> str:
    system = "You are a business analyst. Be concise and factual."
    user = f"""Give me a quick brief on {company} for interview prep:
- What they do (1 sentence)
- Main products/services (2-3 bullets)
- Culture & values (2 bullets)
- Recent news/achievements (1-2 bullets)
- Why people want to work there (1 sentence)
Keep it under 200 words."""
    return await llm_client.complete(system, user, max_tokens=400)
