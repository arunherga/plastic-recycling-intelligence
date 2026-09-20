"""Provider interface for optional LLM backends.

Each provider implements one method: take a prompt, return text. That is the
entire coupling between this project and any model vendor, which is what makes
Ollama / OpenAI / anything-else interchangeable.
"""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    name: str

    def available(self) -> bool:
        """Can this provider actually be reached right now?"""
        ...

    def complete(self, prompt: str, system: str = "") -> str:
        """Return the model's text response, or "" on failure."""
        ...
