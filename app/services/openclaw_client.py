from __future__ import annotations
import httpx
from app.config import settings

class OpenClawClient:
    """
    LLM client that defaults to local Ollama (OpenClaw).
    Anthropic is available as a fallback if explicitly enabled and configured.
    """
    ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self) -> None:
        self.api_url = settings.openclaw_api_url
        self.api_key = settings.openclaw_api_key
        self.model = settings.openclaw_model or "mistral"  # Default to mistral for Ollama
        self.anthropic_key = settings.anthropic_api_key
        self.use_mock = False  # Set to True to test without real API

    def _use_anthropic(self) -> bool:
        """Only use Anthropic if explicitly enabled. Default is Ollama."""
        use_anthropic = False  # Change to True only if you want Anthropic
        local = "localhost" in self.api_url or "127.0.0.1" in self.api_url
        return use_anthropic and local and bool(self.anthropic_key)

    def _get_mock_response(self, system_prompt: str, user_prompt: str) -> str:
        """Return mock LLM response for testing without API"""
        if "resume" in user_prompt.lower() and "target_role" in user_prompt.lower():
            return """Here are key improvements for your Data Analyst resume:

**Recommendations:**
1. Add specific metrics: "Increased dashboard efficiency by 30%" instead of generic statements
2. Use keywords like: Analytics, SQL, Python, Data Mining, Predictive Modeling
3. Highlight technical tools: Power BI, Tableau, Excel, Python, R
4. Show impact with numbers: cost savings %, time reduced, accuracy improved

**Key additions for Data Analyst role:**
✓ RFM Analysis experience (you have this!)
✓ Power BI dashboard development (you have this!)
✓ Data-driven decision making examples
✓ SQL or Python for data manipulation

Your background is strong - just quantify achievements more!"""
        return "Response generated successfully (mock mode)"

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        if self.use_mock:
            return self._get_mock_response(system_prompt, user_prompt)
        if self._use_anthropic():
            return await self._complete_anthropic(system_prompt, user_prompt)
        return await self._complete_openai(system_prompt, user_prompt)

    async def _complete_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.anthropic_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self.ANTHROPIC_URL, headers=headers, json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                error_detail = response.text
                print(f"Anthropic API Error: {e.response.status_code}")
                print(f"Response: {error_detail}")
                raise
            data = response.json()
        content = data.get("content", [])
        if not content:
            return "No response received."
        return content[0].get("text", "No text in response.")

    async def _complete_openai(self, system_prompt: str, user_prompt: str) -> str:
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
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                error_msg = response.text
                print(f"Ollama API Error: {e.response.status_code}")
                print(f"URL: {self.api_url}")
                print(f"Model: {self.model}")
                print(f"Response: {error_msg}")
                raise Exception(f"Ollama returned {e.response.status_code}: {error_msg}") from e
            except httpx.ConnectError as e:
                print(f"Failed to connect to Ollama at {self.api_url}")
                print(f"Make sure Ollama is running: ollama serve")
                raise Exception(f"Cannot connect to Ollama at {self.api_url}. Is it running?") from e
            
            data = response.json()
        choices = data.get("choices", [])
        if not choices:
            return "No response received from Ollama."
        return choices[0].get("message", {}).get("content", "No content received.")

openclaw_client = OpenClawClient()
