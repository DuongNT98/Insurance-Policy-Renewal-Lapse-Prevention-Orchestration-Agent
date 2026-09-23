"""AgentCore Platform v1.0"""

# Inner subgraph step 7 — ChannelDispatchNode. Dispatches via LINE Insurance /
# email / agent-call-brief (local/mock ChannelDispatchService — see
# docs/02_design.md dependency #5). S-3 strips PII: the dispatch_result never
# carries the raw retention_message text or contact details, only delivery
# metadata. Follows the shared/tools multi-channel dispatch pattern.
# Never dispatches a rejected high-value offer (保険業法 第300条 HITL gate).

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.channel_dispatch_service import ChannelDispatchService


class ChannelDispatchNode(FunctionNode):
    """Dispatch the retention message via the resolved channel."""

    # S-1: inner subgraph node — trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, dispatch_service: ChannelDispatchService | None = None):
        self._dispatch_service = dispatch_service or ChannelDispatchService()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}

        if state.get("hitl_decision") == "rejected":
            emit_trace_event(
                "retention_dispatch_skipped",
                {"policy_id": state.get("policy_id"), "reason": "hitl_rejected"},
                state,
            )
            return {
                "dispatch_result": {"delivered": False, "reason": "hitl_rejected"},
                "status": AgentStatus.SUCCESS.value,
            }

        result = self._dispatch_service.dispatch(
            channel=state.get("dispatch_channel", "email"),
            recipient_ref=state.get("policyholder_id", ""),
            message=state.get("retention_message", ""),
        )
        emit_trace_event(
            "retention_dispatched",
            {"policy_id": state.get("policy_id"), "channel": result.get("channel")},
            state,
        )
        return {
            "dispatch_result": result,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3: dispatch_result must never carry the raw message text (PII scope)."""
        dispatch_result = state.get("dispatch_result")
        if isinstance(dispatch_result, dict) and "message" in dispatch_result:
            redacted = dict(dispatch_result)
            redacted.pop("message", None)
            return {**state, "dispatch_result": redacted}
        return state
