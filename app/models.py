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
    "search_provider.api_key",
}


class SystemSettings(BaseModel):
    system_name: str = "Weekly Headlines"
    timezone: str = "Asia/Shanghai"
    enabled: bool = True
    log_retention_days: int = Field(default=30, ge=1, le=365)


class ChatGPTSettings(BaseModel):
    browser_profile_path: str = ""
    model_hint: str = "ChatGPT Plus web browsing"
    login_check_url: HttpUrl = "https://chatgpt.com/"
    fetch_timeout_seconds: int = Field(default=180, ge=30, le=1800)


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
    ] = "openclaw_cache"
    api_key: str = ""
    api_base_url: str = ""
    browser_profile_path: str = ""
    max_results_per_query: int = Field(default=10, ge=1, le=50)
    request_timeout_seconds: int = Field(default=45, ge=5, le=300)
    openclaw_cache_path: str = "/Users/franco/.openclaw/workspace/tmp/news-pending.json"
    manual_seed_path: str = ""
    codex_search_cache_path: str = "data/codex-search-results.json"
    use_codex_search: bool = False


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
        "title_url": "Title & URL",
        "status": "Status",
    })


class DingTalkSettings(BaseModel):
    delivery_mode: Literal["webhook", "app"] = "webhook"
    daily_webhook_url: str = ""
    daily_signing_secret: str = ""
    weekly_webhook_url: str = ""
    weekly_signing_secret: str = ""
    app_id: str = ""
    agent_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    user_ids: str = ""


class DingTalkAITableSettings(BaseModel):
    enabled: bool = False
    base_id: str = ""
    sheet_id: str = ""
    operator_id: str = ""
    operator_user_id: str = ""
    field_mapping: Dict[str, str] = Field(default_factory=lambda: {
        "no": "No",
        "category": "Section",
        "subject": "Headline",
        "tag": "Label",
        "link": "Source URL",
        "source": "Source",
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
    max_items_per_category: int = Field(default=10, ge=1, le=50)
    max_words_per_headline: int = Field(default=20, ge=5, le=50)
    max_domain_frequency_per_section: int = Field(default=3, ge=1, le=10)


class TaskSchedule(BaseModel):
    enabled: bool = True
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    weekdays: List[int] = Field(description="launchd weekdays, Sunday=0")


class ScheduleSettings(BaseModel):
    daily_fetch: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=2, minute=0, weekdays=[1, 2, 3, 4, 5, 6]))
    daily_remind: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=9, minute=0, weekdays=[1, 2, 3, 4, 5, 6]))
    weekly_publish: TaskSchedule = Field(default_factory=lambda: TaskSchedule(hour=9, minute=0, weekdays=[0]))


class AppSettings(BaseModel):
    system: SystemSettings = Field(default_factory=SystemSettings)
    search_provider: SearchProviderSettings = Field(default_factory=SearchProviderSettings)
    chatgpt: ChatGPTSettings = Field(default_factory=ChatGPTSettings)
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
