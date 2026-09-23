"""AgentCore Platform v1.0"""

# Inner subgraph step 8 — ResponseTrackNode. Tracks the policyholder's response
# outcome (confirmed renewal / no-response / cancelled) and feeds it back into
# the churn-scoring loop for future runs. Engineering scope note: real-time
# webhook ingestion of the policyholder's response is a per-insurer deployment
# concern; this node reads an optional `simulated_response` test hook from the
# payload so the pipeline is testable end-to-end without a live webhook.
# Pattern ref: shared/tools/response_tracker.py.

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

VALID_OUTCOMES = ("confirmed_renewal", "no_response", "cancelled", "pending")


class ResponseTrackNode(FunctionNode):
    """Track the policyholder response outcome for this outreach."""

    # S-1: inner subgraph node — trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}

        if state.get("hitl_decision") == "rejected" or not (state.get("dispatch_result") or {}).get("delivered"):
            outcome = "pending"
        else:
            payload = state.get("raw_payload", {}) or {}
            simulated = payload.get("simulated_response")
            outcome = simulated if simulated in VALID_OUTCOMES else "no_response"

        emit_trace_event(
            "response_tracked",
            {"policy_id": state.get("policy_id"), "response_outcome": outcome},
            state,
        )
        return {
            "response_outcome": outcome,
            "status": AgentStatus.SUCCESS.value,
        }
