"""AgentCore Platform v1.0"""

# Inner subgraph step 5 — ContentGenerateNode. LLM generates the channel-
# appropriate retention message copy around the offer selected in step 4.
# S-3 (_extra_security_gate_output): blocks misleading/absolute-guarantee
# claims not backed by the offer matrix (保険業法 第300条).

import logging
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.llm_response import (
    build_azure_llm_client,
    build_llm_messages,
    default_retention_message,
    extract_llm_text,
)

logger = logging.getLogger(__name__)

VALID_CHANNELS = ("line_insurance", "email", "agent_call_brief")
DEFAULT_CHANNEL = "email"

# 第300条: absolute/guarantee wording that must never appear in outbound content —
# no offer in config/retention_offers.yaml is ever an unconditional guarantee.
FORBIDDEN_PHRASES = (
    "guaranteed",
    "guarantee",
    "no risk",
    "保証します",
    "確実に",
)


class ContentGenerateNode(FunctionNode):
    """Generate the retention message copy for the selected offer."""

    # S-1: inner subgraph node — trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, llm: Any = None):
        # `llm` is a test-double seam only — production wiring (register_nodes())
        # never passes one. The real client is built fresh per invocation below.
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}

        offer = state.get("selected_offer", {}) or {}
        payload = state.get("raw_payload", {}) or {}
        channel = payload.get("preferred_channel")
        if channel not in VALID_CHANNELS:
            channel = DEFAULT_CHANNEL

        # Azure OpenAI generates the channel copy; any failure (no secret bound,
        # API error, empty response) degrades to the deterministic message —
        # never status=error, never a raise. An empty retention_message would
        # sail past the S-3 forbidden-phrase scan and be dispatched to the
        # policyholder as blank content, so the fallback must always produce
        # real text.
        try:
            llm = self._llm or build_azure_llm_client(state)
            prompt = (
                f"Write a short, professional retention message for channel '{channel}' offering "
                f"'{offer.get('offer_type')}': {offer.get('benefit_summary')}. "
                f"Do not make guarantee claims or promise outcomes not stated above."
            )
            message = extract_llm_text(llm.complete(build_llm_messages(prompt)))
            if not message.strip():
                raise ValueError("LLM returned empty retention message")
            mode = "llm"
        except Exception as exc:
            logger.info(
                "ContentGenerateNode: LLM unavailable, using deterministic message " "(correlation_id=%s): %s",
                state.get("correlation_id"),
                exc,
            )
            message = default_retention_message(channel, offer)
            mode = "deterministic"

        emit_trace_event(
            "retention_content_generated",
            {"policy_id": state.get("policy_id"), "channel": channel, "mode": mode},
            state,
        )
        return {
            "retention_message": message,
            "dispatch_channel": channel,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3 preservation/filter hook: reject misleading-claim wording (第300条).

        Re-checks the exact key execute() produces (`retention_message`), per
        CoE R1 standard (own-dict self-consistency) — never re-derives from an
        upstream/input field.
        """
        message = (state.get("retention_message") or "").lower()
        if any(phrase.lower() in message for phrase in FORBIDDEN_PHRASES):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ContentGenerateNode: retention_message contains a misleading/guarantee claim (第300条)"],
            }
        return state
