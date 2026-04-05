from __future__ import annotations

from typing import Optional

from notion_client import AsyncClient

from app.config import settings


class NotionService:
    async def track_job(
        self,
        company: str,
        role: str,
        status: str,
        link: Optional[str],
        notes: Optional[str],
    ) -> tuple[str, Optional[str]]:
        if not settings.notion_api_key or not settings.notion_database_id:
            return (
                "Notion is not configured. Set NOTION_API_KEY and NOTION_DATABASE_ID.",
                None,
            )

        client = AsyncClient(auth=settings.notion_api_key)

        properties = {
            "Company": {"title": [{"text": {"content": company}}]},
            "Role": {"rich_text": [{"text": {"content": role}}]},
            "Status": {"select": {"name": status}},
        }

        if link:
            properties["Link"] = {"url": link}

        if notes:
            properties["Notes"] = {"rich_text": [{"text": {"content": notes}}]}

        response = await client.pages.create(
            parent={"database_id": settings.notion_database_id},
            properties=properties,
        )
        return "Job tracked successfully in Notion.", response.get("id")


notion_service = NotionService()
