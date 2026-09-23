"""AgentCore Platform v1.0"""

# Inner subgraph step 2 — LapseSignalDetectNode. Threshold detection of lapse
# signals (missed premium / cancellation inquiry / payment-method change).
# Uses the shared shared/tools/lapse_signal_detector.py pattern.

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class LapseSignalDetectNode(FunctionNode):
    """Detect lapse-risk signals from the policyholder payload."""

    # S-1: inner subgraph node — trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}  # short-circuit: upstream already failed

        payload = state.get("raw_payload", {})
        signals: list[str] = []
        if payload.get("payment_status") == "missed":
            signals.append("missed_premium")
        if payload.get("cancellation_inquiry"):
            signals.append("cancellation_inquiry")
        if payload.get("payment_method_change"):
            signals.append("payment_method_change")
        if state.get("renewal_approaching"):
            signals.append("renewal_approaching")

        emit_trace_event(
            "lapse_signals_detected",
            {"policy_id": state.get("policy_id"), "signal_count": len(signals)},
            state,
        )
        return {
            "lapse_signals": signals,
            "lapse_signal_count": len(signals),
            "status": AgentStatus.SUCCESS.value,
        }
