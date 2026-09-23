"""AgentCore Platform v1.0"""

# Outer post_process (Cat 2 backbone). Only reached on a completed turn (a
# HITL interrupt pauses the whole outer graph before post_process runs — see
# LapsePreventionGraphNode propagate_hitl=True in graph.py).

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class PostProcessNode(FunctionNode):
    """Format the final retention-outreach output."""

    # S-1: outer boundary node — matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "hitl_decision": state.get("hitl_decision"),
            "dispatch_result": state.get("dispatch_result"),
            "response_outcome": state.get("response_outcome"),
            "campaign_report": state.get("campaign_report"),
        }
        emit_trace_event(
            "retention_output_formatted",
            {"hitl_decision": summary["hitl_decision"], "correlation_id": state.get("correlation_id")},
            state,
        )
        return {
            "formatted_output": summary,
            "status": AgentStatus.SUCCESS.value,
        }
