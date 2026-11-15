"""
Сборщик событий для Python-сервиса / бэкенда.

В браузере DOM-автосбор остаётся на JS/TS EventCollector.
Здесь — тот же API emit/error/help/manual для серверных интеграций.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from ..module_a import ModuleA
from ..types import EventType, InteractionEvent


class EventCollector:
    def __init__(
        self,
        module_a: ModuleA,
        *,
        user_id: str,
        interface_id: str,
        session_id: Optional[str] = None,
    ) -> None:
        self._a = module_a
        self.user_id = user_id
        self.interface_id = interface_id
        self.session_id = session_id

    def _uid(self) -> str:
        return f"evt_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"

    async def emit(self, event_type: EventType | str, **kwargs: Any) -> None:
        if isinstance(event_type, str):
            event_type = EventType(event_type)
        event = InteractionEvent(
            id=kwargs.pop("id", None) or self._uid(),
            user_id=kwargs.pop("user_id", self.user_id),
            interface_id=kwargs.pop("interface_id", self.interface_id),
            session_id=kwargs.pop("session_id", self.session_id),
            timestamp=kwargs.pop("timestamp", None)
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            event_type=event_type,
            **kwargs,
        )
        await self._a.handle_event(event)

    async def error(self, element_id: str, error_code: str, message: str | None = None) -> None:
        await self.emit(
            EventType.ERROR,
            element_id=element_id,
            error_code=error_code,
            message=message,
            severity="medium",
        )

    async def help_request(self, element_id: str, help_type: str = "tooltip") -> None:
        await self.emit(EventType.HELP_REQUEST, element_id=element_id, help_type=help_type)

    async def successful_action(self, element_id: str, action_id: str | None = None) -> None:
        await self.emit(EventType.SUCCESSFUL_ACTION, element_id=element_id, action_id=action_id)

    async def manual_override(
        self, element_id: str, property: str, old_value: Any, new_value: Any
    ) -> None:
        await self.emit(
            EventType.MANUAL_OVERRIDE,
            element_id=element_id,
            property=property,
            old_value=old_value,
            new_value=new_value,
        )
