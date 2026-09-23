"""AgentCore Platform v1.0"""

# Shared LLM response handling for the inner subgraph's three LLM-backed nodes
# (RetentionOfferSelectNode, ContentGenerateNode, RetentionReportNode).
#
# `BaseLLM.complete()` takes a message list and returns a dict
# (`shared/services/llm/base_llm.py`):
#     {"content": str, "tool_calls": list, "model": str, "usage": {...}}
# Passing a bare prompt string makes a real provider raise, and treating the
# dict result as text lets a non-str value reach downstream nodes and the S-3
# output gate — where a `.lower()` on a dict raises, or an unexpected shape
# silently bypasses the 第300条 forbidden-phrase scan.

from __future__ import annotations

from typing import Any


def build_azure_llm_client(state: dict[str, Any]) -> Any:
    """Build a fresh AzureOpenAIClient for THIS invocation, from bound secrets.

    Never call this at __init__/register_nodes() time and never cache the
    result on self — it must be rebuilt on every execute() call (constructor-
    injected `self._llm` is a test-double seam only; production wiring never
    passes one). Raises (MissingSecret, KeyError from a state missing the
    lifecycle identity fields, ValueError, ...) on any problem — callers MUST
    wrap this in a try/except alongside their own `.complete()` call and
    degrade to the deterministic fallback on any failure; never let it reach
    the caller as status=error.
    """
    from framework.schemas.invocation_context import InvocationContext
    from shared.services.llm.azure_openai_client import AzureOpenAIClient

    ctx = InvocationContext.from_state(state)
    return AzureOpenAIClient(
        {
            "api_key": ctx.secrets.require("AZURE_OPENAI_API_KEY"),
            "azure_endpoint": ctx.secrets.require("AZURE_OPENAI_ENDPOINT"),
            "azure_deployment": ctx.secrets.require("AZURE_OPENAI_DEPLOYMENT"),
        }
    )


def build_llm_messages(prompt: str) -> list[dict[str, Any]]:
    """Wrap a prompt in the canonical `BaseLLM.complete(messages: list)` shape."""
    return [{"role": "user", "content": prompt}]


def extract_llm_text(raw: Any) -> str:
    """Normalise a `BaseLLM.complete()` response to text.

    Canonical `complete()` returns `{"content": str, ...}`. A bare string is also
    accepted for backward compatibility with string-returning test fakes. Anything
    else (missing/non-str `content`, unexpected type) yields `""`, which the caller
    MUST treat as a failed completion — never as usable text.
    """
    if isinstance(raw, dict):
        content = raw.get("content", "")
        return content if isinstance(content, str) else ""
    if isinstance(raw, str):
        return raw
    return ""


# Deterministic-core fallbacks. Each LLM-backed node calls these whenever a real
# Azure OpenAI completion is unavailable or fails for any reason (no secret
# bound, API error, empty/malformed response) — this is the graceful-degrade
# path, not a placeholder. Wording is drawn strictly from the pre-approved
# offer matrix and carries no guarantee/absolute claim (保険業法 第300条).


def default_retention_message(channel: str, offer: dict[str, Any]) -> str:
    """Deterministic retention copy used when no LLM completion is available."""
    offer_type = (offer or {}).get("offer_type") or "renewal support"
    benefit = (offer or {}).get("benefit_summary") or "options for your upcoming renewal"
    return (
        f"Regarding your upcoming policy renewal, we would like to share a "
        f"{offer_type} option: {benefit}. Please contact your representative to "
        f"discuss whether it suits your needs."
    )


def default_offer_rationale(offer: dict[str, Any], churn_risk_tier: str, premium_tier: str) -> str:
    """Deterministic internal rationale used when no LLM completion is available."""
    offer_type = (offer or {}).get("offer_type") or "retention offer"
    return f"Matrix selection: {offer_type} for a {churn_risk_tier}-risk, " f"{premium_tier}-premium policyholder."


def default_campaign_report(aggregate: dict[str, Any]) -> str:
    """Deterministic aggregate-only campaign report used when no LLM completion is available."""
    return (
        f"Campaign outcome — churn risk tier: {aggregate.get('churn_risk_tier')}, "
        f"premium tier: {aggregate.get('premium_tier')}, "
        f"offer: {aggregate.get('offer_type')}, "
        f"HITL decision: {aggregate.get('hitl_decision')}, "
        f"response outcome: {aggregate.get('response_outcome')}."
    )
