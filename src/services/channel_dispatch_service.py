"""AgentCore Platform v1.0"""

# Service layer: channel dispatch abstraction for retention outreach.
# Engineering scope note (docs/02_design.md dependency #5): LINE Insurance /
# real insurer-backend integration is a per-insurer deployment concern outside
# this template's engineering scope. This service provides a pluggable
# ChannelSender protocol with an in-memory/local default implementation so the
# pipeline is fully testable end-to-end without a live external API call.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

VALID_CHANNELS = ("line_insurance", "email", "agent_call_brief")


class ChannelSender(Protocol):
    """Pluggable channel-send contract. Implement to wire a real transport."""

    def send(self, channel: str, recipient_ref: str, message: str) -> dict[str, Any]: ...


class LocalChannelSender:
    """Default local/mock sender — records the dispatch without a live external call.

    Swap for a real LINE Insurance / email / agent-brief transport in deployment
    by injecting a different ChannelSender-compatible object into
    ChannelDispatchService(sender=...).
    """

    def send(self, channel: str, recipient_ref: str, message: str) -> dict[str, Any]:
        return {
            "channel": channel,
            "recipient_ref": recipient_ref,
            "delivered": True,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
            "message_length": len(message),
        }


class ChannelDispatchService:
    """Selects a channel and dispatches the retention message via the injected sender."""

    def __init__(self, sender: ChannelSender | None = None):
        self._sender = sender or LocalChannelSender()

    def dispatch(self, channel: str, recipient_ref: str, message: str) -> dict[str, Any]:
        if channel not in VALID_CHANNELS:
            channel = "email"  # fail-safe default channel
        return self._sender.send(channel=channel, recipient_ref=recipient_ref, message=message)
