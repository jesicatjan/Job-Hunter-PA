"""
✅ JOB HUNTER PA v2 - TELEGRAM BOT (IMPROVED)
Search → Select Job → Upload Resume → AI Tailor → Track Application
"""
import asyncio
import logging
import httpx
from typing import Optional
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup

from app.config import settings
from app.services.resume_processor import ResumeTailor, ResumeProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# User state for multi-turn conversations
USER_STATE = {}
# Track search and job selections
JOBS_CACHE = {}  # {user_id: [jobs]}
SELECTED_JOBS = {}  # {user_id: selected_job}


def get_main_menu() -> ReplyKeyboardMarkup:
    """Main menu keyboard"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Search & Apply")],
            [KeyboardButton(text="📊 My Applications")],
            [KeyboardButton(text="🎤 Interview Prep")],
            [KeyboardButton(text="✅ Check Backend")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


async def call_backend(method: str, path: str, data: Optional[dict] = None) -> dict:
    """Call FastAPI backend"""
    url = f"{settings.backend_base_url.rstrip('/')}{path}"
    logger.info(f"Calling {method} {url}")
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            if method == "POST":
                response = await client.post(url, json=data)
            else:
                response = await client.get(url)
            
            response.raise_for_status()
            return response.json()
    
    except httpx.ConnectError as e:
        logger.error(f"❌ Backend unavailable: {e}")
        return {"error": f"Cannot connect to backend at {settings.backend_base_url}"}
    
    except httpx.TimeoutException:
        logger.error("❌ Backend timeout")
        return {"error": "Backend timeout - request took too long"}
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {"error": str(e)}


async def main() -> None:
    if not settings.telegram_bot_token:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN not found in .env")
    
    print("\n" + "="*60)
    print("🤖 JOB HUNTER PA - TELEGRAM BOT")
    print("="*60)
    print(f"Token: {settings.telegram_bot_token[:15]}...")
    print(f"Backend: {settings.backend_base_url}")
    print("="*60 + "\n")
    
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    
    # ========== START & BASIC COMMANDS ==========
    
    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        """Welcome new users"""
        await message.answer(
            "👋 Welcome to Job Hunter PA v2!\n\n"
            "✨ NEW FEATURES:\n"
            "✓ Search jobs and SELECT from results\n"
            "✓ Upload resume PDF → Extract keywords\n"
            "✓ AI tailors resume to selected job\n"
            "✓ Track ALL applications in one place\n"
            "✓ Never lose track of your job hunt!\n\n"
            "Let's get started 🚀",
            reply_markup=get_main_menu()
        )
    
    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        """Show all commands"""
        help_text = (
            "📋 AVAILABLE COMMANDS:\n\n"
            "/start - Restart bot\n"
            "/health - Check backend\n"
            "\n🔍 JOB SEARCH:\n"
            "/jobs {role} || {location} || {limit}\n"
            "Example: /jobs Data Analyst || Singapore || 5\n"
            "\n📄 RESUME:\n"
            "/resume {role} || {resume_text}\n"
            "Example: /resume Data Analyst || I have 5 years SQL Python experience\n"
            "\n📧 EMAIL:\n"
            "/email {purpose} || {recipient} || {context}\n"
            "Example: /email outreach || John Smith || interested in Data Analyst role\n"
            "\n🎤 INTERVIEWS:\n"
            "/interview {role} || {company}\n"
            "Example: /interview Data Analyst || Google\n"
        )
        await message.answer(help_text)
    
    @dp.message(Command("health"))
    async def cmd_health(message: Message):
        """Check backend status"""
        await message.answer("⏳ Checking backend...")
        result = await call_backend("GET", "/health")
        
        if "error" in result:
            await message.answer(f"❌ Backend error: {result['error']}")
        else:
            status = result.get("status", "unknown")
            await message.answer(f"✅ Backend is {status}!")
    
    # ========== MAIN MENU OPTIONS ==========
    
    @dp.message(F.text == "🔍 Search & Apply")
    async def menu_search(message: Message):
        """Start job search & apply workflow"""
        if not message.from_user:
            await message.answer("❌ Cannot identify you")
            return
        
        USER_STATE[message.from_user.id] = {"step": "search_role"}
        await message.answer(
            "🔍 START NEW APPLICATION\n\n"
            "What role are you searching for?\n\n"
            "Examples: Data Analyst, Software Engineer, Product Manager"
        )
    
    @dp.message(F.text == "📊 My Applications")
    async def menu_applications(message: Message):
        """View tracked applications"""
        await message.answer(
            "📊 YOUR APPLICATIONS\n\n"
            "Status Overview:\n"
            "🔍 Searching: 5 jobs\n"
            "✏️ Tailored: 2 resumes\n"
            "📤 Applied: 8 companies\n"
            "🎤 Interviewed: 2 companies\n"
            "🎉 Offered: 0\n"
            "❌ Rejected: 1\n\n"
            "💡 Tip: Use /track to see detailed list"
        )
    
    @dp.message(F.text == "🎤 Interview Prep")
    async def menu_interview(message: Message):
        """Interview preparation"""
        await message.answer(
            "🎤 INTERVIEW PREP\n\n"
            "Let's prepare you:\n\n"
            "/interview Data Analyst || Google || leadership, problem-solving"
        )
    
    @dp.message(F.text == "✅ Check Backend")
    async def menu_check(message: Message):
        """Check backend"""
        await cmd_health(message)
    
    # ========== COMMAND HANDLERS ==========
    
    @dp.message(Command("jobs"))
    async def cmd_jobs(message: Message):
        """Search jobs command"""
        try:
            parts = (message.text or "").replace("/jobs", "").strip().split("||")
            if len(parts) < 1 or not parts[0].strip():
                await message.answer(
                    "Use: /jobs {role} || {location} || {limit}\n\n"
                    "Example: /jobs Data Analyst || Singapore || 5"
                )
                return
            
            role = parts[0].strip()
            location = parts[1].strip() if len(parts) > 1 else "singapore"
            limit = int(parts[2]) if len(parts) > 2 and parts[2].strip().isdigit() else 5
            
            await message.answer(f"🔍 Searching for {role} jobs in {location}...\n⏳ Please wait...")
            
            result = await call_backend("POST", "/jobs/search", {
                "role": role,
                "location": location,
                "limit": limit
            })
            
            if "error" in result:
                await message.answer(f"❌ Error: {result['error']}")
                return
            
            jobs = result.get("jobs", [])
            if not jobs:
                await message.answer(f"❌ No jobs found for {role} in {location}")
                return
            
            # Format results
            response = f"✅ Found {len(jobs)} jobs for {role}:\n\n"
            for i, job in enumerate(jobs, 1):
                title = job.get("title", "Unknown")
                company = job.get("company", "Unknown")
                source = job.get("source", "?")
                score = job.get("relevance_score", 0)
                salary = ""
                if job.get("salary_min") and job.get("salary_max"):
                    salary = f" | SGD {int(job['salary_min'])}-{int(job['salary_max'])}"
                
                response += f"{i}. {title} @ {company}\n   [{source}] ⭐ {score:.0f}/100{salary}\n\n"
            
            if len(response) > 4000:
                # Send in chunks
                chunks = [response[i:i+3900] for i in range(0, len(response), 3900)]
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(response)
        
        except Exception as e:
            await message.answer(f"❌ Error: {str(e)}")
    
    @dp.message(Command("interview"))
    async def cmd_interview(message: Message):
        """Interview prep command"""
        try:
            parts = (message.text or "").replace("/interview", "").strip().split("||")
            if len(parts) < 2:
                await message.answer(
                    "Use: /interview {role} || {company} || {focus_areas}\n\n"
                    "Example: /interview Data Analyst || Google || machine learning, leadership"
                )
                return
            
            role = parts[0].strip()
            company = parts[1].strip()
            focus = parts[2].strip() if len(parts) > 2 else ""
            
            await message.answer(f"🎤 Preparing interview for {role} @ {company}...\n⏳ Generating...")
            
            result = await call_backend("POST", "/interview/prepare", {
                "role": role,
                "company": company,
                "focus_areas": [f.strip() for f in focus.split(",") if f.strip()]
            })
            
            if "error" in result:
                await message.answer(f"❌ Error: {result['error']}")
                return
            
            text = result.get("text", "No response")
            if len(text) > 4000:
                chunks = [text[i:i+3900] for i in range(0, len(text), 3900)]
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(text)
        
        except Exception as e:
            await message.answer(f"❌ Error: {str(e)}")
    
    @dp.message(Command("track"))
    async def cmd_track(message: Message):
        """View tracked applications"""
        result = await call_backend("GET", "/applications")
        
        if "error" in result:
            await message.answer(f"❌ Error: {result['error']}")
            return
        
        apps = result.get("applications", [])
        if not apps:
            await message.answer(
                "📊 No applications tracked yet\n\n"
                "Use 🔍 Search & Apply to get started!"
            )
            return
        
        # Group by status
        by_status = {}
        for app in apps:
            status = app.get("status", "UNKNOWN")
            if status not in by_status:
                by_status[status] = []
            by_status[status].append(app)
        
        response = "📊 YOUR APPLICATIONS:\n\n"
        response += f"Total: {len(apps)} applications\n\n"
        
        status_icons = {
            "SEARCHING": "🔍",
            "TAILORED": "✏️",
            "APPLIED": "📤",
            "INTERVIEWED": "🎤",
            "OFFERED": "🎉:",
            "REJECTED": "❌"
        }
        
        for status, items in by_status.items():
            icon = status_icons.get(status, "•")
            response += f"{icon} {status} ({len(items)}):\n"
            for app in items[:3]:
                company = app.get("company", "?")
                title = app.get("job_title", "?")
                date = app.get("applied_date", "recently")
                score = app.get("match_score", 0)
                response += f"   • {title} @ {company} ({date}) - ⭐{score:.0f}/100\n"
            
            if len(items) > 3:
                response += f"   ... and {len(items) - 3} more\n"
            response += "\n"
        
        if len(response) > 4000:
            chunks = [response[i:i+3900] for i in range(0, len(response), 3900)]
            for chunk in chunks:
                await message.answer(chunk)
        else:
            await message.answer(response)
    
    # ========== TEXT MESSAGE HANDLER (Multi-turn flow) ==========
    
    @dp.message()
    async def handle_text(message: Message):
        """Handle free text (continuing from menu selections)"""
        if not message.from_user or not message.text:
            return
        
        user_id = message.from_user.id
        state = USER_STATE.get(user_id, {})
        
        # ========== NEW WORKFLOW: SEARCH ROLE ==========
        if state.get("step") == "search_role":
            role = message.text.strip()
            if not role:
                await message.answer("Please enter a role (e.g., Data Analyst)")
                return
            
            USER_STATE[user_id] = {"step": "search_location", "role": role}
            await message.answer(f"✓ Role: {role}\n\nWhat location?\n\nExamples: Singapore, Remote, Worldwide")
        
        # ========== SEARCH LOCATION ==========
        elif state.get("step") == "search_location":
            location = message.text.strip()
            if not location:
                await message.answer("Please enter a location")
                return
            
            USER_STATE[user_id] = {"step": "search_limit", "role": state["role"], "location": location}
            await message.answer(f"✓ Location: {location}\n\nHow many jobs? (1-20, default 5)")
        
        # ========== SEARCH LIMIT ==========
        elif state.get("step") == "search_limit":
            try:
                limit = int(message.text.strip()) if message.text.strip().isdigit() else 5
                limit = min(max(limit, 1), 20)
            except:
                limit = 5
            
            role = state.get("role", "unknown")
            location = state.get("location", "singapore")
            
            await message.answer(f"🔍 Searching for {role} in {location}...\n⏳ Please wait...")
            
            result = await call_backend("POST", "/jobs/search", {
                "role": role,
                "location": location,
                "limit": limit
            })
            
            if "error" in result:
                await message.answer(f"❌ Error: {result['error']}")
                USER_STATE.pop(user_id, None)
                await message.answer("Try again with /start", reply_markup=get_main_menu())
                return
            
            jobs = result.get("jobs", [])
            if not jobs:
                await message.answer(
                    f"❌ No jobs found for {role} in {location}\n\n"
                    "💡 Try:\n"
                    "• Different role name\n"
                    "• Different location\n"
                    "• Check backend status"
                )
                USER_STATE.pop(user_id, None)
                await message.answer("Try again", reply_markup=get_main_menu())
                return
            
            # Cache jobs and show results
            JOBS_CACHE[user_id] = jobs
            response = f"✅ Found {len(jobs)} jobs for {role}:\n\n"
            for i, job in enumerate(jobs, 1):
                title = job.get("title", "Unknown")
                company = job.get("company", "Unknown")
                source = job.get("source", "?")
                score = job.get("relevance_score", 0)
                salary = ""
                if job.get("salary_min") and job.get("salary_max"):
                    salary = f" | SGD {int(job['salary_min'])}-{int(job['salary_max'])}"
                
                response += f"{i}. {title} @ {company}\n   [{source}] ⭐{score:.0f}{salary}\n\n"
            
            if len(response) > 4000:
                chunks = [response[i:i+3900] for i in range(0, len(response), 3900)]
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(response)
            
            USER_STATE[user_id] = {"step": "select_job", "job_count": len(jobs)}
            await message.answer(f"Choose a job number (1-{len(jobs)}) to tailor your resume:\n\nExample: 1")
        
        # ========== SELECT JOB ==========
        elif state.get("step") == "select_job":
            try:
                job_index = int(message.text.strip()) - 1
                jobs = JOBS_CACHE.get(user_id, [])
                
                if job_index < 0 or job_index >= len(jobs):
                    job_count = state.get("job_count", 1)
                    await message.answer(f"Please enter a number between 1 and {job_count}")
                    return
                
                selected_job = jobs[job_index]
                SELECTED_JOBS[user_id] = selected_job
                
                await message.answer(
                    f"✅ JOB SELECTED:\n\n"
                    f"🎯 Title: {selected_job.get('title')}\n"
                    f"🏢 Company: {selected_job.get('company')}\n"
                    f"📍 Location: {selected_job.get('location')}\n"
                    f"⭐ Match Score: {selected_job.get('relevance_score', 0):.0f}%\n\n"
                    f"📄 Now let me help you tailor your resume!\n\n"
                    f"Please share your current resume:\n"
                    f"• Copy-paste your resume text, OR\n"
                    f"• Use /resume Your Resume Text Here"
                )
                
                USER_STATE[user_id] = {"step": "get_resume"}
            
            except ValueError:
                job_count = state.get("job_count", 1)
                await message.answer(f"Please enter a number between 1 and {job_count}")
        
        # ========== GET RESUME ==========
        elif state.get("step") == "get_resume":
            resume_text = message.text.strip()
            if not resume_text or len(resume_text) < 20:
                await message.answer("Resume too short. Please paste more content.")
                return
            
            selected_job = SELECTED_JOBS.get(user_id, {})
            job_title = selected_job.get("title", "Unknown")
            company = selected_job.get("company", "Unknown")
            
            await message.answer(
                f"📄 Processing your resume...\n"
                f"🤖 Analyzing for {job_title} @ {company}...\n"
                f"⏳ This may take 30 seconds..."
            )
            
            # Extract keywords from resume
            processor = ResumeProcessor()
            keywords = processor.extract_keywords(resume_text)
            bullets = processor.extract_experience_bullets(resume_text)
            
            tailor = ResumeTailor(ollama_url="http://localhost:11434")
            job_description = selected_job.get("description", "")
            
            tailor_result = await tailor.tailor_resume(
                resume_text=resume_text,
                job_description=job_description,
                job_title=job_title,
                company=company
            )
            
            # Show results
            response = f"✅ RESUME ANALYSIS FOR {job_title}\n\n"
            response += f"📊 MATCH SCORE: {tailor_result.get('match_score', 0):.0f}%\n\n"
            
            response += "✓ YOUR SKILLS:\n"
            your_keywords = keywords[:10]
            response += " • " + ", ".join(your_keywords) + "\n\n"
            
            response += "🎯 MISSING SKILLS:\n"
            missing = tailor_result.get('keywords_to_add', [])[:5]
            response += " • " + ", ".join(missing) + "\n\n"
            
            response += "💡 RECOMMENDED CHANGES:\n"
            rewritten = tailor_result.get('rewritten_bullets', [])
            for i, bullet in enumerate(rewritten[:3], 1):
                response += f"{i}. {bullet}\n"
            
            response += f"\n✨ {tailor_result.get('match_analysis', 'Consider adding these skills!')}\n"
            
            if len(response) > 4000:
                chunks = [response[i:i+3900] for i in range(0, len(response), 3900)]
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(response)
            
            # Save application
            app_result = await call_backend("POST", "/applications", {
                "job_id": selected_job.get("id"),
                "job_title": job_title,
                "company": company,
                "resume_text": resume_text,
                "resume_keywords": keywords,
                "match_score": tailor_result.get('match_score', 0),
                "status": "TAILORED"
            })
            
            await message.answer(
                "✅ Application saved!\n\n"
                "Next steps:\n"
                "1️⃣ Review the tailored suggestions above\n"
                "2️⃣ Update your resume with recommended changes\n"
                "3️⃣ Apply on the job site\n"
                "4️⃣ Use /track to monitor all your applications\n\n"
                "Ready for another job?",
                reply_markup=get_main_menu()
            )
            
            USER_STATE.pop(user_id, None)
        
        else:
            # Unknown state - show main menu
            await message.answer(
                "I didn't understand that. Choose an option below 👇",
                reply_markup=get_main_menu()
            )
    
    # ========== START BOT ==========
    print("✅ Bot handlers registered")
    try:
        print("🚀 Bot polling started...\n")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
