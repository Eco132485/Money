"""Optional independent Ollama review. Any disagreement fails closed to HOLD."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import requests

from .widowmaker import widowmaker

log = logging.getLogger("ollama")


class OllamaReviewer:
    def __init__(self):
        self.enabled = os.getenv("OLLAMA_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.base_url = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "gemma4:31b").strip()
        self.api_key = os.getenv("OLLAMA_API_KEY", "").strip()
        self.timeout = max(3, min(int(os.getenv("OLLAMA_TIMEOUT_SECONDS") or "20"), 45))

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.model)

    def review_signal(self, context: Dict[str, Any], candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        hold = {"action": "hold", "confidence": 0.0, "rationale": "Ollama review unavailable; new entries paused", "provider": "Ollama"}
        if not self.configured:
            return hold
        url = self.base_url if self.base_url.endswith("/chat") else self.base_url + ("/chat" if self.base_url.endswith("/api") else "/api/chat")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        try:
            response = requests.post(
                url,
                headers=headers,
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": widowmaker.system_prompt()},
                        {"role": "user", "content": widowmaker.user_prompt(context, candidate)},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            raw = response.json().get("message", {}).get("content", "")
            data = json.loads(raw)
            action = str(data.get("action", "")).lower()
            confidence = float(data.get("confidence", 0))
            rationale = str(data.get("rationale", "")).strip()[:300]
            if action not in {"buy", "sell", "hold"} or not 0 <= confidence <= 1 or not rationale:
                return hold
            return {"action": action, "confidence": confidence, "rationale": rationale, "provider": "Ollama", "model": self.model}
        except Exception as exc:
            log.warning("Ollama review failed (%s); new entries paused", type(exc).__name__)
            return hold


ollama_reviewer = OllamaReviewer()
