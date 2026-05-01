from abc import ABC, abstractmethod
from typing import Any


class BaseRepository(ABC):
    @abstractmethod
    async def get_by_id(self, id: int) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def update_status(self, id: int, status: str, **kwargs: Any) -> dict[str, Any] | None:
        raise NotImplementedError

