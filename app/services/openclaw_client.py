from __future__ import annotations

import httpx

from app.config import settings


class OpenClawClient:
    def __init__(self) -> None:
        self.api_url = settings.openclaw_api_url
        self.api_key = settings.openclaw_api_key
        self.model = settings.openclaw_model

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.4,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            return "No response received from OpenClaw."

        message = choices[0].get("message", {})
        return message.get("content", "No content received from OpenClaw.")


openclaw_client = OpenClawClient()
