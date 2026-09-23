import json

from langgraph.checkpoint.memory import InMemorySaver

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.graph.graph import Graph

LOW_VALUE_PAYLOAD = json.dumps(
    {
        "policyholder_id": "PH-2001",
        "policy_id": "POL-2001",
        "annual_premium_jpy": 120_000,
        "renewal_due_date": "2027-06-01",
        "payment_status": "missed",
        "cancellation_inquiry": False,
        "payment_method_change": False,
        "preferred_channel": "email",
        "simulated_response": "confirmed_renewal",
    },
    ensure_ascii=False,
)


class TestLapsePreventionGraphIntegration:
    def test_compile_and_invoke_success_path(self):
        agent = Graph()
        agent.compile(checkpointer=InMemorySaver())
        ctx = InvocationContext(session_id="itest-1", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="itest")

        result = agent.invoke(LOW_VALUE_PAYLOAD, ctx=ctx)

        assert result["status"] == AgentStatus.SUCCESS.value
        node_history = result.get("node_history", [])
        assert "InitializeNode" in node_history
        assert "PreProcessNode" in node_history
        assert "LapsePreventionGraphNode" in node_history
        assert "PostProcessNode" in node_history
        assert "FinalizeNode" in node_history

    def test_empty_input_returns_error(self):
        agent = Graph()
        agent.compile(checkpointer=InMemorySaver())
        ctx = InvocationContext(session_id="itest-2", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="itest")

        result = agent.invoke("", ctx=ctx)

        assert result["status"] in (AgentStatus.ERROR.value, AgentStatus.CANCELLED.value)
