from framework.schemas.agent_status import AgentStatus
from src.nodes.channel_dispatch_node import ChannelDispatchNode


class TestChannelDispatchNode:
    def test_dispatches_via_local_sender(self):
        node = ChannelDispatchNode()
        state = {
            "policyholder_id": "PH-1",
            "policy_id": "POL-1",
            "dispatch_channel": "email",
            "retention_message": "hello",
        }
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["dispatch_result"]["delivered"] is True
        assert result["dispatch_result"]["channel"] == "email"

    def test_skips_dispatch_when_hitl_rejected(self):
        node = ChannelDispatchNode()
        result = node.execute({"hitl_decision": "rejected", "policy_id": "POL-1"})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["dispatch_result"]["delivered"] is False
        assert result["dispatch_result"]["reason"] == "hitl_rejected"

    def test_short_circuits_on_upstream_error(self):
        node = ChannelDispatchNode()
        result = node.execute({"status": AgentStatus.ERROR})
        assert result["status"] == AgentStatus.ERROR


class TestChannelDispatchNodeS3Hook:
    def test_strips_raw_message_from_dispatch_result(self):
        node = ChannelDispatchNode()
        state = {"dispatch_result": {"channel": "email", "message": "raw PII text", "delivered": True}}
        result = node._extra_security_gate_output(state)
        assert "message" not in result["dispatch_result"]
        assert result["dispatch_result"]["delivered"] is True

    def test_passes_through_when_no_message_key(self):
        node = ChannelDispatchNode()
        state = {"dispatch_result": {"channel": "email", "delivered": True}}
        result = node._extra_security_gate_output(state)
        assert result is state
