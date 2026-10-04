from typing import Any

from .base import ModelProvider


class ModelRouter:
    def __init__(self, providers: dict[str, ModelProvider]):
        self.providers = providers

    async def chat(
        self,
        messages: list[dict[str, str]],
        provider: str = "nebius",
        max_tokens: int = 800,
    ) -> dict[str, Any]:
        selected = self.providers.get(provider)

        if selected is None:
            available = ", ".join(sorted(self.providers))
            raise ValueError(
                f"Unknown provider '{provider}'. Available providers: {available}"
            )

        return await selected.chat(
            messages=messages,
            max_tokens=max_tokens,
        )
