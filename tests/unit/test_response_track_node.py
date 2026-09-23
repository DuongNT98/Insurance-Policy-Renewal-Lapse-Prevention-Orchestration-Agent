from framework.schemas.agent_status import AgentStatus
from src.nodes.response_track_node import ResponseTrackNode


class TestResponseTrackNode:
    def test_uses_simulated_response_when_delivered(self):
        node = ResponseTrackNode()
        state = {
            "dispatch_result": {"delivered": True},
            "raw_payload": {"simulated_response": "cancelled"},
        }
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["response_outcome"] == "cancelled"

    def test_defaults_to_no_response_when_delivered_without_hint(self):
        node = ResponseTrackNode()
        state = {"dispatch_result": {"delivered": True}, "raw_payload": {}}
        result = node.execute(state)
        assert result["response_outcome"] == "no_response"

    def test_pending_when_not_delivered(self):
        node = ResponseTrackNode()
        state = {"dispatch_result": {"delivered": False}}
        result = node.execute(state)
        assert result["response_outcome"] == "pending"

    def test_pending_when_hitl_rejected(self):
        node = ResponseTrackNode()
        state = {"hitl_decision": "rejected", "dispatch_result": {"delivered": False}}
        result = node.execute(state)
        assert result["response_outcome"] == "pending"

    def test_short_circuits_on_upstream_error(self):
        node = ResponseTrackNode()
        result = node.execute({"status": AgentStatus.ERROR})
        assert result["status"] == AgentStatus.ERROR
