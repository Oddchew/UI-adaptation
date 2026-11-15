"""Гибрид: InMemory + best-effort ScMemory."""

from __future__ import annotations

import logging
from typing import Optional

from ..types import AdaptationResult, InteractionEvent, ModuleAConfig, UserModel
from .base import IStorage
from .memory import InMemoryStorage
from .sc_memory import ScMemoryStorage

logger = logging.getLogger(__name__)


class HybridStorage(IStorage):
    def __init__(
        self,
        config: Optional[ModuleAConfig] = None,
        ws_url: str = "ws://127.0.0.1:8090/ws_json",
    ) -> None:
        self._memory = InMemoryStorage(config)
        self._sc = ScMemoryStorage(ws_url=ws_url, soft_fail=True)
        self._sc_ready = False

    async def connect_sc(self) -> bool:
        try:
            await self._sc.connect()
            self._sc_ready = self._sc.is_connected()
            return self._sc_ready
        except Exception as e:
            logger.warning("HybridStorage: sc connect failed: %s", e)
            self._sc_ready = False
            return False

    def is_sc_ready(self) -> bool:
        return self._sc_ready

    async def get_user_model(self, user_id: str) -> Optional[UserModel]:
        local = await self._memory.get_user_model(user_id)
        if local:
            return local
        if self._sc_ready:
            remote = await self._sc.get_user_model(user_id)
            if remote:
                await self._memory.save_user_model(remote)
                return remote
        return None

    async def save_user_model(self, model: UserModel) -> None:
        await self._memory.save_user_model(model)
        if self._sc_ready:
            await self._sc.save_user_model(model)

    async def append_event(self, event: InteractionEvent) -> None:
        await self._memory.append_event(event)
        if self._sc_ready:
            await self._sc.append_event(event)

    async def get_events(self, user_id: str, **kwargs):
        local = await self._memory.get_events(user_id, **kwargs)
        if local:
            return local
        if self._sc_ready:
            return await self._sc.get_events(user_id, **kwargs)
        return local

    async def save_adaptation_result(self, result: AdaptationResult) -> None:
        await self._memory.save_adaptation_result(result)
        if self._sc_ready:
            await self._sc.save_adaptation_result(result)

    async def get_adaptation_history(self, user_id: str, limit: int = 50):
        local = await self._memory.get_adaptation_history(user_id, limit)
        if local:
            return local
        if self._sc_ready:
            return await self._sc.get_adaptation_history(user_id, limit)
        return local
