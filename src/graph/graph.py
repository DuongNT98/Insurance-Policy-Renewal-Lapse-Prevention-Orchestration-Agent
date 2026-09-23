"""AgentCore Platform v1.0"""

# Cat 2 — INS-C2-056 Insurance Policy Renewal & Lapse Prevention Orchestration
# Agent. Outer graph (this file) = AgentBaseGraph fixed 5-node backbone; the
# 9-step domain pipeline lives in the inner subgraph
# (src/graph/lapse_prevention_workflow_graph.py), wrapped by
# LapsePreventionGraphNode in the `main` slot. See
# _shared-rules/coe-standards/... cat2-pattern.md for the full contract.
#
# HITL: `hitl.enabled: true` in config/config.yaml. The inner HITLGateNode
# calls interrupt() for high-value offers (保険業法 第300条); propagate_hitl=True
# below surfaces that interrupt to the OUTER graph so the whole agent pauses
# (AWAITING_HUMAN) rather than only the inner subgraph.

from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.nodes.pre_process_node import PreProcessNode
from src.nodes.post_process_node import PostProcessNode
from src.schemas.state import State

DEFAULT_HIGH_VALUE_THRESHOLD_JPY = 500_000


class LapsePreventionGraphNode(GraphNode):
    """Wraps the inner 9-node lapse-prevention workflow; assigned to `main`."""

    # S-1: the outer main-slot wrapper is the first node to receive caller input,
    # so it must enforce the agent-level trust floor from config/agent.yaml
    # (VERIFIED_EXTERNAL) rather than inheriting BaseNode's permissive ANONYMOUS.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    # "propagate": re-raise inner graph exceptions as SubgraphError (fail fast).
    error_strategy: ClassVar[str] = "propagate"

    # True: surface the inner HITLGateNode's interrupt() to the outer graph
    # caller — the whole agent pauses (AWAITING_HUMAN), not just the inner
    # subgraph. Requires hitl.enabled: true in config.yaml (present).
    propagate_hitl: ClassVar[bool] = True

    def __init__(self, llm: Any = None, high_value_threshold_jpy: float = DEFAULT_HIGH_VALUE_THRESHOLD_JPY):
        super().__init__()
        self._llm = llm
        self._threshold = high_value_threshold_jpy
        # Cache the compiled inner subgraph (with its own checkpointer) so the
        # same checkpoint is reused across an invoke() -> resume() cycle —
        # a fresh saver each call would lose the paused HITL session.
        self._subgraph = self._build_subgraph()

    def _build_subgraph(self) -> Any:
        from langgraph.checkpoint.memory import InMemorySaver
        from src.graph.lapse_prevention_workflow_graph import LapsePreventionWorkflowGraph

        sg = LapsePreventionWorkflowGraph(config=self._parent_config())
        sg.compile(checkpointer=InMemorySaver())
        return sg

    def get_subgraph(self) -> Any:
        return self._subgraph

    def extract_input(self, state: AgentState) -> str:
        # S-4: emit_trace_event runs here — inside GraphNode.execute() — since
        # this GraphNode subclass does not (and must not) override execute().
        emit_trace_event(
            "lapse_prevention_dispatched",
            {"correlation_id": state.get("correlation_id")},
            state,
        )
        # state.get(...) resolves to Any (AgentState is an unstubbed framework
        # type) — cast is descriptive, not a runtime check, since S-1/S-2 gates
        # upstream already guarantee this is a str.
        return cast(str, state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "lapse_prevention_completed",
            {
                "correlation_id": state.get("correlation_id"),
                "hitl_decision": sub_result.get("hitl_decision"),
                "response_outcome": sub_result.get("response_outcome"),
            },
            state,
        )
        return {
            "policyholder_id": sub_result.get("policyholder_id"),
            "policy_id": sub_result.get("policy_id"),
            "churn_score": sub_result.get("churn_score"),
            "churn_risk_tier": sub_result.get("churn_risk_tier"),
            "selected_offer": sub_result.get("selected_offer"),
            "retention_message": sub_result.get("retention_message"),
            "requires_human_review": sub_result.get("requires_human_review"),
            "hitl_decision": sub_result.get("hitl_decision"),
            "dispatch_result": sub_result.get("dispatch_result"),
            "response_outcome": sub_result.get("response_outcome"),
            "campaign_report": sub_result.get("campaign_report"),
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
        }

    def _parent_config(self) -> dict[str, Any]:
        return {
            "llm": self._llm,
            "high_value_threshold_jpy": self._threshold,
            # Mandatory for the inner subgraph too: HITLGateNode's interrupt()
            # requires a thread-scoped checkpointer to suspend/resume (ADR-016 D5).
            "memory_enabled": True,
            "hitl": {"enabled": True, "max_hitl": 8},
        }

    def _handle_call_error(self, subgraph: Any, e: Exception, state: AgentState) -> dict[str, Any]:
        # LangGraph sentinel exceptions (GraphInterrupt et al.) must bubble up
        # to the runtime unmodified — never wrapped into SubgraphError.
        from langgraph.errors import GraphBubbleUp

        if isinstance(e, GraphBubbleUp) or "interrupt" in type(e).__name__.lower():
            raise e
        # super()._handle_call_error resolves to Any (GraphNode is an unstubbed
        # framework type) — cast is descriptive, matching its documented contract.
        return cast(dict[str, Any], super()._handle_call_error(subgraph, e, state))


class LapsePreventionGraph(AgentBaseGraph):
    """INS-C2-056 — outer graph. Backbone: initialize → pre_process → main → post_process → finalize."""

    def __init__(self, config: dict[str, Any] | None = None):
        # HITL (D6 interrupt(), 保険業法 第300条) requires memory_enabled/hitl.enabled
        # on the OUTER graph too — BaseGraph.invoke() only builds the thread-scoped
        # checkpointer config when one of these is set, and the outer graph is
        # always compiled with a checkpointer (see src/api/server.py, tests). These
        # defaults mirror config/config.yaml so a bare Graph() (e.g. in tests) still
        # gets a working HITL setup; explicit config passed by the caller still wins.
        merged = {
            "memory_enabled": True,
            "hitl": {"enabled": True, "max_hitl": 8},
            "high_value_premium_threshold_jpy": DEFAULT_HIGH_VALUE_THRESHOLD_JPY,
        }
        merged.update(config or {})
        super().__init__(config=merged)

    @property
    def name(self) -> str:
        return "ins-c2-056"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode
        llm = self.config.get("llm")
        threshold = self.config.get("high_value_premium_threshold_jpy", DEFAULT_HIGH_VALUE_THRESHOLD_JPY)

        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = LapsePreventionGraphNode(llm=llm, high_value_threshold_jpy=threshold)
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.


# agent.yaml class:"src.graph.graph.LapsePreventionGraph" resolves this class directly.
Graph = LapsePreventionGraph
