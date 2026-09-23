from framework.schemas.agent_status import AgentStatus
from src.nodes.churn_score_node import ChurnScoreNode


class TestChurnScoreNode:
    def test_low_risk_with_no_signals(self):
        node = ChurnScoreNode()
        result = node.execute({"lapse_signal_count": 0, "renewal_approaching": False})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["churn_risk_tier"] == "low"

    def test_high_risk_with_many_signals(self):
        node = ChurnScoreNode()
        result = node.execute({"lapse_signal_count": 4, "renewal_approaching": True})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["churn_risk_tier"] == "high"
        assert result["churn_score"] <= 1.0

    def test_short_circuits_on_upstream_error(self):
        node = ChurnScoreNode()
        result = node.execute({"status": AgentStatus.ERROR})
        assert result["status"] == AgentStatus.ERROR
        assert "churn_score" not in result
