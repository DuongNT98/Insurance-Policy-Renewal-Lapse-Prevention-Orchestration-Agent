from framework.schemas.agent_status import AgentStatus
from src.nodes.content_generate_node import ContentGenerateNode


class FakeLLM:
    """Canonical fake: complete(messages: list) -> {"content": str, ...}."""

    def __init__(self, response: str = "Thank you for your continued policy."):
        self._response = response
        self.last_messages = None

    def complete(self, messages):
        self.last_messages = messages
        return {"content": self._response, "tool_calls": [], "model": "fake", "usage": {}}


class StringLLM:
    """Legacy fake returning a bare string (backward-compat path)."""

    def __init__(self, response: str = "legacy copy"):
        self._response = response

    def complete(self, messages):
        return self._response


class RaisingLLM:
    def complete(self, messages):
        raise RuntimeError("provider timeout")


class EmptyLLM:
    def complete(self, messages):
        return {"content": "", "tool_calls": [], "model": "fake", "usage": {}}


class TestContentGenerateNode:
    def test_generates_message_with_valid_channel(self):
        node = ContentGenerateNode(llm=FakeLLM())
        state = {
            "selected_offer": {"offer_type": "premium_reduction", "benefit_summary": "5% reduction"},
            "raw_payload": {"preferred_channel": "line_insurance"},
        }
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["dispatch_channel"] == "line_insurance"
        assert result["retention_message"] == "Thank you for your continued policy."

    def test_invalid_channel_falls_back_to_email(self):
        node = ContentGenerateNode(llm=FakeLLM())
        result = node.execute({"selected_offer": {}, "raw_payload": {"preferred_channel": "fax"}})
        assert result["dispatch_channel"] == "email"

    def test_short_circuits_on_upstream_error(self):
        node = ContentGenerateNode()
        result = node.execute({"status": AgentStatus.ERROR})
        assert result["status"] == AgentStatus.ERROR

    def test_llm_receives_canonical_message_list(self):
        llm = FakeLLM()
        ContentGenerateNode(llm=llm).execute({"selected_offer": {}, "raw_payload": {}})
        assert isinstance(llm.last_messages, list)
        assert llm.last_messages[0]["role"] == "user"

    def test_llm_string_response_still_accepted(self):
        r = ContentGenerateNode(llm=StringLLM()).execute({"selected_offer": {}, "raw_payload": {}})
        assert r["retention_message"] == "legacy copy"

    def test_no_llm_configured_uses_deterministic_copy_not_empty_string(self):
        # The entry point (src/api/server.py) builds Graph() without an LLM, so
        # no-LLM is a supported production mode. It must still emit real copy —
        # an empty retention_message would pass the S-3 forbidden-phrase scan and
        # be dispatched to the policyholder as blank content.
        r = ContentGenerateNode(llm=None).execute(
            {
                "selected_offer": {"offer_type": "premium_reduction", "benefit_summary": "5% reduction"},
                "raw_payload": {},
            }
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["retention_message"].strip()
        assert "premium_reduction" in r["retention_message"]

    def test_deterministic_copy_carries_no_guarantee_claim(self):
        # 第300条: the deterministic fallback must itself survive the S-3 gate.
        node = ContentGenerateNode(llm=None)
        r = node.execute({"selected_offer": {"offer_type": "premium_reduction"}, "raw_payload": {}})
        assert node._extra_security_gate_output({"retention_message": r["retention_message"]}) is not None
        gated = node._extra_security_gate_output({"retention_message": r["retention_message"]})
        assert gated.get("status") != AgentStatus.ERROR.value

    def test_llm_raising_falls_back_to_deterministic_copy(self):
        # A failing LLM (API error) must degrade to the deterministic copy —
        # never status=error, never a raise (Azure OpenAI is enhancement-only).
        r = ContentGenerateNode(llm=RaisingLLM()).execute(
            {"selected_offer": {"offer_type": "premium_reduction", "benefit_summary": "5% reduction"}, "raw_payload": {}}
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["retention_message"].strip()
        assert "premium_reduction" in r["retention_message"]

    def test_llm_empty_content_falls_back_to_deterministic_copy(self):
        r = ContentGenerateNode(llm=EmptyLLM()).execute({"selected_offer": {}, "raw_payload": {}})
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["retention_message"].strip()


class TestContentGenerateNodeS3Hook:
    def test_extra_gate_blocks_guarantee_claim(self):
        node = ContentGenerateNode()
        state = {"retention_message": "We guarantee your premium will never increase."}
        result = node._extra_security_gate_output(state)
        assert result["status"] == AgentStatus.ERROR
        assert "misleading" in result["error_log"][0].lower()

    def test_extra_gate_passes_clean_message(self):
        node = ContentGenerateNode()
        state = {"retention_message": "Here is a premium reduction option for your renewal."}
        result = node._extra_security_gate_output(state)
        assert result is state

    def test_forbidden_phrase_from_a_dict_llm_still_reaches_the_gate(self):
        # Regression: before response normalisation, a canonical dict response was
        # stored verbatim in retention_message. The S-3 gate does
        # `(state.get("retention_message") or "").lower()` — on a dict that raises
        # AttributeError, so the 第300条 scan never ran on real provider output.
        node = ContentGenerateNode(llm=FakeLLM("We guarantee your premium will never increase."))
        produced = node.execute({"selected_offer": {}, "raw_payload": {}})
        assert isinstance(produced["retention_message"], str)

        gated = node._extra_security_gate_output({"retention_message": produced["retention_message"]})
        assert gated["status"] == AgentStatus.ERROR.value
