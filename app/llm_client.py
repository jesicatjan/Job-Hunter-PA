"""
LLM client – Anthropic Claude (primary) with Ollama fallback.
All prompts go through complete() which picks the right backend.
"""
import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)


async def complete(system: str, user: str, max_tokens: int = 2048) -> str:
    """Call LLM and return text response. Claude first, Ollama fallback."""
    if settings.anthropic_api_key:
        try:
            return await _anthropic(system, user, max_tokens)
        except Exception as e:
            logger.warning(f"Anthropic failed ({e}), falling back to Ollama")
    return await _ollama(system, user)


async def _anthropic(system: str, user: str, max_tokens: int) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    return data["content"][0]["text"]


async def _ollama(system: str, user: str) -> str:
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(settings.ollama_api_url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]
