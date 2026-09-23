from framework.schemas.agent_status import AgentStatus
from src.nodes.lapse_signal_detect_node import LapseSignalDetectNode


class TestLapseSignalDetectNode:
    def test_detects_all_signals(self):
        node = LapseSignalDetectNode()
        state = {
            "raw_payload": {"payment_status": "missed", "cancellation_inquiry": True, "payment_method_change": True},
            "renewal_approaching": True,
        }
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["lapse_signal_count"] == 4
        assert "missed_premium" in result["lapse_signals"]

    def test_no_signals(self):
        node = LapseSignalDetectNode()
        state = {"raw_payload": {"payment_status": "on_time"}, "renewal_approaching": False}
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["lapse_signal_count"] == 0

    def test_short_circuits_on_upstream_error(self):
        node = LapseSignalDetectNode()
        result = node.execute({"status": AgentStatus.ERROR})
        assert result["status"] == AgentStatus.ERROR
        assert "lapse_signals" not in result
