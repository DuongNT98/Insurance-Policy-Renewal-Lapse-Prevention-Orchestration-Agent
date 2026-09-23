"""AgentCore Platform v1.0"""

# Inner subgraph step 1 — PolicyMonitorNode. Parses the JSON payload forwarded
# by the outer GraphNode (inner state["user_input"], set by BaseGraph.invoke()
# from GraphNode.extract_input()'s return value) and detects approaching
# renewal/payment due dates. Pattern ref: shared/tools/policy_monitor.py.

import json
from datetime import date, datetime
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

RENEWAL_APPROACHING_DAYS = 30


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None


class PolicyMonitorNode(FunctionNode):
    """S-1 validates policyholder_id; detects approaching renewal/payment due dates."""

    # S-1: inner subgraph node — trust authenticated once at the outer backbone
    # (PreProcessNode, VERIFIED_EXTERNAL). Inner nodes stay ANONYMOUS.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            payload = None

        if not isinstance(payload, dict) or not payload.get("policyholder_id") or not payload.get("policy_id"):
            emit_trace_event("policy_monitor_rejected", {"reason": "invalid_payload"}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PolicyMonitorNode: payload missing policyholder_id/policy_id"],
            }

        today = date.today()
        renewal_due = _parse_date(payload.get("renewal_due_date"))
        payment_due = _parse_date(payload.get("payment_due_date"))
        days_to_renewal = (renewal_due - today).days if renewal_due else None
        days_to_payment_due = (payment_due - today).days if payment_due else None
        renewal_approaching = days_to_renewal is not None and 0 <= days_to_renewal <= RENEWAL_APPROACHING_DAYS

        emit_trace_event(
            "policy_monitored",
            {
                "policy_id": payload.get("policy_id"),
                "renewal_approaching": renewal_approaching,
            },
            state,
        )
        return {
            "raw_payload": payload,
            "policyholder_id": payload.get("policyholder_id"),
            "policy_id": payload.get("policy_id"),
            "annual_premium_jpy": float(payload.get("annual_premium_jpy", 0) or 0),
            "days_to_renewal": days_to_renewal,
            "days_to_payment_due": days_to_payment_due,
            "renewal_approaching": renewal_approaching,
            "status": AgentStatus.SUCCESS.value,
        }
