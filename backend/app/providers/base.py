from abc import ABC, abstractmethod
from typing import Any


class ModelProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 800,
    ) -> dict[str, Any]:
        """Send a chat request to the provider."""
        raise NotImplementedError
