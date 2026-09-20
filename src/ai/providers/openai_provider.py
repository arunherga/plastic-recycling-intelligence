"""OpenAI-compatible provider.

Disabled by default and never used by the scheduled workflow. The API key is
read from an environment variable whose *name* is configured — the key itself
must never appear in this repository. If you enable it, store the key as a
GitHub Actions secret and expose it to the step via ``env:``.
"""

from __future__ import annotations

import logging
import os

LOG = logging.getLogger(__name__)


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: dict) -> None:
        self.model = str(settings.get("model", "gpt-4o-mini"))
        self.base_url = str(settings.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = int(settings.get("timeout_seconds", 120))
        self.api_key_env = str(settings.get("api_key_env", "OPENAI_API_KEY"))

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    def available(self) -> bool:
        if not self.api_key:
            LOG.info("openai provider disabled: %s is not set", self.api_key_env)
            return False
        return True

    def complete(self, prompt: str, system: str = "") -> str:
        if not self.available():
            return ""
        try:
            import requests

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "temperature": 0.2},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"]).strip()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("openai completion failed: %s", exc)
            return ""
