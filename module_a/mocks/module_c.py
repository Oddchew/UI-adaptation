"""Заглушка модуля C."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..types import AdaptationResult
from .module_b import CommandBtoC


@dataclass
class ResponseCtoB:
    request_id: str
    success: bool
    applied_at: str
    new_version_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


ApplicationHandler = Callable[[AdaptationResult], Awaitable[None] | None]


class MockModuleC:
    def __init__(self) -> None:
        self._ui: dict[str, dict[str, Any]] = {}
        self._version = 1
        self._on_application: Optional[ApplicationHandler] = None

    def set_application_handler(self, handler: ApplicationHandler) -> None:
        self._on_application = handler

    def get_ui_state(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self._ui.items()}

    async def apply(self, cmd: CommandBtoC) -> ResponseCtoB:
        applied_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not cmd.target_element_id:
            res = ResponseCtoB(
                request_id=cmd.request_id,
                success=False,
                applied_at=applied_at,
                error_code="MISSING_TARGET",
                error_message="target_element_id is required",
            )
            await self._notify(cmd, res, False)
            return res

        self._ui.setdefault(cmd.target_element_id, {})[cmd.property] = cmd.new_value
        self._version += 1
        res = ResponseCtoB(
            request_id=cmd.request_id,
            success=True,
            applied_at=applied_at,
            new_version_id=f"ui_v_{self._version}",
        )
        await self._notify(cmd, res, True)
        return res

    async def _notify(self, cmd: CommandBtoC, res: ResponseCtoB, success: bool) -> None:
        if not self._on_application:
            return
        app = AdaptationResult(
            request_id=cmd.request_id,
            interface_id=cmd.interface_id,
            user_id=cmd.user_id,
            success=success,
            applied_at=res.applied_at,
            target_element_id=cmd.target_element_id,
            property=cmd.property,
            old_value=cmd.old_value,
            new_value=cmd.new_value if success else None,
            reason=cmd.reason,
            error_message=res.error_message,
        )
        out = self._on_application(app)
        if out is not None:
            await out  # type: ignore
