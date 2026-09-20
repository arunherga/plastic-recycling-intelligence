"""Concrete LLM providers. Import lazily — none are required to run the agent."""

from __future__ import annotations

__all__ = ["get_provider"]


def get_provider(name: str, settings: dict):
    """Return a provider instance by name, or ``None`` if unknown."""
    lowered = (name or "").lower()
    if lowered == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(settings)
    if lowered == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(settings)
    return None
