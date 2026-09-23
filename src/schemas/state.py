"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict (see ADR-005 for the prohibited
# alternatives). LangGraph checkpoints use msgpack serialization, so only
# plain serializable fields are allowed. Do NOT add credentials or secrets.

from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Agent state — INS-C2-056 lapse-prevention retention pipeline.

    All shared fields (user_input, status, session_id, node_history,
    error_log, hitl_*, etc.) are inherited from AgentState. Every
    agent-specific field below is wrapped in NotRequired[...] (CoE C8):
    absent-until-written by the node that produces it, and a node running
    earlier in the pipeline must never KeyError on a field it hasn't set yet.

    mypy cannot see that AgentState is a TypedDict at runtime (framework ships
    no py.typed marker), so it reports every NotRequired[...] below as invalid
    outside a TypedDict body — a tooling limitation, not a real type error.
    """

    # Outer pre_process sets `validated_input` (already declared on AgentState) to
    # the JSON-serialized policyholder payload; GraphNode.extract_input() forwards
    # it as inner state["user_input"] (BaseGraph.invoke seeds user_input from it).

    # Inner step 1 — PolicyMonitorNode (parses inner state["user_input"] JSON once,
    # keeps the parsed dict around so later inner nodes don't re-parse JSON)
    raw_payload: NotRequired[dict[str, Any]]  # type: ignore[valid-type]
    policyholder_id: NotRequired[str]  # type: ignore[valid-type]
    policy_id: NotRequired[str]  # type: ignore[valid-type]
    days_to_renewal: NotRequired[int]  # type: ignore[valid-type]
    days_to_payment_due: NotRequired[int]  # type: ignore[valid-type]
    renewal_approaching: NotRequired[bool]  # type: ignore[valid-type]

    # Inner step 2 — LapseSignalDetectNode
    lapse_signals: NotRequired[list[str]]  # type: ignore[valid-type]
    lapse_signal_count: NotRequired[int]  # type: ignore[valid-type]

    # Inner step 3 — ChurnScoreNode
    churn_score: NotRequired[float]  # type: ignore[valid-type]
    churn_risk_tier: NotRequired[str]  # type: ignore[valid-type]  # low | medium | high

    # Inner step 4 — RetentionOfferSelectNode
    annual_premium_jpy: NotRequired[float]  # type: ignore[valid-type]
    premium_tier: NotRequired[str]  # type: ignore[valid-type]  # standard | high_value
    selected_offer: NotRequired[dict[str, Any]]  # type: ignore[valid-type]
    offer_rationale: NotRequired[str]  # type: ignore[valid-type]

    # Inner step 5 — ContentGenerateNode
    retention_message: NotRequired[str]  # type: ignore[valid-type]
    dispatch_channel: NotRequired[str]  # type: ignore[valid-type]

    # Inner step 6 — HITLGateNode
    requires_human_review: NotRequired[bool]  # type: ignore[valid-type]
    hitl_decision: NotRequired[str]  # type: ignore[valid-type]  # approved | rejected | corrected | auto

    # Inner step 7 — ChannelDispatchNode
    dispatch_result: NotRequired[dict[str, Any]]  # type: ignore[valid-type]

    # Inner step 8 — ResponseTrackNode
    response_outcome: NotRequired[str]  # type: ignore[valid-type]  # confirmed_renewal | no_response | cancelled | pending

    # Inner step 9 — RetentionReportNode
    campaign_report: NotRequired[str]  # type: ignore[valid-type]
