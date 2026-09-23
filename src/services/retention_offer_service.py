"""AgentCore Platform v1.0"""

# Service layer: loads the retention offer matrix (config/retention_offers.yaml)
# and selects an offer deterministically. This is the S-5 / 保険業法 第300条
# control — RetentionOfferSelectNode may only choose an offer via this service;
# the LLM never invents offer_id/discount/benefit_summary.

from __future__ import annotations

import os
from typing import Any

import yaml

_DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "retention_offers.yaml")


class RetentionOfferService:
    """Loads the retention offer matrix and selects an offer by risk/premium tier."""

    def __init__(self, config_path: str | None = None):
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._matrix: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._matrix is None:
            with open(self._config_path, encoding="utf-8") as f:
                self._matrix = yaml.safe_load(f) or {}
        return self._matrix

    def select_offer(self, churn_risk_tier: str, premium_tier: str) -> dict[str, Any]:
        """Return the offer dict matching (churn_risk_tier, premium_tier).

        Falls back to `default_offer` when no exact match exists in the matrix —
        never fabricates an offer outside the configured matrix.
        """
        matrix = self._load()
        for offer in matrix.get("offers", []):
            if offer.get("churn_risk_tier") == churn_risk_tier and offer.get("premium_tier") == premium_tier:
                return dict(offer)
        return dict(matrix.get("default_offer", {}))
