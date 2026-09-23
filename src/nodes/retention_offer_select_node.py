"""AgentCore Platform v1.0"""

# Inner subgraph step 4 — RetentionOfferSelectNode. S-5 / 保険業法 第300条
# control: the offer itself (offer_id/offer_type/benefit_summary) is selected
# EXCLUSIVELY from config/retention_offers.yaml via RetentionOfferService.
# The LLM is only used to phrase a short internal rationale — it never
# chooses the offer. Follows the shared/tools config-driven offer-selection pattern.

import logging
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_response import (
    build_azure_llm_client,
    build_llm_messages,
    default_offer_rationale,
    extract_llm_text,
)
from src.services.retention_offer_service import RetentionOfferService

logger = logging.getLogger(__name__)


class RetentionOfferSelectNode(FunctionNode):
    """Select a retention offer from the pre-approved matrix; LLM writes rationale only."""

    # S-1: inner subgraph node — trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(
        self,
        llm: Any = None,
        high_value_threshold_jpy: float = 500_000,
        offer_service: RetentionOfferService | None = None,
    ):
        # `llm` is a test-double seam only — production wiring (register_nodes())
        # never passes one. The real client is built fresh per invocation below.
        self._llm = llm
        self._threshold = high_value_threshold_jpy
        self._offer_service = offer_service or RetentionOfferService()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}

        annual_premium = state.get("annual_premium_jpy", 0.0)
        churn_risk_tier = state.get("churn_risk_tier", "low")
        premium_tier = "high_value" if annual_premium >= self._threshold else "standard"

        # S-5 / 第300条: offer comes ONLY from the config matrix — never LLM-generated.
        offer = self._offer_service.select_offer(churn_risk_tier=churn_risk_tier, premium_tier=premium_tier)

        # Azure OpenAI enhances the rationale wording; any failure (no secret
        # bound, API error, empty response) degrades to the matrix-derived
        # deterministic rationale — never status=error, never a raise.
        try:
            llm = self._llm or build_azure_llm_client(state)
            prompt = (
                f"Write a one-sentence internal rationale (Japanese business tone, no customer-facing "
                f"claims) for offering '{offer.get('offer_type')}' to a {churn_risk_tier}-risk, "
                f"{premium_tier}-premium policyholder. Do not invent a discount amount."
            )
            rationale = extract_llm_text(llm.complete(build_llm_messages(prompt)))
            if not rationale.strip():
                raise ValueError("LLM returned empty offer rationale")
        except Exception as exc:
            logger.info(
                "RetentionOfferSelectNode: LLM unavailable, using deterministic rationale " "(correlation_id=%s): %s",
                state.get("correlation_id"),
                exc,
            )
            rationale = default_offer_rationale(offer, churn_risk_tier, premium_tier)

        emit_trace_event(
            "offer_selected",
            {"policy_id": state.get("policy_id"), "offer_id": offer.get("offer_id"), "premium_tier": premium_tier},
            state,
        )
        return {
            "premium_tier": premium_tier,
            "selected_offer": offer,
            "offer_rationale": rationale,
            "status": AgentStatus.SUCCESS.value,
        }
