"""Fail-closed Gemini client. No paid provider fallback and no rule-signal fallback."""
from __future__ import annotations
import json
import logging
from typing import Any, Dict
import requests
from .config import settings
from .widowmaker import widowmaker

log = logging.getLogger("llm")

class LLMClient:
    def __init__(self):
        self.cfg = settings.llm

    @property
    def available(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.api_key and self.cfg.free_tier_confirmed
                    and self.cfg.provider == "google" and self.cfg.model == "gemini-3.8-flash")

    def complete(self, system: str, user: str) -> str:
        if not self.available:
            return ""
        url = f"{self.cfg.base_url}/models/{self.cfg.model}:generateContent"
        response = requests.post(
            url, params={"key": self.cfg.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": self.cfg.temperature,
                    "maxOutputTokens": self.cfg.max_tokens,
                    "responseMimeType": "application/json",
                },
            }, timeout=30,
        )
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        if not candidates:
            return ""
        return "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []))

    def reason_signal(self, context: Dict[str, Any], rule_signal: Dict[str, Any]) -> Dict[str, Any]:
        hold = {"action": "hold", "confidence": 0.0,
                "rationale": "AI unavailable or response invalid; trading suspended"}
        if not self.available:
            return hold
        system = widowmaker.system_prompt()
        try:
            raw = self.complete(system, widowmaker.user_prompt(context, rule_signal))
            data = json.loads(raw)
            action = str(data.get("action", "")).lower()
            confidence = float(data.get("confidence", 0))
            rationale = str(data.get("rationale", ""))[:300]
            if action not in {"buy", "sell", "hold"} or not 0 <= confidence <= 1 or not rationale:
                return hold
            return {"action": action, "confidence": confidence, "rationale": rationale}
        except Exception as exc:
            # Do not log request URLs, headers, response bodies or API credentials.
            log.warning("Gemini request failed (%s); new decisions paused", type(exc).__name__)
            return hold

llm_client = LLMClient()
