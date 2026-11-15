"""Абстракция хранилища модуля A."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..types import AdaptationResult, InteractionEvent, UserModel


class IStorage(ABC):
    @abstractmethod
    async def get_user_model(self, user_id: str) -> Optional[UserModel]:
        ...

    @abstractmethod
    async def save_user_model(self, model: UserModel) -> None:
        ...

    @abstractmethod
    async def append_event(self, event: InteractionEvent) -> None:
        ...

    @abstractmethod
    async def get_events(
        self,
        user_id: str,
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[InteractionEvent]:
        ...

    @abstractmethod
    async def save_adaptation_result(self, result: AdaptationResult) -> None:
        ...

    @abstractmethod
    async def get_adaptation_history(
        self, user_id: str, limit: int = 50
    ) -> list[AdaptationResult]:
        ...
