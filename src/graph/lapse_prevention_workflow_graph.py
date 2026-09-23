"""AgentCore Platform v1.0"""

# Inner subgraph — the 9-node lapse-prevention retention pipeline (Cat 2 inner
# graph, called by LapsePreventionGraphNode.get_subgraph() in graph.py).
# Inherits BaseGraph directly (fully custom linear topology). memory_enabled
# is forced True by LapsePreventionGraphNode._parent_config() so the
# HITLGateNode's interrupt() can suspend/resume via a checkpointer (ADR-016 D5).

from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from src.nodes.channel_dispatch_node import ChannelDispatchNode
from src.nodes.churn_score_node import ChurnScoreNode
from src.nodes.content_generate_node import ContentGenerateNode
from src.nodes.hitl_gate_node import HITLGateNode
from src.nodes.lapse_signal_detect_node import LapseSignalDetectNode
from src.nodes.policy_monitor_node import PolicyMonitorNode
from src.nodes.response_track_node import ResponseTrackNode
from src.nodes.retention_offer_select_node import RetentionOfferSelectNode
from src.nodes.retention_report_node import RetentionReportNode
from src.schemas.state import State

DEFAULT_HIGH_VALUE_THRESHOLD_JPY = 500_000


class LapsePreventionWorkflowGraph(BaseGraph):
    """Inner graph — 9-step lapse-prevention / retention pipeline."""

    @property
    def name(self) -> str:
        return "lapse_prevention_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config keys — threshold/llm default gracefully.
        pass

    def register_nodes(self) -> None:
        # No super() — BaseGraph.register_nodes() is abstract. Do NOT register
        # initialize/finalize; those are outer backbone concerns (graph.py).
        llm = self.config.get("llm")
        threshold = self.config.get("high_value_threshold_jpy", DEFAULT_HIGH_VALUE_THRESHOLD_JPY)

        self._nodes["policy_monitor"] = PolicyMonitorNode()
        self._nodes["lapse_signal_detect"] = LapseSignalDetectNode()
        self._nodes["churn_score"] = ChurnScoreNode()
        self._nodes["retention_offer_select"] = RetentionOfferSelectNode(llm=llm, high_value_threshold_jpy=threshold)
        self._nodes["content_generate"] = ContentGenerateNode(llm=llm)
        self._nodes["hitl_gate"] = HITLGateNode(high_value_threshold_jpy=threshold)
        self._nodes["channel_dispatch"] = ChannelDispatchNode()
        self._nodes["response_track"] = ResponseTrackNode()
        self._nodes["retention_report"] = RetentionReportNode(llm=llm)

    def add_edges(self) -> None:
        self._sg.add_edge(START, "policy_monitor")
        self._sg.add_edge("policy_monitor", "lapse_signal_detect")
        self._sg.add_edge("lapse_signal_detect", "churn_score")
        self._sg.add_edge("churn_score", "retention_offer_select")
        self._sg.add_edge("retention_offer_select", "content_generate")
        self._sg.add_edge("content_generate", "hitl_gate")
        self._sg.add_edge("hitl_gate", "channel_dispatch")
        self._sg.add_edge("channel_dispatch", "response_track")
        self._sg.add_edge("response_track", "retention_report")
        self._sg.add_edge("retention_report", END)

    def route(self, state: AgentState) -> str:
        # Required by BaseGraph ABC; this topology is linear (no conditional
        # edges reference route()), but each node still short-circuits on
        # AgentStatus.ERROR.value internally so a failure does not crash downstream.
        return END if state.get("status") == AgentStatus.ERROR.value else "retention_report"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "output": state.get("campaign_report") or state.get("dispatch_result"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "policyholder_id": state.get("policyholder_id"),
            "policy_id": state.get("policy_id"),
            "churn_score": state.get("churn_score"),
            "churn_risk_tier": state.get("churn_risk_tier"),
            "selected_offer": state.get("selected_offer"),
            "retention_message": state.get("retention_message"),
            "requires_human_review": state.get("requires_human_review"),
            "hitl_decision": state.get("hitl_decision"),
            "dispatch_result": state.get("dispatch_result"),
            "response_outcome": state.get("response_outcome"),
            "campaign_report": state.get("campaign_report"),
            "error_log": state.get("error_log", []),
        }
