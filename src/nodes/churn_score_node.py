"""AgentCore Platform v1.0"""

# Inner subgraph step 3 — ChurnScoreNode. Deterministic lapse-probability
# score from detected signals + renewal proximity. Uses the shared
# shared/tools/churn_scorer.py pattern, shared with other templates'
# churn-scoring use cases.

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

SIGNAL_WEIGHT = 0.2
BASE_SCORE = 0.1
RENEWAL_APPROACHING_WEIGHT = 0.15
LOW_MEDIUM_BOUNDARY = 0.34
MEDIUM_HIGH_BOUNDARY = 0.67


class ChurnScoreNode(FunctionNode):
    """Score lapse probability from detected signals (deterministic, no LLM)."""

    # S-1: inner subgraph node — trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}

        signal_count = state.get("lapse_signal_count", 0)
        renewal_approaching = state.get("renewal_approaching", False)

        score = BASE_SCORE + (signal_count * SIGNAL_WEIGHT)
        if renewal_approaching:
            score += RENEWAL_APPROACHING_WEIGHT
        score = min(score, 1.0)

        if score < LOW_MEDIUM_BOUNDARY:
            tier = "low"
        elif score < MEDIUM_HIGH_BOUNDARY:
            tier = "medium"
        else:
            tier = "high"

        emit_trace_event(
            "churn_scored",
            {"policy_id": state.get("policy_id"), "churn_risk_tier": tier},
            state,
        )
        return {
            "churn_score": round(score, 4),
            "churn_risk_tier": tier,
            "status": AgentStatus.SUCCESS.value,
        }
