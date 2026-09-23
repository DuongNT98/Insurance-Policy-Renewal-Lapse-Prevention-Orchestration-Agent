import json
from datetime import date, timedelta

from framework.schemas.agent_status import AgentStatus
from src.nodes.policy_monitor_node import PolicyMonitorNode


class TestPolicyMonitorNode:
    def test_success_flags_approaching_renewal(self):
        node = PolicyMonitorNode()
        renewal = (date.today() + timedelta(days=10)).isoformat()
        payload = json.dumps(
            {"policyholder_id": "PH-1", "policy_id": "POL-1", "annual_premium_jpy": 100000, "renewal_due_date": renewal}
        )
        result = node.execute({"user_input": payload})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["renewal_approaching"] is True
        assert result["policyholder_id"] == "PH-1"

    def test_far_renewal_not_approaching(self):
        node = PolicyMonitorNode()
        renewal = (date.today() + timedelta(days=200)).isoformat()
        payload = json.dumps(
            {"policyholder_id": "PH-1", "policy_id": "POL-1", "annual_premium_jpy": 100000, "renewal_due_date": renewal}
        )
        result = node.execute({"user_input": payload})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["renewal_approaching"] is False

    def test_missing_ids_is_error(self):
        node = PolicyMonitorNode()
        result = node.execute({"user_input": json.dumps({"annual_premium_jpy": 1})})
        assert result["status"] == AgentStatus.ERROR

    def test_invalid_json_is_error(self):
        node = PolicyMonitorNode()
        result = node.execute({"user_input": "not-json"})
        assert result["status"] == AgentStatus.ERROR
