"""Exclusive SC writer coordinator.

SC link updates (read-check-write) are not atomic across clients.
All Module C property writes must go through one ExclusiveScWriter
instance per process (or external lock service). Guarantees:

1. Single in-process writer: asyncio.Lock serialises all SC mutations.
2. Optimistic version token per (interface, component, property).
3. Optional write journal for recovery / audit.
4. Reject concurrent writers when exclusive_writer flag is required.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class WriteToken:
    interface_id: str
    component_id: str
    property: str
    version: int
    expected_value: Any
    new_value: Any
    request_id: str
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class WriteResult:
    ok: bool
    new_version: int
    error: Optional[str] = None
    duration_ms: int = 0


class ExclusiveScWriter:
    """Process-local exclusive coordinator for SC UI property updates."""

    def __init__(self, adapter: Any, *, max_queue: int = 64) -> None:
        if not getattr(adapter, "exclusive_writer", False):
            raise RuntimeError(
                "ExclusiveScWriter requires ScUiModelAdapter(exclusive_writer=True)"
            )
        self.adapter = adapter
        self._lock = asyncio.Lock()
        self._versions: dict[tuple[str, str, str], int] = {}
        self._last_values: dict[tuple[str, str, str], Any] = {}
        self._journal: list[dict[str, Any]] = []
        self._max_queue = max_queue
        self._inflight = 0

    def _key(self, interface_id: str, component_id: str, prop: str) -> tuple[str, str, str]:
        return (interface_id, component_id, prop)

    def current_version(self, interface_id: str, component_id: str, prop: str) -> int:
        return self._versions.get(self._key(interface_id, component_id, prop), 0)

    async def apply(
        self,
        *,
        interface_id: str,
        component_id: str,
        property: str,
        expected: Any,
        new_value: Any,
        request_id: str,
        expected_version: Optional[int] = None,
    ) -> WriteResult:
        started = time.monotonic()
        if self._queued >= self._max_queue:
            return WriteResult(False, 0, "writer_queue_full", 0)
        self._queued += 1
        try:
            async with self._lock:
                key = self._key(interface_id, component_id, property)
                current_version = self._versions.get(key, 0)
                if expected_version is not None and expected_version != current_version:
                    return WriteResult(False, current_version, "version_mismatch",
                                       int((time.monotonic() - started) * 1000))
                try:
                    prop_info = await self.adapter.read_property(interface_id, component_id, property)
                    current = prop_info.value
                    if type(current) is not type(expected) or current != expected:
                        return WriteResult(False, current_version, "old_value_mismatch",
                                           int((time.monotonic() - started) * 1000))
                    if type(current) is type(new_value) and current == new_value:
                        return WriteResult(True, current_version, "no_change_required",
                                           int((time.monotonic() - started) * 1000))
                    await self.adapter.update_property(interface_id, component_id, property, expected, new_value)
                    new_version = current_version + 1
                    self._versions[key] = new_version
                    self._last_values[key] = new_value
                    self._journal.append({
                        "request_id": request_id,
                        "interface_id": interface_id,
                        "component_id": component_id,
                        "property": property,
                        "old": expected,
                        "new": new_value,
                        "version": new_version,
                        "ts": time.time(),
                    })
                    if len(self._journal) > 500:
                        self._journal = self._journal[-500:]
                    return WriteResult(True, new_version, None,
                                       int((time.monotonic() - started) * 1000))
                except Exception as exc:
                    logger.exception("ExclusiveScWriter.apply failed: %s", request_id)
                    return WriteResult(False, current_version, str(exc)[:200],
                                       int((time.monotonic() - started) * 1000))
        finally:
            self._queued -= 1

    def journal(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._journal[-limit:])


class NullScWriter:
    """No-op writer for pure in-memory ModuleC (no SC)."""

    async def apply(self, **kwargs) -> WriteResult:
        return WriteResult(True, 0, None, 0)

    def current_version(self, *args) -> int:
        return 0

    def journal(self, limit: int = 50) -> list:
        return []
