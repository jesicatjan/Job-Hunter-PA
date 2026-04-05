from __future__ import annotations

import asyncio

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.config import settings


def _help_text() -> str:
    return (
        "Job Hunter Personal Assistant\n\n"
        "Commands:\n"
        "/jobs <role> | <location> | <limit>\n"
        "/resume <target_role> || <resume_text> || <skill1,skill2>\n"
        "/email <purpose> || <recipient_name> || <context> || <tone>\n"
        "/track <company> || <role> || <status> || <link> || <notes>\n"
        "/interview <role> || <company> || <focus1,focus2>\n"
        "/help"
    )


async def api_post(path: str, payload: dict) -> dict:
    url = f"{settings.backend_base_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def api_get(path: str) -> dict:
    url = f"{settings.backend_base_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def main() -> None:
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing. Add it in .env")

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start_handler(message: Message) -> None:
        await message.answer("Welcome. " + _help_text())

    @dp.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(_help_text())

    @dp.message(Command("health"))
    async def health_handler(message: Message) -> None:
        data = await api_get("/health")
        await message.answer(f"Backend status: {data.get('status', 'unknown')}")

    @dp.message(Command("jobs"))
    async def jobs_handler(message: Message) -> None:
        try:
            raw = (message.text or "").replace("/jobs", "", 1).strip()
            role, location, limit = [x.strip() for x in raw.split("|")]
            payload = {"role": role, "location": location, "limit": int(limit)}
            data = await api_post("/jobs/search", payload)

            jobs = data.get("jobs", [])
            if not jobs:
                await message.answer("No jobs found.")
                return

            lines = ["Top jobs:"]
            for idx, job in enumerate(jobs, start=1):
                lines.append(
                    f"{idx}. {job.get('title')} at {job.get('company')}\n"
                    f"   {job.get('location')} | {job.get('type')}\n"
                    f"   {job.get('url')}"
                )
            await message.answer("\n\n".join(lines))
        except Exception:
            await message.answer("Usage: /jobs <role> | <location> | <limit>")

    @dp.message(Command("resume"))
    async def resume_handler(message: Message) -> None:
        try:
            raw = (message.text or "").replace("/resume", "", 1).strip()
            target_role, resume_text, skills_csv = [x.strip() for x in raw.split("||")]
            payload = {
                "target_role": target_role,
                "current_resume": resume_text,
                "key_skills": [s.strip() for s in skills_csv.split(",") if s.strip()],
            }
            data = await api_post("/resume/revise", payload)
            await message.answer(data.get("text", "No response."))
        except Exception:
            await message.answer("Usage: /resume <target_role> || <resume_text> || <skill1,skill2>")

    @dp.message(Command("email"))
    async def email_handler(message: Message) -> None:
        try:
            raw = (message.text or "").replace("/email", "", 1).strip()
            purpose, recipient_name, context, tone = [x.strip() for x in raw.split("||")]
            payload = {
                "purpose": purpose,
                "recipient_name": recipient_name,
                "context": context,
                "tone": tone,
            }
            data = await api_post("/email/draft", payload)
            await message.answer(data.get("text", "No response."))
        except Exception:
            await message.answer("Usage: /email <purpose> || <recipient_name> || <context> || <tone>")

    @dp.message(Command("track"))
    async def track_handler(message: Message) -> None:
        try:
            raw = (message.text or "").replace("/track", "", 1).strip()
            company, role, status, link, notes = [x.strip() for x in raw.split("||")]
            payload = {
                "company": company,
                "role": role,
                "status": status,
                "link": link or None,
                "notes": notes or None,
            }
            data = await api_post("/notion/track", payload)
            await message.answer(f"{data.get('message')} Page ID: {data.get('page_id')}")
        except Exception:
            await message.answer("Usage: /track <company> || <role> || <status> || <link> || <notes>")

    @dp.message(Command("interview"))
    async def interview_handler(message: Message) -> None:
        try:
            raw = (message.text or "").replace("/interview", "", 1).strip()
            role, company, focus_csv = [x.strip() for x in raw.split("||")]
            payload = {
                "role": role,
                "company": company,
                "focus_areas": [s.strip() for s in focus_csv.split(",") if s.strip()],
            }
            data = await api_post("/interview/prepare", payload)
            await message.answer(data.get("text", "No response."))
        except Exception:
            await message.answer("Usage: /interview <role> || <company> || <focus1,focus2>")

    @dp.message(F.text)
    async def fallback_handler(message: Message) -> None:
        await message.answer("Unknown command. Use /help")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
