"""
Provider-agnostic LLM client.

Supports OpenAI-compatible endpoints and Anthropic. If no provider/key is
configured (or a call fails), it degrades gracefully to a deterministic
rule-based "reasoner" so the agent always keeps working.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import requests

from .config import settings

log = logging.getLogger("llm")


class LLMClient:
    def __init__(self) -> None:
        self.cfg = settings.llm

    @property
    def available(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.api_key and self.cfg.provider != "rule")

    def complete(self, system: str, user: str) -> str:
        """Return raw text completion. Falls back to empty string on failure."""
        if not self.available:
            return ""
        try:
            if self.cfg.provider == "anthropic":
                return self._anthropic(system, user)
            return self._openai(system, user)
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("LLM call failed (%s); using rule fallback", exc)
            return ""

    def _openai(self, system: str, user: str) -> str:
        base = self.cfg.base_url or "https://api.openai.com/v1"
        resp = requests.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.cfg.api_key}"},
            json={
                "model": self.cfg.model,
                "temperature": self.cfg.temperature,
                "max_tokens": self.cfg.max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _anthropic(self, system: str, user: str) -> str:
        base = self.cfg.base_url or "https://api.anthropic.com/v1"
        resp = requests.post(
            f"{base.rstrip('/')}/messages",
            headers={
                "x-api-key": self.cfg.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.cfg.model,
                "max_tokens": self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    def reason_signal(self, context: Dict[str, Any], rule_signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ask the LLM to review/refine a rule-based signal. Returns a dict with
        keys: action, confidence, rationale. On any issue returns rule_signal.
        """
        if not self.available:
            return rule_signal
        system = (
            "You are a senior quantitative trading analyst. Given market context and a "
            "candidate signal, reply ONLY with JSON: "
            '{"action":"buy|sell|hold","confidence":0-1,"rationale":"short"}. '
            "Be conservative; prefer hold when uncertain."
        )
        user = json.dumps({"context": context, "candidate": rule_signal}, default=str)
        raw = self.complete(system, user)
        if not raw:
            return rule_signal
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            data = json.loads(raw[start:end + 1])
            action = str(data.get("action", rule_signal["action"])).lower()
            if action not in {"buy", "sell", "hold"}:
                return rule_signal
            conf = float(data.get("confidence", rule_signal["confidence"]))
            return {
                "action": action,
                "confidence": max(0.0, min(1.0, conf)),
                "rationale": str(data.get("rationale", rule_signal.get("rationale", "")))[:300],
            }
        except Exception:
            return rule_signal


llm_client = LLMClient()
