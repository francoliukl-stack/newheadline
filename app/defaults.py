DEFAULT_SOURCES = [
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com",
    "techcrunch.com", "theinformation.com", "finextra.com", "pymnts.com",
    "paymentsdive.com", "fintechfutures.com", "fintechnews.hk", "ledgerinsights.com",
    "americanbanker.com", "businesswire.com", "prnewswire.com", "forbes.com",
    "fortune.com", "axios.com", "theverge.com", "wired.com", "venturebeat.com",
    "cxtoday.com", "nojitter.com", "contactcenterpipeline.com", "destinationcrm.com",
    "customerthink.com", "cmswire.com", "salesforce.com", "aws.amazon.com",
    "microsoft.com", "googlecloudpresscorner.com", "openai.com", "anthropic.com",
    "deepgram.com", "sierra.ai", "vapi.ai", "elevenlabs.io", "twilio.com",
    "genesys.com", "nice.com", "five9.com", "talkdesk.com", "zendesk.com",
    "intercom.com", "stripe.com", "adyen.com", "wise.com", "airwallex.com",
    "paypal.com", "visa.com", "mastercard.com", "antgroup.com", "antom.com",
    "worldfirst.com", "xtransfer.com",
]

DEFAULT_DAILY_FETCH_PROMPT = """Search the web for high-signal news in Finance, Payments, Banking, and Contact Center Voice AI.
Expand entity aliases semantically, deduplicate by event, prefer tier-1 sources, and return only strict JSON."""

DEFAULT_CHANNEL_PROPOSAL_PROMPT = """If a new vertical source or entity appears at least twice this week and is not in the configured source list,
return it as Channel_Proposal with reason, evidence URLs, and suggested category."""

DEFAULT_WEEKLY_PROMPT = """Rewrite accepted records into the exact weekly headline format.
Use concise English, keep each item under 20 words, preserve Markdown links, and cap each category at 10 items."""
