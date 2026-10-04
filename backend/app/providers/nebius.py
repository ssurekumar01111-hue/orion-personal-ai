from typing import Any

import httpx

from ..config import Settings
from .base import ModelProvider


class NebiusProvider(ModelProvider):
    def __init__(self, settings: Settings):
        self.settings = settings

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 800,
    ) -> dict[str, Any]:
        url = f"{self.settings.nebius_base_url.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.settings.nebius_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.settings.nebius_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        timeout = httpx.Timeout(self.settings.model_timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )

        response.raise_for_status()
        return response.json()
