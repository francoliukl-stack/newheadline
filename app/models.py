from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from .defaults import (
    DEFAULT_CHANNEL_PROPOSAL_PROMPT,
    DEFAULT_DAILY_FETCH_PROMPT,
    DEFAULT_SOURCES,
    DEFAULT_WEEKLY_PROMPT,
)


SENSITIVE_FIELDS = {
    "lark.app_secret",
    "dingtalk.daily_signing_secret",
    "dingtalk.weekly_signing_secret",
    "dingtalk.client_secret",
    "dingtalk.daily_webhook_url",
    "dingtalk.weekly_webhook_url",
    "search_provider.api_key",
    "search_provider.brave_api_key",
    "search_provider.serpapi_api_key",
    "openai_research.api_key",
    "openai_service.api_key",
    "event_intelligence.marketaux_api_key",
    "event_intelligence.firecrawl_api_key",
    "event_intelligence.alpha_vantage_api_key",
}


class SystemSettings(BaseModel):
    system_name: str = "Industry Intelligence"
    timezone: str = "Asia/Kuala_Lumpur"
    enabled: bool = True
    log_retention_days: int = Field(default=30, ge=1, le=365)


class ChatGPTSettings(BaseModel):
    browser_profile_path: str = ""
    model_hint: str = "ChatGPT Plus web browsing"
    login_check_url: HttpUrl = "https://chatgpt.com/"
    fetch_timeout_seconds: int = Field(default=180, ge=30, le=1800)


class OpenAIResearchSettings(BaseModel):
    enabled: bool = True
    api_key: str = ""
    model: str = "gpt-5.4-2026-03-05"
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    poll_interval_seconds: int = Field(default=10, ge=2, le=60)
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class OpenAIServiceSettings(BaseModel):
    enabled: bool = False
    api_key: str = ""
    api_url: str = "https://api.openai.com/v1/responses"
    classification_model: str = "gpt-5.4-nano-2026-03-17"
    analysis_model: str = "gpt-5.4-mini-2026-03-17"
    research_model: str = "gpt-5.4-2026-03-05"
    prompt_version: str = "gbss-event-v3.1.0"
    pricing_version: str = "2026-06-27"
    request_timeout_seconds: int = Field(default=60, ge=5, le=600)
    max_retries: int = Field(default=3, ge=0, le=5)
    circuit_open_seconds: int = Field(default=900, ge=60, le=86400)
    circuit_failure_threshold: int = Field(default=5, ge=1, le=20)
    single_ingest_cap_usd: float = Field(default=0.30, gt=0, le=10)
    single_insight_cap_usd: float = Field(default=1.50, gt=0, le=25)
    daily_cap_usd: float = Field(default=1.00, gt=0, le=25)
    weekly_cap_usd: float = Field(default=5.00, gt=0, le=50)
    monthly_cap_usd: float = Field(default=25.00, gt=0, le=100)


class EventIntelligenceSettings(BaseModel):
    enabled: bool = False
    critical_scan_enabled: bool = False
    weekly_input_mode: Literal["news", "event_cases"] = "news"
    schema_version: str = "3.1.0"
    review_view_url: str = ""
    critical_scan_hours: List[int] = Field(default_factory=lambda: [6, 21])
    critical_scan_fast_hours: List[int] = Field(default_factory=lambda: [9, 12, 15, 18])
    critical_scan_lookback_days: int = Field(default=7, ge=1, le=30)
    event_window_days: int = Field(default=3, ge=1, le=14)
    p0_candidate_score: float = Field(default=0.80, ge=0, le=1)
    p1_score: float = Field(default=0.60, ge=0, le=1)
    watch_score: float = Field(default=0.40, ge=0, le=1)
    official_enabled: bool = True
    gdelt_enabled: bool = True
    yfinance_enabled: bool = True
    marketaux_enabled: bool = False
    firecrawl_enabled: bool = False
    alpha_vantage_enabled: bool = False
    alpha_vantage_daily_call_limit: int = Field(default=20, ge=0)
    marketaux_api_key: str = ""
    firecrawl_api_key: str = ""
    alpha_vantage_api_key: str = ""


class SearchProviderSettings(BaseModel):
    provider: Literal[
        "chatgpt_web",
        "gemini_web",
        "serpapi",
        "bing_web_search",
        "serpstack",
        "openclaw_cache",
        "manual_seed",
        "codex_search",
        "gdelt_doc",
        "brave_search",
    ] = "openclaw_cache"
    fallback_provider: Literal[
        "none",
        "chatgpt_web",
        "gemini_web",
        "serpapi",
        "bing_web_search",
        "serpstack",
        "openclaw_cache",
        "manual_seed",
        "codex_search",
        "gdelt_doc",
        "brave_search",
    ] = "openclaw_cache"
    api_key: str = ""
    brave_api_key: str = ""
    serpapi_api_key: str = ""
    # Mirrored from event_intelligence.marketaux_api_key at load time so the
    # Marketaux search provider can read it; excluded from dumps so it is never
    # persisted in plaintext (the canonical secret stays in event_intelligence).
    marketaux_api_key: str = Field(default="", exclude=True)
    api_base_url: str = ""
    browser_profile_path: str = ""
    max_results_per_query: int = Field(default=20, ge=1, le=50)
    max_candidates_per_query: int = Field(default=5, ge=1, le=20)
    max_candidates_per_daily_fetch: int = Field(default=30, ge=5, le=100)
    request_timeout_seconds: int = Field(default=45, ge=5, le=300)
    openclaw_cache_path: str = "/Users/franco/.openclaw/workspace/tmp/news-pending.json"
    manual_seed_path: str = ""
    codex_search_cache_path: str = "data/codex-search-results.json"
    use_codex_search: bool = False
    supplemental_providers: List[str] = Field(default_factory=lambda: ["gdelt_doc"])
    # Per-provider cap on how many query groups a rate-limited supplemental
    # provider runs per fetch; providers absent here run every group.
    supplemental_query_group_limits: Dict[str, int] = Field(default_factory=lambda: {"marketaux": 5})


class LarkBaseSettings(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    app_token: str = ""
    table_id: str = ""
    approval_view_url: str = ""
    field_mapping: Dict[str, str] = Field(default_factory=lambda: {
        "id": "ID",
        "section": "Section",
        "label": "Label",
        "title_url": "Title",
        "status": "Status",
    })


class DingTalkSettings(BaseModel):
    delivery_mode: Literal["webhook", "app"] = "webhook"
    daily_webhook_url: str = ""
    daily_signing_secret: str = ""
    weekly_webhook_url: str = ""
    weekly_signing_secret: str = ""
    at_mobiles: str = ""
    app_id: str = ""
    agent_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    user_ids: str = ""


class DingTalkAITableSettings(BaseModel):
    enabled: bool = False
    base_id: str = ""
    sheet_id: str = ""
    insights_sheet_id: str = ""
    audit_trail_sheet_id: str = ""
    config_sheet_id: str = ""
    research_topics_sheet_id: str = ""
    research_queue_sheet_id: str = ""
    evidence_bank_sheet_id: str = ""
    claim_ledger_sheet_id: str = ""
    research_results_sheet_id: str = ""
    detect_sources_sheet_id: str = ""
    event_cases_sheet_id: str = ""
    event_entities_sheet_id: str = ""
    event_sources_sheet_id: str = ""
    event_scores_sheet_id: str = ""
    entity_catalog_sheet_id: str = ""
    alert_log_sheet_id: str = ""
    api_usage_sheet_id: str = ""
    report_docs_workspace_id: str = ""
    report_docs_root_node_id: str = ""
    report_docs_folder_node_id: str = ""
    report_docs_folder_url: str = ""
    report_docs_folder_name: str = "GBSS Research Reports"
    approval_view_url: str = ""
    operator_id: str = ""
    operator_user_id: str = ""
    field_mapping: Dict[str, str] = Field(default_factory=lambda: {
        "no": "No",
        "category": "Section",
        "subject": "Title",
        "tag": "Label",
        "link": "Source URL",
        "source": "Source",
        "source_excerpt": "Source Excerpt",
        "release_date": "Publish Date",
        "status": "Review Status",
        "operator": "Operator",
        "publish_status": "Publish Status",
        "sent_at": "Sent At",
        "search_provider": "Search Provider",
        "search_query": "Search Query",
        "search_batch": "Search Batch",
        "discovery_type": "Discovery Type",
        "first_seen_at": "First Seen At",
        "duplicate_of": "Duplicate Of",
        "duplicate_reason": "Duplicate Reason",
        "rejection_reason": "Rejection Reason",
    })


class SourceItem(BaseModel):
    domain: str
    weight: int = Field(default=1, ge=1, le=10)
    enabled: bool = True

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        domain = value.strip().lower().removeprefix("https://").removeprefix("http://")
        return domain.split("/")[0]


class SourceSettings(BaseModel):
    proposal_threshold: int = Field(default=2, ge=1, le=10)
    sources: List[SourceItem] = Field(
        default_factory=lambda: [SourceItem(domain=domain) for domain in DEFAULT_SOURCES]
    )


class KeywordMatrix(BaseModel):
    finance_keywords: List[str] = Field(default_factory=lambda: [
        "Antom", "Ant International", "Alipay+", "Stripe", "Adyen", "Wise",
        "Airwallex", "XTransfer", "PayPal", "Visa", "Mastercard", "WorldFirst",
    ])
    contact_center_keywords: List[str] = Field(default_factory=lambda: [
        "Voice AI", "Audio LLM", "Conversational Intelligence", "Agentforce",
        "Amazon Connect", "Deepgram", "Vapi", "Sierra.ai", "Contact Center AI",
    ])
    alias_expansions: Dict[str, List[str]] = Field(default_factory=lambda: {
        "Antom": ["Alipay+", "Ant International"],
        "Voice AI": ["Audio LLM", "Conversational Intelligence"],
    })
    highlighted_entities: List[str] = Field(default_factory=lambda: ["Antom", "Sierra.ai"])


class TaxonomySettings(BaseModel):
    sections: List[str] = Field(default_factory=lambda: ["Finance", "Contact Center"])
    labels: List[str] = Field(default_factory=lambda: [
        "Regulation", "Product", "Funding", "Partnership", "Benchmark", "M&A",
        "Market Expansion", "Earnings", "Leadership",
    ])
    statuses: List[str] = Field(default_factory=lambda: ["待处理", "已采纳", "已拒绝", "已重复"])
    default_status: str = "待处理"


class PromptTemplates(BaseModel):
    daily_fetch: str = DEFAULT_DAILY_FETCH_PROMPT
    channel_proposal: str = DEFAULT_CHANNEL_PROPOSAL_PROMPT
    weekly_publish: str = DEFAULT_WEEKLY_PROMPT


class PublishingRules(BaseModel):
    dedupe_window_days: int = Field(default=14, ge=1, le=90)
    daily_report_lookback_days: int = Field(default=7, ge=1, le=30)
    weekly_report_lookback_days: int = Field(default=7, ge=1, le=90)
    max_items_per_category: int = Field(default=10, ge=1, le=50)
    max_words_per_headline: int = Field(default=20, ge=5, le=50)
    max_domain_frequency_per_section: int = Field(default=3, ge=1, le=10)


class TaskSchedule(BaseModel):
    enabled: bool = True
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    weekdays: List[int] = Field(description="launchd weekdays, Sunday=0")


class ScheduleSettings(BaseModel):
    daily_fetch: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=2, minute=0, weekdays=[0, 1, 2, 3, 4, 5, 6]))
    ai_review_suggest: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=8, minute=50, weekdays=[0, 1, 2, 3, 4, 5, 6]))
    daily_remind: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=9, minute=0, weekdays=[0, 1, 2, 3, 4, 5, 6]))
    ai_review_deadline: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=11, minute=50, weekdays=[0, 1, 2, 3, 4, 5, 6]))
    daily_health_check: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=0, minute=0, weekdays=[0, 1, 2, 3, 4, 5, 6]))
    # Kept for existing installations only. Management delivery is weekly now.
    daily_publish: TaskSchedule = Field(default_factory=lambda: TaskSchedule(enabled=False, hour=9, minute=30, weekdays=[0, 1, 2, 3, 4, 5, 6]))
    # The no-cost proposal leaves more than a day for explicit approval.
    weekly_research_plan: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=9, minute=0, weekdays=[5]))
    # Manual ChatGPT Deep Research replaces unattended API research and image-draft generation.
    weekly_deep_research: TaskSchedule = Field(default_factory=lambda: TaskSchedule(enabled=False, hour=14, minute=0, weekdays=[6]))
    weekly_draft: TaskSchedule = Field(default_factory=lambda: TaskSchedule(enabled=False, hour=12, minute=0, weekdays=[6]))
    # Legacy field name retained for settings compatibility; this is the Daily Report task.
    weekly_headlines: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=12, minute=0, weekdays=[0, 1, 2, 3, 4, 5, 6]))
    weekly_publish: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=12, minute=0, weekdays=[0]))


class AppSettings(BaseModel):
    system: SystemSettings = Field(default_factory=SystemSettings)
    search_provider: SearchProviderSettings = Field(default_factory=SearchProviderSettings)
    chatgpt: ChatGPTSettings = Field(default_factory=ChatGPTSettings)
    openai_research: OpenAIResearchSettings = Field(default_factory=OpenAIResearchSettings)
    openai_service: OpenAIServiceSettings = Field(default_factory=OpenAIServiceSettings)
    event_intelligence: EventIntelligenceSettings = Field(default_factory=EventIntelligenceSettings)
    lark: LarkBaseSettings = Field(default_factory=LarkBaseSettings)
    dingtalk: DingTalkSettings = Field(default_factory=DingTalkSettings)
    dingtalk_ai_table: DingTalkAITableSettings = Field(default_factory=DingTalkAITableSettings)
    source_settings: SourceSettings = Field(default_factory=SourceSettings)
    keywords: KeywordMatrix = Field(default_factory=KeywordMatrix)
    taxonomy: TaxonomySettings = Field(default_factory=TaxonomySettings)
    prompts: PromptTemplates = Field(default_factory=PromptTemplates)
    rules: PublishingRules = Field(default_factory=PublishingRules)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)

    @field_validator("taxonomy")
    @classmethod
    def validate_taxonomy(cls, value: TaxonomySettings) -> TaxonomySettings:
        if value.default_status not in value.statuses:
            raise ValueError("default_status must be listed in statuses")
        return value
