from framework.schemas.agent_status import AgentStatus
from src.nodes.retention_offer_select_node import RetentionOfferSelectNode


class FakeLLM:
    """Canonical fake: complete(messages: list) -> {"content": str, ...}."""

    def __init__(self, response: str = "rationale text"):
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


class TestRetentionOfferSelectNode:
    def test_selects_offer_from_matrix_standard_low(self):
        node = RetentionOfferSelectNode(llm=None, high_value_threshold_jpy=500_000)
        result = node.execute({"annual_premium_jpy": 100_000, "churn_risk_tier": "low"})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["premium_tier"] == "standard"
        assert result["selected_offer"]["offer_id"] == "benefit_reminder_standard"
        # No LLM injected: deterministic-core mode still yields a real matrix-derived
        # rationale, not an empty string.
        assert result["offer_rationale"].strip()
        assert "benefit_reminder" in result["offer_rationale"] or "low" in result["offer_rationale"]

    def test_high_value_premium_tier(self):
        node = RetentionOfferSelectNode(llm=FakeLLM(), high_value_threshold_jpy=500_000)
        result = node.execute({"annual_premium_jpy": 900_000, "churn_risk_tier": "high"})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["premium_tier"] == "high_value"
        assert result["selected_offer"]["offer_id"] == "agent_visit_high_value_high"
        assert result["offer_rationale"] == "rationale text"

    def test_llm_never_determines_offer_id(self):
        """S-5 / 第300条 control: offer_id always comes from the matrix, never the LLM."""

        class OfferInventingLLM:
            def complete(self, prompt: str) -> str:
                return "offer_id: guaranteed_free_renewal"

        node = RetentionOfferSelectNode(llm=OfferInventingLLM(), high_value_threshold_jpy=500_000)
        result = node.execute({"annual_premium_jpy": 100_000, "churn_risk_tier": "low"})
        assert result["selected_offer"]["offer_id"] == "benefit_reminder_standard"

    def test_short_circuits_on_upstream_error(self):
        node = RetentionOfferSelectNode()
        result = node.execute({"status": AgentStatus.ERROR})
        assert result["status"] == AgentStatus.ERROR
        assert "selected_offer" not in result

    def test_llm_receives_canonical_message_list(self):
        llm = FakeLLM()
        RetentionOfferSelectNode(llm=llm, high_value_threshold_jpy=500_000).execute(
            {"annual_premium_jpy": 100_000, "churn_risk_tier": "low"}
        )
        assert isinstance(llm.last_messages, list)
        assert llm.last_messages[0]["role"] == "user"

    def test_llm_raising_falls_back_to_deterministic_rationale(self):
        # A failing LLM (API error) must degrade to the matrix-derived rationale
        # — never status=error, never a raise (Azure OpenAI is enhancement-only).
        r = RetentionOfferSelectNode(llm=RaisingLLM(), high_value_threshold_jpy=500_000).execute(
            {"annual_premium_jpy": 100_000, "churn_risk_tier": "low"}
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["selected_offer"]["offer_id"] == "benefit_reminder_standard"
        assert r["offer_rationale"].strip()

    def test_llm_empty_content_falls_back_to_deterministic_rationale(self):
        r = RetentionOfferSelectNode(llm=EmptyLLM(), high_value_threshold_jpy=500_000).execute(
            {"annual_premium_jpy": 100_000, "churn_risk_tier": "low"}
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["offer_rationale"].strip()

    def test_no_llm_injected_and_no_secret_bound_falls_back_to_deterministic(self):
        # Production shape in any env without a configured Azure OpenAI secret:
        # build_azure_llm_client(state) raises (no bound SecretProvider / missing
        # lifecycle identity fields on this bare state) and execute() must still
        # degrade cleanly rather than propagate that failure.
        node = RetentionOfferSelectNode(llm=None, high_value_threshold_jpy=500_000)
        result = node.execute({"annual_premium_jpy": 100_000, "churn_risk_tier": "low"})
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["offer_rationale"].strip()
