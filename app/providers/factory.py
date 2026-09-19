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


PROVIDERS: dict[str, ProviderFactory] = {
    "rule_based": lambda settings: RuleBasedProvider(),
    "ollama": _ollama,
}


def create_provider(settings: Settings) -> LLMProvider:
    factory = PROVIDERS.get(settings.llm_provider)
    if factory:
        try:
            provider = factory(settings)
            if provider.available:
                return provider
        except Exception:
            pass
    return RuleBasedProvider()
