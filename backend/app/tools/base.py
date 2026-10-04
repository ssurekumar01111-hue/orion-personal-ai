from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    name: str
    description: str
    permission: str

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError
