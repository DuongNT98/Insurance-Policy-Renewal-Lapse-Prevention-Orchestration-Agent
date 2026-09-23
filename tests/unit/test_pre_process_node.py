import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.pre_process_node import PreProcessNode

VALID_PAYLOAD = json.dumps({"policyholder_id": "PH-1", "policy_id": "POL-1", "annual_premium_jpy": 100000})


def _base_state(**overrides) -> dict:
    state = {
        "user_input": VALID_PAYLOAD,
        "input_context": {},
        "status": AgentStatus.PENDING,
        "execution_time": {},
        "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
        "correlation_id": "corr-1",
    }
    state.update(overrides)
    return state


class TestPreProcessNode:
    def test_success_serializes_validated_input(self):
        node = PreProcessNode()
        result = node.execute(_base_state())
        assert result["status"] == AgentStatus.SUCCESS
        assert json.loads(result["validated_input"])["policy_id"] == "POL-1"

    def test_empty_input_is_error(self):
        node = PreProcessNode()
        result = node.execute(_base_state(user_input=""))
        assert result["status"] == AgentStatus.ERROR

    def test_invalid_json_is_error(self):
        node = PreProcessNode()
        result = node.execute(_base_state(user_input="not-json"))
        assert result["status"] == AgentStatus.ERROR

    def test_missing_required_field_is_error(self):
        node = PreProcessNode()
        bad = json.dumps({"policyholder_id": "PH-1"})
        result = node.execute(_base_state(user_input=bad))
        assert result["status"] == AgentStatus.ERROR

    def test_trust_gate_enforced(self):
        node = PreProcessNode()
        state = _base_state(caller_trust_level=TrustLevel.ANONYMOUS.value)
        result = node(state)  # via __call__ — S-1 trust gate
        assert result["status"] == AgentStatus.ERROR.value
        assert "S-1 trust gate denied" in result["error_log"][0]
