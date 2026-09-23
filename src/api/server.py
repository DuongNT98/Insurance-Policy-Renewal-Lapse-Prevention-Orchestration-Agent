"""AgentCore Platform v1.0"""

# Standalone HTTP entry point for INS-C2-056. Entry points are adapters only —
# no business logic here. For platform-level routing, AgentGateway calls
# agent.invoke() directly.
#
# HITL: the outer graph is compiled with a checkpointer (memory_enabled: true /
# hitl.enabled: true in config/config.yaml) so a high-value offer review can
# suspend at /invoke and resume at /resume once a human agent decides.

import os
import secrets
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from shared.secrets import factory as secrets_factory
from src.graph.graph import Graph

app = FastAPI(title="INS-C2-056 Lapse Prevention Orchestration Agent")

agent = Graph()
agent.compile(checkpointer=InMemorySaver())
agent.provision_secrets(secrets_factory(namespace="ins", agent_name="ins-c2-056"))


class InvokeRequest(BaseModel):
    input: str
    session_id: str = ""


class ResumeRequest(BaseModel):
    thread_id: str
    feedback: str | dict[str, Any]


@app.post("/invoke")
async def invoke(req: InvokeRequest, request: Request) -> dict[str, Any]:
    trust = getattr(request.state, "trust_level", TrustLevel.ANONYMOUS)
    # Standalone/STG caller auth: when INVOKE_AUTH_TOKEN is set on the server
    # environment, callers that no upstream middleware vouched for (still
    # ANONYMOUS) must present it as a Bearer token and run at VERIFIED_EXTERNAL.
    # Middleware-established trust is never demoted.
    expected = os.environ.get("INVOKE_AUTH_TOKEN")
    if expected and trust is TrustLevel.ANONYMOUS:
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
            raise HTTPException(status_code=401, detail="Token is invalid or expired.")
        trust = TrustLevel.VERIFIED_EXTERNAL
    with bound_secrets(agent._secrets_provider):
        ctx = InvocationContext(
            session_id=req.session_id or str(uuid4()),
            caller_trust_level=trust,
            caller_id=getattr(request.state, "caller_id", ""),
        )
        # agent.invoke() resolves to Any (AgentBaseGraph is an unstubbed
        # framework type) — cast is descriptive, matching its documented
        # JSON-envelope return contract.
        return cast(dict[str, Any], agent.invoke(req.input, ctx=ctx))


@app.post("/resume")
async def resume(req: ResumeRequest) -> dict[str, Any]:
    """Resume a suspended HITL session (high-value offer review outcome)."""
    with bound_secrets(agent._secrets_provider):
        return cast(dict[str, Any], agent.resume(thread_id=req.thread_id, feedback=req.feedback))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "ins-c2-056"}
