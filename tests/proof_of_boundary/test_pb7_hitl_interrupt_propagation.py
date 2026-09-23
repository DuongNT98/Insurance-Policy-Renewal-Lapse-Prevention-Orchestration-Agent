# PB-7: HITL Interrupt Propagation — MANIFEST exact-name, required every
# template. INS-C2-056 has hitl.enabled: true, so this
# is the real GraphInterrupt-propagation test (not the auto-skip stub):
# verifies HITLGateNode's interrupt() (D6, inside the inner subgraph) surfaces
# through GraphNode (propagate_hitl=True) and the outer AgentBaseGraph as
# status=AWAITING_HUMAN — never status=error — and that resume() completes
# the pipeline with a real human decision.

import json

from langgraph.checkpoint.memory import InMemorySaver

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.graph.graph import Graph

HIGH_VALUE_PAYLOAD = json.dumps(
    {
        "policyholder_id": "PH-9001",
        "policy_id": "POL-9001",
        "annual_premium_jpy": 900_000,  # >= high_value_premium_threshold_jpy (500000)
        "renewal_due_date": "2027-01-01",
        "payment_status": "missed",
        "cancellation_inquiry": False,
        "payment_method_change": False,
        "preferred_channel": "email",
        "simulated_response": "confirmed_renewal",
    },
    ensure_ascii=False,
)

LOW_VALUE_PAYLOAD = json.dumps(
    {
        "policyholder_id": "PH-1001",
        "policy_id": "POL-1001",
        "annual_premium_jpy": 100_000,  # below threshold — auto-proceeds, no interrupt
        "renewal_due_date": "2027-06-01",
        "payment_status": "on_time",
        "cancellation_inquiry": False,
        "payment_method_change": False,
        "preferred_channel": "email",
        "simulated_response": "confirmed_renewal",
    },
    ensure_ascii=False,
)


def _ctx(session_id: str) -> InvocationContext:
    return InvocationContext(session_id=session_id, caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="pb7-test")


class TestPB7HitlInterruptPropagation:
    def test_high_value_offer_suspends_awaiting_human_not_error(self):
        agent = Graph()
        agent.compile(checkpointer=InMemorySaver())

        ctx = _ctx("pb7-high-value")
        result = agent.invoke(HIGH_VALUE_PAYLOAD, ctx=ctx)

        assert result["status"] == AgentStatus.AWAITING_HUMAN.value, (
            f"expected AWAITING_HUMAN, got {result['status']!r} — a HITL interrupt() must never "
            "surface as status=error"
        )
        assert "thread_id" in result and result["thread_id"]

    def test_resume_after_approve_completes_pipeline(self):
        agent = Graph()
        agent.compile(checkpointer=InMemorySaver())

        ctx = _ctx("pb7-resume-approve")
        paused = agent.invoke(HIGH_VALUE_PAYLOAD, ctx=ctx)
        assert paused["status"] == AgentStatus.AWAITING_HUMAN.value

        resumed = agent.resume(thread_id=paused["thread_id"], feedback={"action": "approve"})

        assert resumed["status"] == AgentStatus.SUCCESS.value
        node_history = resumed.get("node_history", [])
        assert "PostProcessNode" in node_history
        assert "FinalizeNode" in node_history

    def test_resume_after_reject_never_auto_dispatches(self):
        agent = Graph()
        agent.compile(checkpointer=InMemorySaver())

        ctx = _ctx("pb7-resume-reject")
        paused = agent.invoke(HIGH_VALUE_PAYLOAD, ctx=ctx)
        assert paused["status"] == AgentStatus.AWAITING_HUMAN.value

        resumed = agent.resume(thread_id=paused["thread_id"], feedback={"action": "reject"})

        assert resumed["status"] == AgentStatus.SUCCESS.value
        output = resumed.get("output") or {}
        dispatch_result = output.get("dispatch_result") or {}
        assert dispatch_result.get("delivered") is False, "a rejected high-value offer must never auto-dispatch"

    def test_low_value_offer_auto_proceeds_without_interrupt(self):
        agent = Graph()
        agent.compile(checkpointer=InMemorySaver())

        ctx = _ctx("pb7-low-value")
        result = agent.invoke(LOW_VALUE_PAYLOAD, ctx=ctx)

        assert result["status"] == AgentStatus.SUCCESS.value
