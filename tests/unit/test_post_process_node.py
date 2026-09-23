from framework.schemas.agent_status import AgentStatus
from src.nodes.post_process_node import PostProcessNode


class TestPostProcessNode:
    def test_formats_summary(self):
        node = PostProcessNode()
        state = {
            "hitl_decision": "auto",
            "dispatch_result": {"delivered": True},
            "response_outcome": "pending",
            "campaign_report": "report text",
            "correlation_id": "corr-1",
        }
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["formatted_output"]["hitl_decision"] == "auto"
        assert result["formatted_output"]["dispatch_result"] == {"delivered": True}

    def test_missing_fields_default_none(self):
        node = PostProcessNode()
        result = node.execute({})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["formatted_output"]["hitl_decision"] is None
