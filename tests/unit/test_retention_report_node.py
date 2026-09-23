from framework.schemas.agent_status import AgentStatus
from src.nodes.retention_report_node import RetentionReportNode


class FakeLLM:
    """Canonical fake: complete(messages: list) -> {"content": str, ...}."""

    def __init__(self, response: str = "Campaign summary: medium risk tier, offer dispatched, response pending."):
        self._response = response
        self.last_messages = None

    def complete(self, messages):
        self.last_messages = messages
        return {"content": self._response, "tool_calls": [], "model": "fake", "usage": {}}


class RaisingLLM:
    def complete(self, messages):
        raise RuntimeError("provider timeout")


class EmptyLLM:
    def complete(self, messages):
        return {"content": "", "tool_calls": [], "model": "fake", "usage": {}}


AGG_STATE = {
    "churn_risk_tier": "medium",
    "premium_tier": "standard",
    "selected_offer": {"offer_type": "premium_reduction"},
    "hitl_decision": "auto",
    "response_outcome": "pending",
}


class TestRetentionReportNode:
    def test_generates_report(self):
        node = RetentionReportNode(llm=FakeLLM())
        state = {
            "churn_risk_tier": "medium",
            "premium_tier": "standard",
            "selected_offer": {"offer_type": "premium_reduction"},
            "hitl_decision": "auto",
            "response_outcome": "pending",
        }
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert "Campaign summary" in result["campaign_report"]

    def test_short_circuits_on_upstream_error(self):
        node = RetentionReportNode()
        result = node.execute({"status": AgentStatus.ERROR})
        assert result["status"] == AgentStatus.ERROR

    def test_llm_receives_canonical_message_list(self):
        llm = FakeLLM()
        RetentionReportNode(llm=llm).execute(dict(AGG_STATE))
        assert isinstance(llm.last_messages, list)
        assert llm.last_messages[0]["role"] == "user"

    def test_no_llm_configured_uses_deterministic_report_not_empty_string(self):
        # The entry point builds Graph() without an LLM, so no-LLM is a supported
        # production mode. An empty campaign_report would pass the S-3 identifier
        # scan trivially and be recorded as a completed report.
        r = RetentionReportNode(llm=None).execute(dict(AGG_STATE))
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["campaign_report"].strip()
        assert "medium" in r["campaign_report"]

    def test_deterministic_report_is_aggregate_only(self):
        # S-3: the deterministic fallback must not echo a policyholder identifier.
        node = RetentionReportNode(llm=None)
        r = node.execute({**AGG_STATE, "policyholder_id": "PH-1234"})
        assert "PH-1234" not in r["campaign_report"]
        gated = node._extra_security_gate_output(
            {"campaign_report": r["campaign_report"], "policyholder_id": "PH-1234"}
        )
        assert gated.get("status") != AgentStatus.ERROR.value

    def test_llm_raising_falls_back_to_deterministic_report(self):
        # A failing LLM (API error) must degrade to the deterministic aggregate
        # report — never status=error, never a raise (Azure OpenAI is
        # enhancement-only).
        r = RetentionReportNode(llm=RaisingLLM()).execute(dict(AGG_STATE))
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["campaign_report"].strip()
        assert "medium" in r["campaign_report"]

    def test_llm_empty_content_falls_back_to_deterministic_report(self):
        r = RetentionReportNode(llm=EmptyLLM()).execute(dict(AGG_STATE))
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["campaign_report"].strip()

    def test_policyholder_id_leak_from_a_dict_llm_still_reaches_the_gate(self):
        # Regression: before response normalisation, a canonical dict response was
        # stored verbatim in campaign_report. The S-3 gate does
        # `str(policyholder_id) in report` — on a dict that tests keys, not text,
        # so a leaked identifier inside the narrative was never caught.
        node = RetentionReportNode(llm=FakeLLM("Report for PH-1234 shows steady retention."))
        produced = node.execute({**AGG_STATE, "policyholder_id": "PH-1234"})
        assert isinstance(produced["campaign_report"], str)

        gated = node._extra_security_gate_output(
            {"campaign_report": produced["campaign_report"], "policyholder_id": "PH-1234"}
        )
        assert gated["status"] == AgentStatus.ERROR.value


class TestRetentionReportNodeS3Hook:
    def test_blocks_raw_policyholder_id_leak(self):
        node = RetentionReportNode()
        state = {"campaign_report": "Report for PH-1234 shows...", "policyholder_id": "PH-1234"}
        result = node._extra_security_gate_output(state)
        assert result["status"] == AgentStatus.ERROR

    def test_passes_aggregate_only_report(self):
        node = RetentionReportNode()
        state = {"campaign_report": "Medium-risk cohort, 1 offer dispatched.", "policyholder_id": "PH-1234"}
        result = node._extra_security_gate_output(state)
        assert result is state
