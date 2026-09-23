# Template Design Specification — INS-C2-056

## Position in AgentCore Architecture

- **Agent Class**: `LapsePreventionGraph` (aliased as `Graph` in `src/graph/graph.py`)
- **L1 Base**: `AgentBaseGraph` (L1 direct) — Cat 2 outer graph
- **Three-Layer Separation**:
  - State: flat TypedDict composition (`src/schemas/state.py`, no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview (Cat 2 — outer + inner subgraph)

This template follows the mandatory Cat 2 pattern: an outer `AgentBaseGraph`
backbone wraps a 9-step domain workflow inside a `GraphNode` in the `main`
slot. The inner subgraph implements the lapse-prevention pipeline.

### Outer graph (`src/graph/graph.py`)

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version, session_id, trust_level setup | — | — | InitializeNode (default) |
| pre_process | Validate raw policyholder payload; serialize to `validated_input` (JSON) | `user_input` | `validated_input`, `enriched_context` | `PreProcessNode` |
| main | `LapsePreventionGraphNode` (`GraphNode`) — dispatches to inner subgraph, merges result | `validated_input` | `policyholder_id`, `churn_score`, `selected_offer`, `retention_message`, `hitl_decision`, `dispatch_result`, `response_outcome`, `campaign_report`, `result`, `status` | `GraphNode` |
| post_process | Format final retention-outreach summary | merged fields above | `formatted_output` | `PostProcessNode` |
| finalize | response_metadata, total_time_ms | — | — | FinalizeNode (default) |

### Inner subgraph (`src/graph/lapse_prevention_workflow_graph.py` — `LapsePreventionWorkflowGraph`, `BaseGraph` direct)

| # | Node | Responsibility | LLM? |
|---|------|----------------|------|
| 1 | `PolicyMonitorNode` | Parse payload; detect approaching renewal/payment due dates | ❌ |
| 2 | `LapseSignalDetectNode` | Detect lapse signals (missed premium / cancellation inquiry / payment-method change) | ❌ |
| 3 | `ChurnScoreNode` | Deterministic lapse-probability score + risk tier | ❌ |
| 4 | `RetentionOfferSelectNode` | Select offer from `config/retention_offers.yaml` **only** (S-5/第300条); LLM writes rationale copy only | ✅ (rationale copy only) |
| 5 | `ContentGenerateNode` | Generate channel-appropriate retention message; S-3 blocks misleading/guarantee claims | ✅ |
| 6 | `HITLGateNode` | D6 `interrupt()`: `annual_premium_jpy >= high_value_premium_threshold_jpy` → human-agent review; below → auto; reject → never dispatch | ❌ |
| 7 | `ChannelDispatchNode` | Dispatch via LINE Insurance / email / agent-call-brief (local `ChannelDispatchService`, pluggable sender); S-3 strips raw message from `dispatch_result` | ❌ |
| 8 | `ResponseTrackNode` | Track response outcome (confirmed_renewal / no_response / cancelled / pending) | ❌ |
| 9 | `RetentionReportNode` | Campaign report narrative; S-3 blocks raw `policyholder_id` leakage (aggregate-only) | ✅ |

### Data Flow

```
Outer:  START → initialize → pre_process → main(GraphNode) → {route} → post_process → finalize → END
Inner (inside main):
        START → policy_monitor → lapse_signal_detect → churn_score → retention_offer_select
              → content_generate → hitl_gate → channel_dispatch → response_track → retention_report → END
```

Outer `pre_process` serializes the caller's raw JSON payload into
`validated_input`; `GraphNode.extract_input()` forwards that string as the
inner graph's `user_input`. The inner graph does not see outer state directly
(Cat 2 GraphNode data-flow contract) — its first node (`PolicyMonitorNode`)
`json.loads()`s it back into a dict (`raw_payload`).

### HITL — D6 `interrupt()` (保険業法 第300条 compliance gate)

- `config/config.yaml`: `hitl.enabled: true`, `hitl.max_hitl: 8`, `memory_enabled: true` (mandatory — checkpointer required for interrupt()/resume()).
- `config/config.yaml`'s `high_value_premium_threshold_jpy: 500000` — the compliance
  threshold; policyholders at or above this annual premium require a human
  agent's approval before any offer dispatch.
- The inner subgraph is compiled with its own `InMemorySaver` checkpointer
  (cached on `LapsePreventionGraphNode.__init__`, reused across
  invoke→resume so the paused session is not lost).
- `LapsePreventionGraphNode.propagate_hitl = True`: when the inner
  `HITLGateNode` suspends (`AgentStatus.AWAITING_HUMAN`), the outer graph
  itself re-raises `interrupt()`, so the *whole agent* pauses — the caller
  sees `status: awaiting_human` + `thread_id`, not a partial success.
- Resume: `agent.resume(thread_id, feedback={"action": "approve"|"reject"|"correct", "message": "..."})`.
  - `approve` → dispatch proceeds with the original message.
  - `reject` → `ChannelDispatchNode` skips dispatch (`dispatch_result.delivered = False`), never auto-dispatches.
  - `correct` → the corrected `message` overrides `retention_message` before dispatch.
- On timeout / no resume, the session simply stays `AWAITING_HUMAN` at its
  checkpoint — the offer is never auto-dispatched.

**Known limitation — HITL is structurally incompatible with the Marketplace one-shot Pod entry
point.** The Marketplace platform runner treats `AWAITING_HUMAN` as a failure: a one-shot Pod
invocation has no resume channel, so the first high-value offer that reaches the D6 `interrupt()`
above comes back as `status='error'` (confirmed by exercising the built image locally before push)
instead of pausing for the human-agent review this gate exists to enforce. This is not a defect in
this template — it is a present-state gap in the Marketplace entry point's runtime contract (no
durable, cross-Pod resume path yet; tracked upstream with the framework maintainers), not
something this template's code can work around. Do not disable or bypass `hitl.enabled` to force compatibility —
the D6 gate is this template's whole compliance purpose (保険業法 第300条 sign-off before dispatch),
and removing it to pass a check would defeat that purpose entirely. The standalone HTTP entry point
(`src/api/server.py`, `POST /invoke` + `POST /resume`) is unaffected — resume is reachable there —
and remains the supported deployment path for any invocation that can reach the high-value gate.
This is a present-state constraint, not a permanent exclusion.

### LLM Wiring — Azure OpenAI (enhancement-only, graceful degrade)

- **Nodes**: `RetentionOfferSelectNode` (offer rationale copy only — never the
  offer itself, see the Design Decision Record below), `ContentGenerateNode`
  (retention message copy), `RetentionReportNode` (campaign report narrative).
- **Client construction**: each node builds a fresh `AzureOpenAIClient`
  *inside* `execute()`, on every invocation — never at `__init__`/
  `register_nodes()`, never cached on `self`
  (`src/services/llm_response.py build_azure_llm_client(state)`). The
  constructor's `llm=None` parameter is a **test-double seam only**;
  production wiring (`register_nodes()` in both the outer and inner graph)
  never passes one.
- **Secrets**: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`,
  `AZURE_OPENAI_DEPLOYMENT` — all three declared under `config/agent.yaml`
  `requires.secrets` (none of it in `config/config.yaml`), resolved per
  invocation via `ctx.secrets.require(...)` off `InvocationContext.from_state(state)`.
  `AZURE_OPENAI_ENDPOINT` must be the bare resource endpoint
  (`https://<resource>.services.ai.azure.com`, no `/openai` path segment) —
  `AzureOpenAIClient.__init__` rejects a URL containing one rather than
  rewriting it.
- **Error handling — degrade, never fail**: a missing secret
  (`MissingSecret`), an API error, or an empty/whitespace-only response is
  caught by one broad `except Exception` around the whole build-and-call
  sequence per node, and the node falls back to its existing deterministic
  wording (`src/services/llm_response.py default_offer_rationale` /
  `default_retention_message` / `default_campaign_report`). This is the
  **production path in any environment without the three secrets
  provisioned** — it must never surface as `status=error` and never raise,
  since an LLM outage or an unconfigured key is not a pipeline failure. The
  S-5/第300条 forbidden-phrase gate (`ContentGenerateNode._extra_security_gate_output`)
  and the S-3 policyholder-ID leak gate (`RetentionReportNode._extra_security_gate_output`)
  run identically on both the LLM-generated and the deterministic-fallback
  text.
- **PB-6 safety**: the generic per-node discovery test constructs each node
  with zero args and a minimal state (no `session_id`/`thread_id`/`trace_id`).
  `InvocationContext.from_state(state)` raises `KeyError` on that bare state;
  because the broad `except Exception` wraps every `ctx`-touching line, this
  is swallowed the same as a missing secret and the node degrades cleanly —
  no dispatch-time customization was needed for PB-6 to keep passing.

### State Definition (`src/schemas/state.py`)

All agent-specific fields are `NotRequired[...]` (CoE C8) — absent until the
node that produces them runs.

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `raw_payload` | `dict` | Parsed inner JSON payload (set by `PolicyMonitorNode`) | No |
| `policyholder_id` / `policy_id` | `str` | Policy identifiers | No |
| `days_to_renewal` / `days_to_payment_due` | `int` | Days until due dates | No |
| `renewal_approaching` | `bool` | Renewal within 30 days | No |
| `lapse_signals` / `lapse_signal_count` | `list[str]` / `int` | Detected lapse-risk signals | No |
| `churn_score` / `churn_risk_tier` | `float` / `str` | Lapse probability + tier | No |
| `annual_premium_jpy` / `premium_tier` | `float` / `str` | Premium + tier (standard/high_value) | No |
| `selected_offer` / `offer_rationale` | `dict` / `str` | Matrix-selected offer + LLM rationale | No |
| `retention_message` / `dispatch_channel` | `str` | Generated message + resolved channel | No |
| `requires_human_review` / `hitl_decision` | `bool` / `str` | HITL outcome | No |
| `dispatch_result` | `dict` | Dispatch delivery metadata (PII-stripped) | No |
| `response_outcome` | `str` | Policyholder response tracking | No |
| `campaign_report` | `str` | Aggregate campaign report narrative | No |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types) ✅
- No JWT, API keys, credentials in State ✅ (no secrets used by this template)
- InvocationContext via `config["configurable"]` only (not in State) ✅
- No Pydantic models, dataclass, arbitrary Python objects ✅

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, caller_trust_level)
- [x] S-2: `_extra_security_gate_input()` — not needed beyond the default PII scan (no additional domain input checks identified)
- [x] S-3: `_extra_security_gate_output()` — implemented on `ContentGenerateNode` (blocks 第300条 misleading/guarantee claims), `ChannelDispatchNode` (strips raw message from dispatch_result), `RetentionReportNode` (blocks raw policyholder_id leakage into the aggregate report)
- [x] S-4: `emit_trace_event()` — at least one domain event per `execute()` across all 11 nodes (outer pre/post + 9 inner)

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclasses (8 of 9 inner + outer pre/post) → framework `@final` gate always runs; extended via `_extra_security_gate_input/output()` where domain checks apply.
> - `HITLGateNode` → direct `BaseNode` subclass (required for `interrupt()`); overrides `_security_gate_input`/`_security_gate_output` as no-op passthroughs — S-2 already ran at the outer `PreProcessNode` boundary, and the outbound payload is gated separately by `ChannelDispatchNode`'s own S-3 hook.
> - `LapsePreventionGraphNode` (`GraphNode`) → S-4 emitted via `extract_input()`/`merge_output()` hooks (runs inside `GraphNode.execute()`, which is not overridden itself).

### Composition Pattern

- **Pattern**: Cat 2 — outer `AgentBaseGraph` + `GraphNode` (`main` slot) wrapping inner `BaseGraph` subgraph.
- **Composition target**: `LapsePreventionWorkflowGraph` (`src/graph/lapse_prevention_workflow_graph.py`).
- **Error propagation strategy**: `propagate` (fail fast — inner errors surface as `SubgraphError`); HITL interrupts are the deliberate exception and are re-raised, never wrapped, via `LapsePreventionGraphNode._handle_call_error`.

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only (no `agents/base/` required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Fixed 9-step pipeline with a bounded HITL gate — not an autonomous think/act/observe loop. |
| Composition pattern | Flat Cat 1 3-slot | Cat 2 GraphNode + inner subgraph | **Cat 2 GraphNode + inner subgraph** | 9 business steps require the mandated Cat 2 pattern (`gate-composition`); a flat MainNode would fail CI and violate the reviewed pattern (feedback 2026-06-17). |
| Channel dispatch integration | Live LINE Insurance / insurer backend API | Local/mock `ChannelSender` abstraction | **Local/mock (pluggable)** | LINE Insurance / real insurer-backend integration is a per-insurer deployment pre-requisite (proposal §12 dependency #5), outside this template's engineering scope; the pluggable `ChannelSender` protocol lets a real transport be injected later without touching node logic. |
| Retention offer source | LLM-generated offer | Config-matrix-only (`config/retention_offers.yaml`) | **Config-matrix-only** | S-5 / 保険業法 第300条 control against misleading solicitation — the LLM is confined to phrasing copy around a pre-approved offer, never choosing the offer itself. |
| LLM provider wiring | Constructor-injected client cached across invocations | Fresh `AzureOpenAIClient` per invocation, resolved via `ctx.secrets.require(...)` | **Per-invocation, secret-resolved** | Caching a client built from bound secrets on `self` would leave it reachable by every later caller of the same (registry-cacheable) node instance; the `llm=` constructor parameter is kept only as a test-double seam. |
| LLM failure handling | Surface as `status=error` | Degrade to the existing deterministic wording | **Degrade — never `status=error`** | Azure OpenAI is enhancement-only (copy/rationale/narrative quality), not a required capability; an LLM outage or an unprovisioned secret is an operational fact, not a pipeline failure. Supersedes the template's original "configured LLM failure is error" contract. |
