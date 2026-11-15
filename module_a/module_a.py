"""Фасад модуля A."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from .package_builder import PackageBuilder
from .storage.base import IStorage
from .storage.memory import InMemoryStorage
from .types import (
    DEFAULT_CONFIG,
    AdaptationResult,
    InteractionEvent,
    ModuleAConfig,
    PackageAtoB,
    PackageTrigger,
    EventType,
)
from .user_model_manager import UserModelManager
from .validation import validate_interaction_event

logger = logging.getLogger(__name__)

PackageHandler = Callable[[PackageAtoB], Awaitable[None] | None]


class ModuleA:
    def __init__(
        self,
        storage: Optional[IStorage] = None,
        config: Optional[ModuleAConfig] = None,
    ) -> None:
        self.config = config or DEFAULT_CONFIG
        self._storage = storage or InMemoryStorage(self.config)
        self._mgr = UserModelManager(self._storage, self.config)
        self._builder = PackageBuilder(self._mgr)
        self._on_package: Optional[PackageHandler] = None
        self._periodic_tasks: dict[str, asyncio.Task] = {}
        self._interface_by_user: dict[str, str] = {}
        self._disposed = False

    def set_package_handler(self, handler: PackageHandler) -> None:
        self._on_package = handler

    async def handle_event(self, raw: InteractionEvent) -> None:
        if self._disposed:
            raise RuntimeError("ModuleA is disposed")
        event = validate_interaction_event(raw, self.config)
        self._interface_by_user[event.user_id] = event.interface_id

        await self._mgr.process_event(event)

        should_send = False
        trigger = PackageTrigger.THRESHOLD
        manual = False

        if event.event_type == EventType.MANUAL_OVERRIDE:
            should_send = True
            trigger = PackageTrigger.MANUAL_OVERRIDE
            manual = True
        else:
            send, trig = await self._mgr.should_send_package(event.user_id, event=event)
            should_send = send
            if trig:
                trigger = PackageTrigger(trig)

        if should_send:
            await self._emit_package(
                event.user_id, event.interface_id, trigger, manual, event.session_id
            )

        self._ensure_periodic(event.user_id, event.interface_id)

    async def handle_application_result(self, result: AdaptationResult) -> None:
        if self._disposed:
            raise RuntimeError("ModuleA is disposed")
        await self._mgr.record_adaptation_result(result)

    async def force_send_package(self, user_id: str, interface_id: str) -> PackageAtoB:
        if self._disposed:
            raise RuntimeError("ModuleA is disposed")
        return await self._emit_package(user_id, interface_id, PackageTrigger.FORCE, False)

    async def get_user_model(self, user_id: str):
        return await self._mgr.get_model(user_id)

    async def get_user_events(self, user_id: str):
        return await self._mgr.get_all_events(user_id)

    async def _emit_package(
        self,
        user_id: str,
        interface_id: str,
        trigger: PackageTrigger,
        manual_override: bool,
        session_id: Optional[str] = None,
    ) -> PackageAtoB:
        pkg = await self._builder.build(user_id, interface_id, trigger, manual_override, session_id)
        if trigger == PackageTrigger.COLD_START:
            await self._mgr.mark_cold_start_notified(user_id)
        if self._on_package:
            try:
                res = self._on_package(pkg)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                logger.exception("ModuleA: package handler error")
        return pkg

    def _ensure_periodic(self, user_id: str, interface_id: str) -> None:
        if self._disposed or self.config.PERIODIC_SNAPSHOT_MS <= 0:
            return
        self._interface_by_user[user_id] = interface_id
        if user_id in self._periodic_tasks:
            return

        async def _loop() -> None:
            interval = self.config.PERIODIC_SNAPSHOT_MS / 1000.0
            while not self._disposed:
                await asyncio.sleep(interval)
                if self._disposed:
                    break
                try:
                    model = await self._mgr.get_model(user_id)
                    iface = self._interface_by_user.get(user_id, interface_id)
                    if model and model.counters.total_events > 0:
                        await self._emit_package(
                            user_id, iface, PackageTrigger.PERIODIC, False
                        )
                except Exception:
                    logger.exception("ModuleA: periodic snapshot error")

        self._periodic_tasks[user_id] = asyncio.create_task(_loop())

    def stop_periodic(self, user_id: Optional[str] = None) -> None:
        if user_id:
            t = self._periodic_tasks.pop(user_id, None)
            if t:
                t.cancel()
        else:
            for t in self._periodic_tasks.values():
                t.cancel()
            self._periodic_tasks.clear()

    def dispose(self) -> None:
        self._disposed = True
        self.stop_periodic()
        self._on_package = None
