from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # ============ Server ============
    host: str = "0.0.0.0"
    port: int = 8000

    # ============ LLM (Ollama) ============
    openclaw_api_url: str = "http://localhost:11434/v1/chat/completions"
    openclaw_api_key: str = ""
    openclaw_model: str = "mistral"  # Default Ollama model

    # ============ Job Search APIs ============
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    # ============ Notion Integration ============
    notion_api_key: str = ""
    notion_database_id: str = ""

    # ============ Telegram Bot ============
    telegram_bot_token: str = ""
    backend_base_url: str = "http://localhost:8000"

    # ============ Gmail Integration ============
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    oauth_redirect_url: str = "http://localhost:8000/oauth/gmail/callback"

    # ============ Database ============
    app_secret_key: str = "change-me-in-production"
    sqlite_db_path: str = "./data/job_hunter.db"
    database_url: str = ""  # Override SQLite if provided

    # ============ Email Automation ============
    email_followup_days: int = 3  # Follow up after N days
    email_digest_hour: int = 9  # Daily digest at 9 AM
    email_digest_timezone: str = "Asia/Singapore"

    # ============ Job Search Settings ============
    job_search_cache_hours: int = 6  # Refresh cache every 6 hours
    daily_digest_enabled: bool = True
    default_job_limit: int = 10

    # ============ Anthropic API (Optional fallback) ============
    anthropic_api_key: str = ""


settings = Settings()
