"""One extension point for optional AI, shared by the browser UI and CLI.

Factories receive Settings and return an LLMProvider. Providers generate text;
they never receive an executor or bypass core permission and tool validation.
"""
from collections.abc import Callable

from app.core.config import Settings
from app.core.llm import LLMProvider
from app.providers.rule_based import RuleBasedProvider

ProviderFactory = Callable[[Settings], LLMProvider]


def _ollama(settings: Settings) -> LLMProvider:
    from app.providers.ollama import OllamaProvider
    return OllamaProvider(base_url=settings.ollama_url, model=settings.ollama_model)


def _groq(settings: Settings) -> LLMProvider:
    from app.providers.groq import GroqProvider

    return GroqProvider(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        timeout=settings.groq_timeout_seconds,
        max_retries=settings.groq_max_retries,
    )


PROVIDERS: dict[str, ProviderFactory] = {
    "rule_based": lambda settings: RuleBasedProvider(),
    "ollama": _ollama,
    "groq": _groq,
}


def create_provider(settings: Settings) -> LLMProvider:
    factory = PROVIDERS.get(settings.llm_provider)
    if factory:
        try:
            provider = factory(settings)
            if provider.available:
                return provider
        except Exception as exc:
            return RuleBasedProvider(
                f"{settings.llm_provider} unavailable ({type(exc).__name__}); using local command mode"
            )
    reason = None
    if settings.llm_provider not in PROVIDERS:
        reason = f"Unknown AI provider {settings.llm_provider!r}; using local command mode"
    elif settings.llm_provider != "rule_based":
        reason = f"{settings.llm_provider} is not configured; using local command mode"
    return RuleBasedProvider(reason)
