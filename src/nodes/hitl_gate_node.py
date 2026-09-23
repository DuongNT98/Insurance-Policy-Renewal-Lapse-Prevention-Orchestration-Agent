"""AgentCore Platform v1.0"""

# Inner subgraph step 6 — HITLGateNode. D6 interrupt() pattern (保険業法 第300条):
# annual_premium_jpy >= threshold routes the offer to a human agent for review
# before dispatch; below threshold auto-proceeds. On timeout/no-resume the
# offer stays "pending" inside the interrupt — it is never auto-dispatched.
#
# Extends BaseNode directly (NOT FunctionNode) per code-contracts.md: a node
# calling interrupt() must override _security_gate_input()/_security_gate_output()
# itself (FunctionNode's versions are @final). Both are no-op passthroughs here —
# S-2 PII scanning already ran on the outer PreProcessNode input; this node
# introduces no new external output surface (ChannelDispatchNode's S-3 hook
# covers the actual outbound payload).

from typing import Any, ClassVar

from langgraph.types import interrupt
from framework.nodes.base_node import BaseNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.hitl_status import HitlStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class HITLGateNode(BaseNode):
    """D6 interrupt() gate for high-value retention offers (保険業法 第300条)."""

    # S-1: inner subgraph node — trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, high_value_threshold_jpy: float = 500_000):
        self._threshold = high_value_threshold_jpy

    def _security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        # No-op passthrough: S-2 PII scan already ran on the outer PreProcessNode
        # input; this node adds no new caller-supplied input surface.
        return state

    def _security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        # No-op passthrough: the outbound dispatch payload is gated by
        # ChannelDispatchNode's own S-3 _extra_security_gate_output().
        return state

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}

        annual_premium = state.get("annual_premium_jpy", 0.0)
        requires_review = annual_premium >= self._threshold

        if not requires_review:
            emit_trace_event(
                "hitl_auto_approved",
                {"policy_id": state.get("policy_id"), "annual_premium_jpy": annual_premium},
                state,
            )
            return {
                "requires_human_review": False,
                "hitl_decision": "auto",
                "status": AgentStatus.SUCCESS.value,
            }

        draft = {
            "policy_id": state.get("policy_id"),
            "offer_id": (state.get("selected_offer") or {}).get("offer_id"),
            "retention_message": state.get("retention_message"),
        }
        # hitl_draft: idempotency guard — avoids recomputing the (cheap, here)
        # draft when this node re-executes from the top after resume.
        feedback = interrupt(
            {
                "draft": draft,
                "reason": "high_value_offer_review",
                "policy_id": state.get("policy_id"),
                "annual_premium_jpy": annual_premium,
            }
        )
        decision = HitlStatus.from_feedback(feedback)

        result: dict[str, Any] = {
            "requires_human_review": True,
            "hitl_status": decision,
            "hitl_draft": draft,
            "status": AgentStatus.SUCCESS.value,
        }
        if decision == HitlStatus.REJECTED:
            result["hitl_decision"] = "rejected"
        elif decision == HitlStatus.CORRECTED:
            result["hitl_decision"] = "corrected"
            corrected_message = feedback.get("message") if isinstance(feedback, dict) else None
            if corrected_message:
                result["retention_message"] = corrected_message
        else:
            result["hitl_decision"] = "approved"

        emit_trace_event(
            "hitl_decision_recorded",
            {"policy_id": state.get("policy_id"), "hitl_decision": result["hitl_decision"]},
            state,
        )
        return result
