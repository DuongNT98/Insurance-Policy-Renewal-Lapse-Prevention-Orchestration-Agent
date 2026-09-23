"""AgentCore Platform v1.0"""

# Inner subgraph step 9 — RetentionReportNode. Generates a campaign-report
# narrative (LLM) summarizing this run's outcome. S-3: the report is
# aggregate-only — it must never surface raw policyholder_id/policy_id, only
# counts/tiers/outcomes. Follows the shared/tools aggregate-reporting pattern.

import logging
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.llm_response import (
    build_azure_llm_client,
    build_llm_messages,
    default_campaign_report,
    extract_llm_text,
)

logger = logging.getLogger(__name__)


class RetentionReportNode(FunctionNode):
    """Generate the campaign report narrative for this retention run."""

    # S-1: inner subgraph node — trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, llm: Any = None):
        # `llm` is a test-double seam only — production wiring (register_nodes())
        # never passes one. The real client is built fresh per invocation below.
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}

        aggregate = {
            "churn_risk_tier": state.get("churn_risk_tier"),
            "premium_tier": state.get("premium_tier"),
            "offer_type": (state.get("selected_offer") or {}).get("offer_type"),
            "hitl_decision": state.get("hitl_decision"),
            "response_outcome": state.get("response_outcome"),
        }

        # Azure OpenAI writes the narrative; any failure (no secret bound, API
        # error, empty response) degrades to the deterministic aggregate report
        # — never status=error, never a raise. An empty string would pass the
        # S-3 identifier scan trivially and be recorded as a completed report,
        # so the fallback must always produce real text.
        try:
            llm = self._llm or build_azure_llm_client(state)
            prompt = (
                "Write a one-paragraph campaign report narrative from this aggregate outcome "
                f"(no policyholder identifiers): {aggregate}."
            )
            report = extract_llm_text(llm.complete(build_llm_messages(prompt)))
            if not report.strip():
                raise ValueError("LLM returned empty campaign report")
            mode = "llm"
        except Exception as exc:
            logger.info(
                "RetentionReportNode: LLM unavailable, using deterministic report " "(correlation_id=%s): %s",
                state.get("correlation_id"),
                exc,
            )
            report = default_campaign_report(aggregate)
            mode = "deterministic"

        emit_trace_event(
            "campaign_report_generated",
            {
                "churn_risk_tier": aggregate["churn_risk_tier"],
                "response_outcome": aggregate["response_outcome"],
                "mode": mode,
            },
            state,
        )
        return {
            "campaign_report": report,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3: campaign_report must be aggregate-only — never echo raw policyholder_id."""
        report = state.get("campaign_report") or ""
        policyholder_id = state.get("policyholder_id")
        if policyholder_id and str(policyholder_id) in report:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["RetentionReportNode: campaign_report leaked raw policyholder_id (S-3)"],
            }
        return state
