"""AgentCore Platform v1.0"""

# Outer pre_process (Cat 2 backbone). Validates the raw caller payload and
# serializes it to `validated_input` (JSON string) — the inner subgraph does
# not see outer state, only the string returned by GraphNode.extract_input().
# S-1: outer boundary node — matches agent.yaml `required_trust_level`
# (VERIFIED_EXTERNAL) since this is the entry point that receives caller input.

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

REQUIRED_FIELDS = ("policyholder_id", "policy_id", "annual_premium_jpy")


class PreProcessNode(FunctionNode):
    """Validate incoming policyholder payload before the retention pipeline runs."""

    # S-1: outer boundary node — matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        user_input = state.get("user_input", "")
        input_context = state.get("input_context", {})  # read-only [C1]

        if not user_input or not str(user_input).strip():
            emit_trace_event(
                "policyholder_payload_rejected",
                {"reason": "empty_input", "correlation_id": state.get("correlation_id")},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: user_input is empty or missing"],
            }

        try:
            payload = json.loads(user_input) if isinstance(user_input, str) else user_input
        except (ValueError, TypeError):
            emit_trace_event(
                "policyholder_payload_rejected",
                {"reason": "invalid_json", "correlation_id": state.get("correlation_id")},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: user_input is not valid JSON"],
            }

        if not isinstance(payload, dict) or any(f not in payload for f in REQUIRED_FIELDS):
            emit_trace_event(
                "policyholder_payload_rejected",
                {"reason": "missing_required_fields", "correlation_id": state.get("correlation_id")},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"PreProcessNode: payload must include {REQUIRED_FIELDS}"],
            }

        emit_trace_event(
            "policyholder_payload_validated",
            {"policy_id": payload.get("policy_id"), "correlation_id": state.get("correlation_id")},
            state,
        )
        return {
            "validated_input": json.dumps(payload, ensure_ascii=False),
            "enriched_context": {"source": "ins-c2-056", "channel": input_context.get("channel", "unknown")},
            "status": AgentStatus.SUCCESS.value,
        }
