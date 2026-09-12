from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """PRD section 18. All configuration is environment variables; none lives in code."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://bankrecon:bankrecon@localhost:5432/bankrecon"

    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""
    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_recon_channel_id: str = ""
    slack_evidence_channel_ids: str = ""
    web_app_url: str = ""

    anthropic_api_key: str = ""
    llm_provider: Literal["anthropic", "openrouter"] = "openrouter"
    openrouter_api_key: str = ""
    openrouter_api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_model: str = "openai/gpt-5.6-luna"
    openrouter_reasoning_enabled: bool = True
    openrouter_timeout_seconds: float = 60
    openrouter_max_tokens: int = 4096
    # PRD section 18 pins claude-sonnet-4-6. Sonnet 5 is the current generation of the
    # same tier: cheaper ($2/$10 vs $3/$15 per 1M) and stronger. Override to pin back.
    anthropic_model: str = "claude-sonnet-5"

    storage_path: str = "/data/statements"

    auto_match_threshold: int = 90
    review_floor: int = 60
    ambiguity_gap: int = 5
    date_window_days: int = 5
    amount_tolerance_bps: int = 0
    approval_value_threshold_minor: int = 50_000_000

    listener_threshold: int = 55
    listener_per_case_cooldown_hours: int = 6
    listener_max_per_case: int = 3
    listener_max_per_workspace_hour: int = 10

    evidence_backfill_days: int = 60
    agent_max_turns: int = 6
    llm_call_budget_per_run: int = 250
    statement_retention_days: int = 30

    demo_mode: bool = False
    log_level: str = "INFO"

    api_v1_prefix: str = "/api/v1"
    app_name: str = "BankRecon"

    # Noise budget, PRD section 09.
    max_case_openers_in_channel: int = 5
    max_agent_messages_per_case_per_day: int = 1
    max_agent_messages_per_workspace_hour: int = 10

    # Extraction limits, PRD section 6.1.
    max_pdf_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 50
    max_csv_bytes: int = 10 * 1024 * 1024
    ocr_timeout_seconds: int = 90


@lru_cache
def get_settings() -> Settings:
    return Settings()
