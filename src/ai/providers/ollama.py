"""Ollama provider — local models, no API key, no cost.

Not installed by the GitHub Actions workflow and not required anywhere. See
``docs/ollama.md`` for how to run it locally.
"""

from __future__ import annotations

import json
import logging

LOG = logging.getLogger(__name__)


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: dict) -> None:
        self.base_url = str(settings.get("base_url", "http://localhost:11434")).rstrip("/")
        self.model = str(settings.get("model", "qwen2.5:1.5b"))
        self.timeout = int(settings.get("timeout_seconds", 120))

    def available(self) -> bool:
        try:
            import requests

            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.ok
        except Exception as exc:  # noqa: BLE001
            LOG.info("ollama not reachable at %s: %s", self.base_url, exc)
            return False

    def complete(self, prompt: str, system: str = "") -> str:
        try:
            import requests

            payload = {
                "model": self.model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {"temperature": 0.2},
            }
            response = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            return str(json.loads(response.text).get("response", "")).strip()
        except Exception as exc:  # noqa: BLE001 - AI is optional; never fail the run
            LOG.warning("ollama completion failed: %s", exc)
            return ""
