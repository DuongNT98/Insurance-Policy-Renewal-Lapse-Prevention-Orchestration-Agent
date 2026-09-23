from framework.schemas.agent_status import AgentStatus
from framework.schemas.hitl_status import HitlStatus
import src.nodes.hitl_gate_node as hitl_gate_module
from src.nodes.hitl_gate_node import HITLGateNode


class TestHITLGateNodeAuto:
    def test_below_threshold_auto_proceeds_without_interrupt(self, monkeypatch):
        def _fail_if_called(payload):
            raise AssertionError("interrupt() must not be called below threshold")

        monkeypatch.setattr(hitl_gate_module, "interrupt", _fail_if_called)
        node = HITLGateNode(high_value_threshold_jpy=500_000)
        result = node.execute({"annual_premium_jpy": 100_000, "policy_id": "POL-1"})
        assert result["status"] == AgentStatus.SUCCESS
        assert result["requires_human_review"] is False
        assert result["hitl_decision"] == "auto"

    def test_short_circuits_on_upstream_error(self):
        node = HITLGateNode()
        result = node.execute({"status": AgentStatus.ERROR})
        assert result["status"] == AgentStatus.ERROR


class TestHITLGateNodeInterrupt:
    """Simulate interrupt()'s resume value directly (real GraphInterrupt propagation
    is covered end-to-end in tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py).
    """

    def test_approve_decision(self, monkeypatch):
        monkeypatch.setattr(hitl_gate_module, "interrupt", lambda payload: {"action": "approve"})
        node = HITLGateNode(high_value_threshold_jpy=500_000)
        result = node.execute(
            {"annual_premium_jpy": 900_000, "policy_id": "POL-2", "selected_offer": {"offer_id": "x"}}
        )
        assert result["status"] == AgentStatus.SUCCESS
        assert result["requires_human_review"] is True
        assert result["hitl_decision"] == "approved"
        assert result["hitl_status"] == HitlStatus.APPROVED

    def test_reject_decision_never_auto_dispatches(self, monkeypatch):
        monkeypatch.setattr(hitl_gate_module, "interrupt", lambda payload: {"action": "reject"})
        node = HITLGateNode(high_value_threshold_jpy=500_000)
        result = node.execute({"annual_premium_jpy": 900_000, "policy_id": "POL-3"})
        assert result["hitl_decision"] == "rejected"
        assert result["hitl_status"] == HitlStatus.REJECTED

    def test_corrected_decision_overrides_message(self, monkeypatch):
        monkeypatch.setattr(
            hitl_gate_module, "interrupt", lambda payload: {"action": "correct", "message": "corrected copy"}
        )
        node = HITLGateNode(high_value_threshold_jpy=500_000)
        result = node.execute({"annual_premium_jpy": 900_000, "policy_id": "POL-4", "retention_message": "original"})
        assert result["hitl_decision"] == "corrected"
        assert result["retention_message"] == "corrected copy"


class TestHITLGateNodeSecurityGateHooks:
    def test_no_op_passthrough_hooks(self):
        node = HITLGateNode()
        state = {"foo": "bar"}
        assert node._security_gate_input(state) is state
        assert node._security_gate_output(state) is state
