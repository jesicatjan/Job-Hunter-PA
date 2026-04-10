"""
Job Hunter PA – Telegram Bot 

Features:
  1. Multi-source job search (5 sources, dedup, ranking, inline selection)
  2. Daily 9 AM digest + follow-up reminders via APScheduler
  3. Resume upload (PDF) → stored master resume, never re-upload
  4. Resume revision with AI scoring and ATS tips
  5. Resume tailoring with keyword gap analysis before LLM call
  6. Email drafting (general / follow-up / thank-you)
  7. Cold outreach drafting + Gmail send with PDF attachment
  8. Application tracker → colour-coded Excel export
  9. Interview prep guide (company brief + questions + 24h plan)
  10. Live mock interview (5 Q&A with AI feedback per answer)
  11. STAR story bank (save, view, use in interview prep)
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
from datetime import date, timedelta

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import database as db
from app.config import settings
from app.resume_utils import extract_keywords, extract_text_from_pdf

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BACKEND = settings.backend_base_url.rstrip("/")

# ── Conversation state (in-memory, per user) ──────────────────────────────────
STATE:    dict[int, dict] = {}   # { uid: { "step": ..., ...data } }
PDF_STORE: dict[int, bytes] = {} # { uid: raw_pdf_bytes }
JOBS_CACHE: dict[int, list] = {} # { uid: [job dicts from last search] }
PRACTICE:  dict[int, dict] = {}  # { uid: { role, company, question, count } }


# ── Keyboards ──────────────────────────────────────────────────────────────────

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1. See jobs available")],
            [KeyboardButton(text="2. Revise resume")],
            [KeyboardButton(text="3. Draft email")],
            [KeyboardButton(text="4. Track application")],
            [KeyboardButton(text="5. Prepare for interviews")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def yn_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yes", callback_data=yes_cb),
        InlineKeyboardButton(text="❌ No",  callback_data=no_cb),
    ]])


# ── HTTP helpers ───────────────────────────────────────────────────────────────

async def api_post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{BACKEND}{path}", json=payload)
        r.raise_for_status()
        return r.json()


async def api_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BACKEND}{path}")
        r.raise_for_status()
        return r.json()


async def api_bytes(path: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BACKEND}{path}")
        r.raise_for_status()
        return r.content


# ── Telegram message helpers ───────────────────────────────────────────────────

async def send_long(msg: Message, text: str, pm: str = "Markdown") -> None:
    """Send text split into <=3900-char chunks."""
    for i in range(0, len(text), 3900):
        chunk = text[i: i + 3900]
        try:
            await msg.answer(chunk, parse_mode=pm)
        except Exception:
            await msg.answer(chunk)


def fmt_jobs(jobs: list[dict]) -> str:
    if not jobs:
        return "❌ No new jobs found."
    lines = [f"📋 *Found {len(jobs)} job(s):*\n"]
    for i, j in enumerate(jobs, 1):
        sal = f"\n   💰 {j['salary']}" if j.get("salary") else ""
        typ = f" · {j['job_type']}"   if j.get("job_type") else ""
        dt  = f" · {j['posted_at']}"  if j.get("posted_at") else ""
        lines.append(
            f"*{i}. {j['title']}*\n"
            f"   🏢 {j['company']}{sal}\n"
            f"   📍 {j['location']}{typ}{dt}\n"
            f"   🔗 [{j['source']}]({j['url']})\n"
        )
    return "\n".join(lines)


# ── Module-level tailor runner (avoids inner-function scoping issues) ──────────

async def _run_tailor(msg: Message, uid: int) -> None:
    """Read tailor params from STATE, call backend, display result, clean up."""
    state = STATE.get(uid, {})
    try:
        result = await api_post("/resume/tailor", {
            "resume_text":     state.get("resume_text", ""),
            "job_description": state.get("jd_text", "") or state.get("auto_jd", ""),
            "job_title":       state.get("job_title", ""),
            "company":         state.get("company", ""),
        })
        await send_long(msg, result.get("text", "No result."))
    except Exception as e:
        await msg.answer(f"❌ Tailor error: {e}")
    STATE.pop(uid, None)
    await msg.answer("Done! Back to main menu 👇", reply_markup=main_menu())


# ── Scheduler tasks ────────────────────────────────────────────────────────────

async def daily_digest(bot: Bot) -> None:
    """9 AM – push new jobs to every user with saved searches."""
    logger.info("Running daily digest...")
    for uid in db.get_all_active_users():
        try:
            searches = db.get_saved_searches(uid)
            if not searches:
                continue
            new_jobs: list[dict] = []
            for s in searches:
                data = await api_post("/jobs/search", {
                    "role":        s["role"],
                    "location":    s["location"],
                    "limit":       s.get("limit_", 5),
                    "telegram_id": uid,
                    "new_only":    True,
                })
                new_jobs.extend(data.get("jobs", []))
            if new_jobs:
                await bot.send_message(
                    uid,
                    f"🌅 *Good morning! Daily digest – {date.today()}*\n\n"
                    + fmt_jobs(new_jobs[:10]),
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            else:
                await bot.send_message(
                    uid,
                    "☀️ *Daily digest:* No new jobs today. Check back tomorrow!",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"Digest error uid={uid}: {e}")


async def followup_check(bot: Bot) -> None:
    """9:05 AM – remind users about overdue follow-ups."""
    for uid in db.get_all_active_users():
        try:
            for app in db.get_followup_due(uid):
                await bot.send_message(
                    uid,
                    f"⏰ *Follow-up reminder!*\n\n"
                    f"Have you followed up with:\n"
                    f"🏢 *{app['company']}* – {app['role']}\n"
                    f"📅 Applied: {app['applied_date']}\n\n"
                    f"Reply `/update {app['id']} Interviewed` to update status.",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"Reminder uid={uid}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN missing in .env")

    bot = Bot(token=settings.telegram_bot_token)
    dp  = Dispatcher()

    # ── Scheduler ──────────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone=settings.daily_digest_timezone)
    scheduler.add_job(daily_digest,   "cron",
                      hour=settings.daily_digest_hour, minute=0,  args=[bot])
    scheduler.add_job(followup_check, "cron",
                      hour=settings.daily_digest_hour, minute=5,  args=[bot])
    scheduler.start()
    logger.info(f"Scheduler ready – digest at {settings.daily_digest_hour}:00 "
                f"{settings.daily_digest_timezone}")

    # ══════════════════════════════════════════════════════════════════════════
    # COMMANDS
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(CommandStart())
    async def cmd_start(msg: Message) -> None:
        uid = msg.from_user.id
        db.upsert_user(uid, msg.from_user.full_name or "")
        STATE.pop(uid, None)
        await msg.answer(
            "👋 *Welcome to Job Hunter PA!*\n\n"
            "I search jobs from *5 sources*, tailor your resume with keyword analysis, "
            "prep interviews, track applications, and send outreach emails — all here.\n\n"
            "Choose an option 👇",
            parse_mode="Markdown",
            reply_markup=main_menu(),
        )

    @dp.message(Command("help"))
    async def cmd_help(msg: Message) -> None:
        await msg.answer(
            "*📋 All Commands*\n\n"
            "*🔍 Jobs*\n"
            "/jobs – search jobs (5 sources)\n"
            "/digest – save search for daily 9 AM digest\n\n"
            "*📄 Resume*\n"
            "/resume – upload PDF & revise with AI\n"
            "/tailor – tailor to a specific job description\n\n"
            "*📧 Email*\n"
            "/email – draft any email\n"
            "/outreach – cold outreach + Gmail send\n"
            "/gmail\\_connect – link your Gmail account\n"
            "/gmail\\_status – check connection\n"
            "/gmail\\_disconnect – unlink Gmail\n\n"
            "*📊 Applications*\n"
            "/track – add application manually\n"
            "/myapps – view your pipeline summary\n"
            "/update ID STATUS – e.g. /update 3 Interviewed\n"
            "/export – download colour-coded Excel tracker\n\n"
            "*🎤 Interview*\n"
            "/interview – full prep guide\n"
            "/practice – live 5-question mock interview\n\n"
            "*⭐ STAR Stories*\n"
            "/addstar – save a STAR story for interviews\n"
            "/mystars – list all saved stories\n\n"
            "/stop – cancel current action\n"
            "/status – check backend health\n",
            parse_mode="Markdown",
        )

    @dp.message(Command("status"))
    async def cmd_status(msg: Message) -> None:
        try:
            data = await api_get("/health")
            await msg.answer(f"✅ Backend online – v{data.get('version','?')}")
        except Exception as e:
            await msg.answer(f"❌ Backend unreachable: {e}")

    @dp.message(Command("stop"))
    async def cmd_stop(msg: Message) -> None:
        STATE.pop(msg.from_user.id, None)
        PRACTICE.pop(msg.from_user.id, None)
        await msg.answer("✋ Cancelled. Back to main menu.", reply_markup=main_menu())

    # ══════════════════════════════════════════════════════════════════════════
    # 1. JOB SEARCH
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(F.text == "1. See jobs available")
    @dp.message(Command("jobs"))
    async def start_jobs(msg: Message) -> None:
        STATE[msg.from_user.id] = {"step": "jobs_role"}
        await msg.answer(
            "🔍 *Job Search*\n\nWhat role are you looking for?\n"
            "_e.g. Data Analyst, Business Analyst, Software Engineer_",
            parse_mode="Markdown",
        )

    @dp.message(Command("digest"))
    async def cmd_digest(msg: Message) -> None:
        STATE[msg.from_user.id] = {"step": "digest_role"}
        await msg.answer(
            "📬 *Save Daily Search*\n\n"
            "What role should I search every morning?\n"
            "_I'll push only NEW jobs at 9 AM Singapore time._",
            parse_mode="Markdown",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 2. RESUME
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(F.text == "2. Revise resume")
    @dp.message(Command("resume"))
    async def start_resume(msg: Message) -> None:
        uid     = msg.from_user.id
        existing = db.get_master_resume(uid)
        if existing:
            STATE[uid] = {"step": "resume_have_existing"}
            await msg.answer(
                "📄 I have your stored resume. What would you like to do?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Revise stored resume",
                                          callback_data="resume_use_existing")],
                    [InlineKeyboardButton(text="📤 Upload new PDF",
                                          callback_data="resume_upload_new")],
                ]),
            )
        else:
            STATE[uid] = {"step": "resume_await_pdf"}
            await msg.answer(
                "📄 *Upload your resume*\n\nSend me your resume as a *PDF file*.",
                parse_mode="Markdown",
            )

    @dp.message(Command("tailor"))
    async def cmd_tailor(msg: Message) -> None:
        uid    = msg.from_user.id
        resume = db.get_master_resume(uid)
        if resume:
            STATE[uid] = {"step": "tailor_jd", "resume_text": resume}
            await msg.answer(
                "🎯 *Resume Tailor*\n\n"
                "✅ Using your stored resume.\n\n"
                "Paste the *full job description* (copy everything from the posting):",
                parse_mode="Markdown",
            )
        else:
            STATE[uid] = {"step": "tailor_await_pdf"}
            await msg.answer(
                "🎯 *Resume Tailor*\n\nFirst upload your resume as a PDF.",
                parse_mode="Markdown",
            )

    # ══════════════════════════════════════════════════════════════════════════
    # 3. EMAIL
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(F.text == "3. Draft email")
    @dp.message(Command("email"))
    async def start_email(msg: Message) -> None:
        await msg.answer(
            "📧 *Email type:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📩 General / follow-up",
                                      callback_data="email_general")],
                [InlineKeyboardButton(text="📨 Cold outreach",
                                      callback_data="email_outreach_start")],
                [InlineKeyboardButton(text="🙏 Thank you (post-interview)",
                                      callback_data="email_thankyou")],
            ]),
        )

    @dp.message(Command("outreach"))
    async def cmd_outreach(msg: Message) -> None:
        STATE[msg.from_user.id] = {"step": "outreach_details"}
        await msg.answer(
            "📨 *Cold Outreach*\n\n"
            "Send one line:\n"
            "`to@email.com || Recipient Name || Role || Company`\n\n"
            "Example:\n`hr@google.com || Sarah Tan || Data Analyst || Google`",
            parse_mode="Markdown",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 4. TRACK
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(F.text == "4. Track application")
    @dp.message(Command("track"))
    async def start_track(msg: Message) -> None:
        STATE[msg.from_user.id] = {"step": "track_company"}
        await msg.answer("📊 *Track Application*\n\nCompany name?",
                         parse_mode="Markdown")

    @dp.message(Command("myapps"))
    async def cmd_myapps(msg: Message) -> None:
        uid = msg.from_user.id
        try:
            data = await api_get(f"/applications/{uid}")
            apps = data.get("applications", [])
            if not apps:
                await msg.answer(
                    "📊 No applications tracked yet.\n\n"
                    "Use '4. Track application' to add one."
                )
                return
            from collections import Counter
            counts = Counter(a["status"] for a in apps)
            icons  = {"Applied": "📤", "Interviewed": "🎤", "Offered": "🎉",
                      "Rejected": "❌", "Withdrawn": "↩️"}
            lines  = [f"📊 *Your Pipeline ({len(apps)} total)*\n"]
            for status, n in sorted(counts.items()):
                lines.append(f"{icons.get(status, '•')} {status}: {n}")
            lines.append("\n*Last 5:*")
            for a in apps[:5]:
                fd     = a.get("followup_date", "")
                flag   = ""
                if fd and a["status"] == "Applied":
                    delta = (date.fromisoformat(fd) - date.today()).days
                    flag  = (" ⚠️ overdue" if delta < 0 else
                             " ⏰ today"   if delta == 0 else "")
                lines.append(
                    f"• *{a['company']}* – {a['role']} "
                    f"[{a['status']}] {a.get('applied_date','')}{flag}"
                )
            lines.append("\n_/export → Excel tracker_")
            await msg.answer("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            await msg.answer(f"❌ Error: {e}")

    @dp.message(Command("update"))
    async def cmd_update(msg: Message) -> None:
        parts = (msg.text or "").replace("/update", "").strip().split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            await msg.answer("Usage: `/update APP_ID STATUS`\nExample: `/update 3 Interviewed`",
                             parse_mode="Markdown")
            return
        try:
            await api_post(f"/applications/update/{parts[0]}",
                           {"status": parts[1].strip().capitalize()})
            await msg.answer(f"✅ Application #{parts[0]} → *{parts[1].strip().capitalize()}*",
                             parse_mode="Markdown")
        except Exception as e:
            await msg.answer(f"❌ Error: {e}")

    @dp.message(Command("export"))
    async def cmd_export(msg: Message) -> None:
        await msg.answer("⏳ Building your Excel tracker...")
        try:
            xlsx = await api_bytes(f"/applications/export/{msg.from_user.id}")
            await msg.answer_document(
                document=("job_applications.xlsx", xlsx),
                caption=(
                    "📊 *Job Application Tracker*\n\n"
                    "• Sheet 1 – Applications (colour-coded by status)\n"
                    "• Sheet 2 – Dashboard (pipeline stats)\n\n"
                    "_Open in Excel or Google Sheets_"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            await msg.answer(f"❌ Export failed: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # 5. INTERVIEW
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(F.text == "5. Prepare for interviews")
    @dp.message(Command("interview"))
    async def start_interview(msg: Message) -> None:
        STATE[msg.from_user.id] = {"step": "interview_role"}
        await msg.answer("🎤 *Interview Prep*\n\nWhat role are you interviewing for?",
                         parse_mode="Markdown")

    @dp.message(Command("practice"))
    async def cmd_practice(msg: Message) -> None:
        STATE[msg.from_user.id] = {"step": "practice_role"}
        await msg.answer(
            "🎯 *Mock Interview*\n\n"
            "5 questions with AI feedback on each answer.\n"
            "Type /stop to exit early.\n\n"
            "What role are you practising for?",
            parse_mode="Markdown",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # STAR STORIES
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(Command("addstar"))
    async def cmd_addstar(msg: Message) -> None:
        STATE[msg.from_user.id] = {"step": "star_title"}
        await msg.answer(
            "⭐ *Add STAR Story*\n\n"
            "Saved stories are surfaced during interview prep.\n\n"
            "Give this story a short title:\n"
            "_e.g. 'Led RFM analysis at Science Centre'_",
            parse_mode="Markdown",
        )

    @dp.message(Command("mystars"))
    async def cmd_mystars(msg: Message) -> None:
        uid     = msg.from_user.id
        stories = db.get_star_stories(uid)
        if not stories:
            await msg.answer("⭐ No STAR stories yet. Use /addstar to add one.")
            return
        lines = [f"⭐ *Your STAR Stories ({len(stories)})*\n"]
        for i, s in enumerate(stories, 1):
            lines.append(
                f"*{i}. {s['title']}*\n"
                f"   🏷️ {s.get('themes','')}\n"
                f"   📈 {(s.get('result') or '')[:80]}...\n"
            )
        lines.append("_/addstar to add more_")
        await send_long(msg, "\n".join(lines))

    # ══════════════════════════════════════════════════════════════════════════
    # GMAIL
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(Command("gmail_connect"))
    async def cmd_gmail_connect(msg: Message) -> None:
        try:
            data = await api_get(f"/gmail/connect-link?telegram_id={msg.from_user.id}")
            await msg.answer(
                f"🔗 [Tap here to connect Gmail]({data['connect_url']})\n\n"
                "_After approving, return to Telegram. "
                "I'll send emails on your behalf._",
                parse_mode="Markdown",
            )
        except Exception as e:
            await msg.answer(f"❌ Gmail not configured: {e}")

    @dp.message(Command("gmail_status"))
    async def cmd_gmail_status(msg: Message) -> None:
        try:
            data = await api_get(f"/gmail/status/{msg.from_user.id}")
            if data["connected"]:
                await msg.answer(f"✅ Gmail connected: *{data['email']}*",
                                 parse_mode="Markdown")
            else:
                await msg.answer("❌ Not connected. Use /gmail\\_connect",
                                 parse_mode="Markdown")
        except Exception as e:
            await msg.answer(f"❌ Error: {e}")

    @dp.message(Command("gmail_disconnect"))
    async def cmd_gmail_disconnect(msg: Message) -> None:
        try:
            await api_post(f"/gmail/disconnect/{msg.from_user.id}", {})
            await msg.answer("✅ Gmail disconnected.")
        except Exception as e:
            await msg.answer(f"❌ Error: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # PDF UPLOAD
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(F.document)
    async def handle_pdf(msg: Message) -> None:
        uid  = msg.from_user.id
        doc  = msg.document
        if not doc:
            return
        fname = (doc.file_name or "").lower()
        mime  = (doc.mime_type  or "").lower()
        if not (fname.endswith(".pdf") or mime == "application/pdf"):
            await msg.answer("⚠️ Please send a PDF file (.pdf).")
            return

        await msg.answer("⏳ Reading your PDF...")
        try:
            tf  = await bot.get_file(doc.file_id)
            buf = io.BytesIO()
            await bot.download_file(tf.file_path, destination=buf)
            pdf_bytes = buf.getvalue()
        except Exception as e:
            await msg.answer(f"❌ Download failed: {e}")
            return

        text = extract_text_from_pdf(pdf_bytes)
        if not text or len(text) < 50:
            await msg.answer(
                "❌ Could not extract text.\n\n"
                "Make sure it's a text-based PDF (not a scanned image). "
                "You can also paste your resume as plain text."
            )
            return

        PDF_STORE[uid] = pdf_bytes
        step = STATE.get(uid, {}).get("step", "")

        if step in ("resume_await_pdf", "resume_upload_new"):
            db.save_master_resume(uid, text)
            STATE[uid] = {"step": "resume_target_role", "resume_text": text}
            await msg.answer(
                f"✅ Resume saved! ({len(text.split())} words extracted)\n\n"
                "What role are you targeting?\n_e.g. Data Analyst_",
                parse_mode="Markdown",
            )
        elif step == "tailor_await_pdf":
            db.save_master_resume(uid, text)
            STATE[uid] = {"step": "tailor_jd", "resume_text": text}
            await msg.answer(
                "✅ Resume saved!\n\nNow paste the *full job description*:",
                parse_mode="Markdown",
            )
        elif step == "outreach_await_pdf":
            pending = STATE.get(uid, {})
            pending["resume_bytes_b64"] = base64.b64encode(pdf_bytes).decode()
            pending["step"] = "outreach_confirm_send"
            STATE[uid] = pending
            await msg.answer(
                "✅ Resume ready.\n\nSend this outreach email now?",
                reply_markup=yn_kb("outreach_send_confirmed", "outreach_cancel"),
            )
        else:
            db.save_master_resume(uid, text)
            await msg.answer(
                f"✅ Resume saved! ({len(text.split())} words)\n\nWhat would you like to do?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Revise it",
                                          callback_data="resume_use_existing")],
                    [InlineKeyboardButton(text="🎯 Tailor to a job",
                                          callback_data="tailor_from_stored")],
                    [InlineKeyboardButton(text="📨 Send outreach",
                                          callback_data="email_outreach_start")],
                ]),
            )

    # ══════════════════════════════════════════════════════════════════════════
    # CALLBACK QUERIES
    # ══════════════════════════════════════════════════════════════════════════

    # ── Resume ────────────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "resume_use_existing")
    async def cb_resume_use(cb: CallbackQuery) -> None:
        uid    = cb.from_user.id
        resume = db.get_master_resume(uid)
        if not resume:
            await cb.message.answer("No stored resume. Please upload a PDF.")
        else:
            STATE[uid] = {"step": "resume_target_role", "resume_text": resume}
            await cb.message.answer("What role are you targeting?\n_e.g. Data Analyst_",
                                    parse_mode="Markdown")
        await cb.answer()

    @dp.callback_query(F.data == "resume_upload_new")
    async def cb_resume_new(cb: CallbackQuery) -> None:
        STATE[cb.from_user.id] = {"step": "resume_upload_new"}
        await cb.message.answer("📤 Send your updated resume as a PDF.")
        await cb.answer()

    @dp.callback_query(F.data == "tailor_from_stored")
    async def cb_tailor_stored(cb: CallbackQuery) -> None:
        uid    = cb.from_user.id
        resume = db.get_master_resume(uid)
        if resume:
            STATE[uid] = {"step": "tailor_jd", "resume_text": resume}
            await cb.message.answer("Paste the *job description* below:",
                                    parse_mode="Markdown")
        else:
            STATE[uid] = {"step": "tailor_await_pdf"}
            await cb.message.answer("Please upload your resume PDF first.")
        await cb.answer()

    # ── Email ─────────────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "email_general")
    async def cb_email_general(cb: CallbackQuery) -> None:
        STATE[cb.from_user.id] = {"step": "email_purpose"}
        await cb.message.answer(
            "What's the *purpose* of this email?\n"
            "_e.g. follow up on my application, check interview timeline_",
            parse_mode="Markdown",
        )
        await cb.answer()

    @dp.callback_query(F.data == "email_outreach_start")
    async def cb_email_outreach(cb: CallbackQuery) -> None:
        STATE[cb.from_user.id] = {"step": "outreach_details"}
        await cb.message.answer(
            "📨 *Cold Outreach*\n\n"
            "One line:\n`email || Name || Role || Company`",
            parse_mode="Markdown",
        )
        await cb.answer()

    @dp.callback_query(F.data == "email_thankyou")
    async def cb_email_ty(cb: CallbackQuery) -> None:
        STATE[cb.from_user.id] = {
            "step": "email_purpose",
            "purpose_preset": "thank you after job interview",
        }
        await cb.message.answer("Who interviewed you? _(their name)_",
                                parse_mode="Markdown")
        await cb.answer()

    # ── Outreach ──────────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "outreach_send_confirmed")
    async def cb_outreach_send(cb: CallbackQuery) -> None:
        uid   = cb.from_user.id
        state = STATE.get(uid, {})
        await cb.message.answer("📤 Sending via Gmail...")
        try:
            r = await api_post("/email/outreach", {**state, "send_now": True})
            if r.get("sent"):
                await cb.message.answer("✅ Outreach email sent!")
                db.log_email(uid, state.get("to_email",""), state.get("recipient_name",""),
                             state.get("company",""), state.get("role",""),
                             r.get("subject",""), r.get("body",""),
                             True, str(date.today() + timedelta(days=7)))
                STATE[uid] = {"step": "track_after_outreach",
                              "company": state.get("company",""),
                              "role":    state.get("role","")}
                await cb.message.answer(
                    f"Track this application to *{state.get('company','')}*?",
                    parse_mode="Markdown",
                    reply_markup=yn_kb("track_auto_yes", "track_auto_no"),
                )
            else:
                await cb.message.answer(
                    "❌ Send failed. Is Gmail connected? /gmail\\_connect",
                    parse_mode="Markdown",
                )
        except Exception as e:
            await cb.message.answer(f"❌ Error: {e}")
        await cb.answer()

    @dp.callback_query(F.data == "outreach_cancel")
    async def cb_outreach_cancel(cb: CallbackQuery) -> None:
        STATE.pop(cb.from_user.id, None)
        await cb.message.answer("Cancelled.", reply_markup=main_menu())
        await cb.answer()

    @dp.callback_query(F.data == "track_auto_yes")
    async def cb_track_yes(cb: CallbackQuery) -> None:
        uid   = cb.from_user.id
        state = STATE.get(uid, {})
        try:
            r = await api_post("/applications/add", {
                "telegram_id": uid,
                "company": state.get("company","Unknown"),
                "role":    state.get("role","Unknown"),
                "status":  "Applied",
            })
            await cb.message.answer(
                f"✅ Tracked! Follow-up: *{r.get('followup_date','')}*",
                parse_mode="Markdown",
            )
        except Exception as e:
            await cb.message.answer(f"❌ Error: {e}")
        STATE.pop(uid, None)
        await cb.message.answer("Back to main menu 👇", reply_markup=main_menu())
        await cb.answer()

    @dp.callback_query(F.data == "track_auto_no")
    async def cb_track_no(cb: CallbackQuery) -> None:
        STATE.pop(cb.from_user.id, None)
        await cb.message.answer("OK! 👇", reply_markup=main_menu())
        await cb.answer()

    # ── Track status ──────────────────────────────────────────────────────────
    @dp.callback_query(F.data.startswith("track_status_"))
    async def cb_track_status(cb: CallbackQuery) -> None:
        uid    = cb.from_user.id
        status = cb.data.replace("track_status_", "")
        state  = STATE.get(uid, {})
        try:
            r = await api_post("/applications/add", {
                "telegram_id": uid,
                "company": state.get("company","Unknown"),
                "role":    state.get("role","Unknown"),
                "status":  status,
                "url":     state.get("url",""),
                "salary":  state.get("salary",""),
                "source":  state.get("source",""),
            })
            await cb.message.answer(
                f"✅ *Tracked!*\n"
                f"🏢 {state.get('company','')} – {state.get('role','')}\n"
                f"📊 {status} | ⏰ Follow-up: {r.get('followup_date','')}",
                parse_mode="Markdown",
            )
        except Exception as e:
            await cb.message.answer(f"❌ Error: {e}")
        STATE.pop(uid, None)
        await cb.message.answer("Back to main menu 👇", reply_markup=main_menu())
        await cb.answer()

    # ── Job selection ─────────────────────────────────────────────────────────
    @dp.callback_query(F.data.startswith("select_job_"))
    async def cb_select_job(cb: CallbackQuery) -> None:
        uid  = cb.from_user.id
        idx  = int(cb.data.split("_")[-1]) - 1
        jobs = JOBS_CACHE.get(uid, [])
        if idx < 0 or idx >= len(jobs):
            await cb.answer("Invalid selection.")
            return
        job = jobs[idx]
        STATE[uid] = {"step": "job_action", "job": job}
        sal = f"\n💰 {job['salary']}" if job.get("salary") else ""
        await cb.message.answer(
            f"*{job['title']}*\n🏢 {job['company']}{sal}\n\nWhat would you like to do?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Tailor my resume",
                                      callback_data="job_do_tailor")],
                [InlineKeyboardButton(text="📊 Track application",
                                      callback_data="job_do_track")],
                [InlineKeyboardButton(text="📨 Send outreach",
                                      callback_data="job_do_outreach")],
                [InlineKeyboardButton(text="🎤 Interview prep",
                                      callback_data="job_do_interview")],
            ]),
        )
        await cb.answer()

    @dp.callback_query(F.data == "job_do_tailor")
    async def cb_job_tailor(cb: CallbackQuery) -> None:
        uid    = cb.from_user.id
        job    = STATE.get(uid, {}).get("job", {})
        resume = db.get_master_resume(uid)
        auto_jd = job.get("description", "")
        if not resume:
            STATE[uid] = {"step": "tailor_await_pdf",
                          "job_title": job.get("title",""),
                          "company":   job.get("company","")}
            await cb.message.answer("Please upload your resume PDF first.")
        elif auto_jd:
            STATE[uid] = {"resume_text": resume,
                          "job_title":   job.get("title",""),
                          "company":     job.get("company",""),
                          "jd_text":     auto_jd}
            await cb.message.answer("⏳ Tailoring your resume...")
            await _run_tailor(cb.message, uid)
        else:
            STATE[uid] = {"step": "tailor_jd",
                          "resume_text": resume,
                          "job_title":   job.get("title",""),
                          "company":     job.get("company","")}
            await cb.message.answer("Paste the *full job description* for this role:",
                                    parse_mode="Markdown")
        await cb.answer()

    @dp.callback_query(F.data == "job_do_track")
    async def cb_job_track(cb: CallbackQuery) -> None:
        uid = cb.from_user.id
        job = STATE.get(uid, {}).get("job", {})
        try:
            r = await api_post("/applications/add", {
                "telegram_id": uid,
                "company": job.get("company","Unknown"),
                "role":    job.get("title","Unknown"),
                "status":  "Applied",
                "url":     job.get("url",""),
                "salary":  job.get("salary",""),
                "source":  job.get("source",""),
            })
            await cb.message.answer(
                f"✅ Tracked! Follow-up: *{r.get('followup_date','')}*",
                parse_mode="Markdown",
            )
        except Exception as e:
            await cb.message.answer(f"❌ Error: {e}")
        await cb.answer()

    @dp.callback_query(F.data == "job_do_outreach")
    async def cb_job_outreach(cb: CallbackQuery) -> None:
        uid = cb.from_user.id
        job = STATE.get(uid, {}).get("job", {})
        STATE[uid] = {"step":           "outreach_details",
                      "prefill_company": job.get("company",""),
                      "prefill_role":    job.get("title","")}
        await cb.message.answer(
            f"📨 Outreach for *{job.get('title','')}* at *{job.get('company','')}*\n\n"
            "Send:\n`email || Recipient Name`\n_(role and company are pre-filled)_",
            parse_mode="Markdown",
        )
        await cb.answer()

    @dp.callback_query(F.data == "job_do_interview")
    async def cb_job_interview(cb: CallbackQuery) -> None:
        uid = cb.from_user.id
        job = STATE.get(uid, {}).get("job", {})
        await cb.message.answer(
            f"⏳ Building interview guide for *{job.get('title','')}* "
            f"at *{job.get('company','')}*...",
            parse_mode="Markdown",
        )
        try:
            r = await api_post("/interview/prepare", {
                "role":        job.get("title",""),
                "company":     job.get("company",""),
                "focus_areas": [],
            })
            await send_long(cb.message, r.get("text",""))
        except Exception as e:
            await cb.message.answer(f"❌ Error: {e}")
        await cb.answer()

    # ── Outreach send-now check ───────────────────────────────────────────────
    @dp.callback_query(F.data == "outreach_do_send_check")
    async def cb_outreach_do_send(cb: CallbackQuery) -> None:
        uid   = cb.from_user.id
        state = STATE.get(uid, {})
        # Verify Gmail connected
        try:
            gd = await api_get(f"/gmail/status/{uid}")
            ok = gd.get("connected", False)
        except Exception:
            ok = False
        if not ok:
            await cb.message.answer(
                "❌ Gmail not connected. Use /gmail\\_connect first.",
                parse_mode="Markdown",
            )
            await cb.answer()
            return
        pdf = PDF_STORE.get(uid)
        if not pdf:
            STATE[uid] = {**state, "step": "outreach_await_pdf"}
            await cb.message.answer(
                "📎 Please upload your resume PDF to attach to the email."
            )
        else:
            state["resume_bytes_b64"] = base64.b64encode(pdf).decode()
            state["send_now"] = True
            await cb.message.answer("📤 Sending...")
            try:
                r = await api_post("/email/outreach", state)
                if r.get("sent"):
                    await cb.message.answer("✅ Outreach email sent!")
                    db.log_email(uid, state.get("to_email",""),
                                 state.get("recipient_name",""),
                                 state.get("company",""), state.get("role",""),
                                 r.get("subject",""), r.get("body",""),
                                 True, str(date.today() + timedelta(days=7)))
                else:
                    await cb.message.answer(
                        "❌ Send failed. Check Gmail connection with /gmail\\_status",
                        parse_mode="Markdown",
                    )
            except Exception as e:
                await cb.message.answer(f"❌ Error: {e}")
            STATE.pop(uid, None)
        await cb.answer()

    # ══════════════════════════════════════════════════════════════════════════
    # TEXT STATE MACHINE
    # ══════════════════════════════════════════════════════════════════════════

    @dp.message(F.text)
    async def handle_text(msg: Message) -> None:
        uid   = msg.from_user.id
        text  = msg.text.strip()
        state = STATE.get(uid, {})
        step  = state.get("step", "")

        # ── Job search ──────────────────────────────────────────────────────
        if step == "jobs_role":
            STATE[uid] = {**state, "step": "jobs_location", "role": text}
            await msg.answer("📍 Location?\n_Singapore / Remote / Worldwide_",
                             parse_mode="Markdown")

        elif step == "jobs_location":
            STATE[uid] = {**state, "step": "jobs_limit", "location": text}
            await msg.answer("How many results? _(1–20, default 10)_",
                             parse_mode="Markdown")

        elif step == "jobs_limit":
            try:
                limit = max(1, min(20, int(text)))
            except ValueError:
                limit = 10
            role = state.get("role", "")
            loc  = state.get("location", "singapore")
            await msg.answer(
                f"🔍 Searching *{limit}* jobs for *{role}* in *{loc}*...\n"
                "_Checking 5 sources in parallel..._",
                parse_mode="Markdown",
            )
            try:
                data = await api_post("/jobs/search", {
                    "role": role, "location": loc,
                    "limit": limit, "telegram_id": uid,
                })
                jobs = data.get("jobs", [])
                JOBS_CACHE[uid] = jobs
                await send_long(msg, fmt_jobs(jobs), pm="Markdown")
                if jobs:
                    buttons = [
                        [InlineKeyboardButton(
                            text=f"{i}. {j['title'][:28]}… @ {j['company'][:18]}",
                            callback_data=f"select_job_{i}",
                        )]
                        for i, j in enumerate(jobs[:10], 1)
                    ]
                    await msg.answer(
                        "👆 Select a job to tailor, track, or prep interview:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                    )
            except Exception as e:
                await msg.answer(f"❌ Search error: {e}")
            STATE.pop(uid, None)

        # ── Digest ──────────────────────────────────────────────────────────
        elif step == "digest_role":
            STATE[uid] = {**state, "step": "digest_location", "role": text}
            await msg.answer("📍 Location? _(Singapore / Remote)_",
                             parse_mode="Markdown")

        elif step == "digest_location":
            role = state.get("role", "")
            db.save_search_profile(uid, f"{role} in {text}", role, text)
            STATE.pop(uid, None)
            await msg.answer(
                f"✅ Saved! Every morning at *{settings.daily_digest_hour}:00 AM* "
                f"({settings.daily_digest_timezone}) I'll push new *{role}* jobs in *{text}*.",
                parse_mode="Markdown",
            )

        # ── Resume revise ───────────────────────────────────────────────────
        elif step == "resume_target_role":
            resume = state.get("resume_text", "")
            await msg.answer("⏳ Analysing your resume...")
            try:
                r = await api_post("/resume/revise", {
                    "resume_text": resume,
                    "target_role": text,
                    "telegram_id": uid,
                })
                await send_long(msg, r.get("text",""))
            except Exception as e:
                await msg.answer(f"❌ Error: {e}")
            STATE.pop(uid, None)
            await msg.answer("Done! Back to main menu 👇", reply_markup=main_menu())

        # ── Resume tailor ───────────────────────────────────────────────────
        elif step == "tailor_jd":
            STATE[uid] = {**state, "step": "tailor_job_title", "jd_text": text}
            await msg.answer("Job title for this role?\n_e.g. Data Analyst_",
                             parse_mode="Markdown")

        elif step == "tailor_job_title":
            STATE[uid] = {**state, "step": "tailor_company", "job_title": text}
            await msg.answer("Company name?")

        elif step == "tailor_company":
            STATE[uid] = {**state, "company": text}
            await msg.answer("⏳ Tailoring your resume... _(~15 seconds)_",
                             parse_mode="Markdown")
            await _run_tailor(msg, uid)

        # ── Email general ───────────────────────────────────────────────────
        elif step == "email_purpose":
            preset  = state.get("purpose_preset", "")
            purpose = preset or text
            STATE[uid] = {**state, "step": "email_recipient", "purpose": purpose}
            await msg.answer("Recipient's name?")

        elif step == "email_recipient":
            STATE[uid] = {**state, "step": "email_context", "recipient_name": text}
            await msg.answer(
                "Any extra context?\n"
                "_e.g. applied via LinkedIn last week, met at NUS career fair_",
                parse_mode="Markdown",
            )

        elif step == "email_context":
            await msg.answer("⏳ Drafting email...")
            try:
                r = await api_post("/email/draft", {
                    "purpose":        state.get("purpose",""),
                    "recipient_name": state.get("recipient_name",""),
                    "context":        text,
                    "tone":           "professional",
                })
                await send_long(msg, r.get("text",""))
            except Exception as e:
                await msg.answer(f"❌ Error: {e}")
            STATE.pop(uid, None)
            await msg.answer("Done! Back to main menu 👇", reply_markup=main_menu())

        # ── Outreach ────────────────────────────────────────────────────────
        elif step == "outreach_details":
            parts          = [p.strip() for p in text.split("||")]
            prefill_co     = state.get("prefill_company","")
            prefill_role   = state.get("prefill_role","")
            if len(parts) < 2:
                await msg.answer("Format: `email || Name || Role || Company`",
                                 parse_mode="Markdown")
                return
            to_email = parts[0]
            to_name  = parts[1]
            role     = parts[2] if len(parts) > 2 else prefill_role
            company  = parts[3] if len(parts) > 3 else prefill_co
            if not role or not company:
                await msg.answer("Missing role or company.\n"
                                 "Format: `email || Name || Role || Company`",
                                 parse_mode="Markdown")
                return
            kws = ""
            stored = db.get_master_resume(uid)
            if stored:
                kws = ", ".join(extract_keywords(stored)[:12])
            await msg.answer("⏳ Drafting outreach email...")
            try:
                r = await api_post("/email/outreach", {
                    "telegram_id":       uid,
                    "to_email":          to_email,
                    "recipient_name":    to_name,
                    "role":              role,
                    "company":           company,
                    "sender_name":       msg.from_user.full_name or "Candidate",
                    "resume_highlights": kws,
                    "send_now":          False,
                })
                subject = r.get("subject","")
                body    = r.get("body","")
                await send_long(msg,
                    f"📧 *Draft:*\n\n*Subject:* {subject}\n\n{body}")
                STATE[uid] = {
                    "step":            "outreach_confirm",
                    "telegram_id":     uid,
                    "to_email":        to_email,
                    "recipient_name":  to_name,
                    "role":            role,
                    "company":         company,
                    "sender_name":     msg.from_user.full_name or "",
                    "resume_highlights": kws,
                    "subject":         subject,
                    "body":            body,
                }
                await msg.answer(
                    "Send this now via Gmail?",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Send via Gmail",
                                              callback_data="outreach_do_send_check")],
                        [InlineKeyboardButton(text="📋 Keep as draft",
                                              callback_data="outreach_cancel")],
                    ]),
                )
            except Exception as e:
                await msg.answer(f"❌ Error: {e}")
                STATE.pop(uid, None)

        # ── Track ───────────────────────────────────────────────────────────
        elif step == "track_company":
            STATE[uid] = {**state, "step": "track_role", "company": text}
            await msg.answer("Role you applied for?")

        elif step == "track_role":
            STATE[uid] = {**state, "step": "track_status", "role": text}
            await msg.answer(
                "Status?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📤 Applied",
                                          callback_data="track_status_Applied")],
                    [InlineKeyboardButton(text="🎤 Interviewed",
                                          callback_data="track_status_Interviewed")],
                    [InlineKeyboardButton(text="🎉 Offered",
                                          callback_data="track_status_Offered")],
                    [InlineKeyboardButton(text="❌ Rejected",
                                          callback_data="track_status_Rejected")],
                    [InlineKeyboardButton(text="↩️ Withdrawn",
                                          callback_data="track_status_Withdrawn")],
                ]),
            )

        # ── Interview ───────────────────────────────────────────────────────
        elif step == "interview_role":
            STATE[uid] = {**state, "step": "interview_company", "role": text}
            await msg.answer("Which company?")

        elif step == "interview_company":
            role = state.get("role","")
            await msg.answer(
                f"⏳ Building interview guide for *{role}* at *{text}*...",
                parse_mode="Markdown",
            )
            try:
                r = await api_post("/interview/prepare", {
                    "role": role, "company": text, "focus_areas": [],
                })
                await send_long(msg, r.get("text",""))
            except Exception as e:
                await msg.answer(f"❌ Error: {e}")
            STATE.pop(uid, None)
            await msg.answer("Done! Back to main menu 👇", reply_markup=main_menu())

        # ── Practice ────────────────────────────────────────────────────────
        elif step == "practice_role":
            STATE[uid] = {**state, "step": "practice_company", "role": text}
            await msg.answer("Which company?")

        elif step == "practice_company":
            role = state.get("role","")
            await msg.answer(
                f"🎯 *Mock interview:* {role} at {text}\n\n"
                "5 questions. /stop to exit early.\n\n"
                "⏳ Getting question 1...",
                parse_mode="Markdown",
            )
            from app.services.llm_tasks import practice_question
            try:
                q = await practice_question(role, text, "behavioural")
                PRACTICE[uid] = {"role": role, "company": text,
                                  "question": q, "count": 1}
                STATE[uid]    = {"step": "practice_answer"}
                await msg.answer(f"❓ *Question 1 of 5:*\n\n{q}",
                                 parse_mode="Markdown")
            except Exception as e:
                await msg.answer(f"❌ Error: {e}")
                STATE.pop(uid, None)

        elif step == "practice_answer":
            ctx   = PRACTICE.get(uid, {})
            count = ctx.get("count", 1)
            await msg.answer("📝 Evaluating...")
            from app.services.llm_tasks import evaluate_answer, practice_question
            try:
                fb = await evaluate_answer(ctx.get("question",""), text,
                                           ctx.get("role",""))
                await send_long(msg, fb)
                if count < 5:
                    q_type = "technical" if count % 2 == 0 else "behavioural"
                    nq = await practice_question(ctx.get("role",""),
                                                 ctx.get("company",""), q_type)
                    PRACTICE[uid] = {**ctx, "question": nq, "count": count + 1}
                    await msg.answer(
                        f"❓ *Question {count + 1} of 5:*\n\n{nq}",
                        parse_mode="Markdown",
                    )
                else:
                    await msg.answer(
                        "🎉 *Mock interview complete!* 5 questions done.\n\n"
                        "Use /practice for another round.",
                        parse_mode="Markdown",
                    )
                    STATE.pop(uid, None)
                    PRACTICE.pop(uid, None)
                    await msg.answer("Back to main menu 👇", reply_markup=main_menu())
            except Exception as e:
                await msg.answer(f"❌ Error: {e}")

        # ── STAR story ──────────────────────────────────────────────────────
        elif step == "star_title":
            STATE[uid] = {**state, "step": "star_situation", "title": text}
            await msg.answer(
                "📖 *Situation*\n\n"
                "What was the context or challenge?",
                parse_mode="Markdown",
            )

        elif step == "star_situation":
            STATE[uid] = {**state, "step": "star_task", "situation": text}
            await msg.answer(
                "🎯 *Task*\n\nWhat was YOUR specific responsibility or goal?",
                parse_mode="Markdown",
            )

        elif step == "star_task":
            STATE[uid] = {**state, "step": "star_action", "action_needed": text}
            await msg.answer(
                "⚡ *Action*\n\nWhat did YOU specifically do?\n"
                "_(Use 'I', not 'we'. Be specific.)_",
                parse_mode="Markdown",
            )

        elif step == "star_action_needed":
            STATE[uid] = {**state, "step": "star_result", "action": text}
            await msg.answer(
                "📈 *Result*\n\nWhat was the outcome?\n"
                "_(Include numbers/metrics if possible)_",
                parse_mode="Markdown",
            )

        elif step == "star_result":
            STATE[uid] = {**state, "step": "star_themes", "result": text}
            await msg.answer(
                "🏷️ *Themes* (comma-separated)\n\n"
                "_e.g. leadership, analytics, problem-solving, communication_",
                parse_mode="Markdown",
            )

        elif step == "star_themes":
            s = STATE.get(uid, {})
            db.add_star_story(
                uid,
                title=s.get("title",""),
                situation=s.get("situation",""),
                task=s.get("action_needed",""),
                action=s.get("action",""),
                result=s.get("result",""),
                themes=text,
            )
            STATE.pop(uid, None)
            await msg.answer(
                f"✅ *STAR story saved!*\n\n"
                f"📌 *{s.get('title','')}*\n"
                f"🏷️ Themes: {text}\n\n"
                "Use /mystars to see all your stories.\n"
                "Use /addstar to add another.",
                parse_mode="Markdown",
                reply_markup=main_menu(),
            )

        # ── Fallback ────────────────────────────────────────────────────────
        else:
            await msg.answer(
                "👇 Use the menu below or /help for all commands.",
                reply_markup=main_menu(),
            )

    # ══════════════════════════════════════════════════════════════════════════
    # START POLLING
    # ══════════════════════════════════════════════════════════════════════════
    print("\n" + "═" * 55)
    print("  Job Hunter PA – Telegram Bot v3 (final)")
    print(f"  Backend  : {BACKEND}")
    print(f"  Digest   : {settings.daily_digest_hour}:00 {settings.daily_digest_timezone}")
    print("═" * 55 + "\n")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
