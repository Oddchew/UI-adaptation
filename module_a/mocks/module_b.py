"""Заглушка модуля B."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ..types import PackageAtoB, PackageTrigger


@dataclass
class CommandBtoC:
    request_id: str
    interface_id: str
    user_id: str
    base_version_id: str
    target_element_id: str
    property: str
    old_value: Any
    new_value: Any
    reason: str
    rule_id: str
    source_package_trigger: Optional[str] = None
    created_at: str = ""


CommandHandler = Callable[[CommandBtoC], Awaitable[None] | None]


class MockModuleB:
    def __init__(self) -> None:
        self._applied: set[str] = set()
        self._on_command: Optional[CommandHandler] = None

    def set_command_handler(self, handler: CommandHandler) -> None:
        self._on_command = handler

    def _key(self, user_id: str, rule_id: str) -> str:
        return f"{user_id}|{rule_id}"

    async def handle_package(self, pkg: PackageAtoB) -> Optional[CommandBtoC]:
        if pkg.manual_override or pkg.trigger == PackageTrigger.MANUAL_OVERRIDE:
            return None
        if pkg.trigger == PackageTrigger.COLD_START or pkg.model_snapshot.is_cold_start:
            return None

        snap = pkg.model_snapshot
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if snap.observation.recent_error_rate >= 0.25:
            rule_id = "rule_show_help_on_errors"
            k = self._key(pkg.user_id, rule_id)
            if k in self._applied:
                return None
            self._applied.add(k)
            cmd = CommandBtoC(
                request_id=f"req_{uuid.uuid4().hex[:8]}",
                interface_id=pkg.interface_id,
                user_id=pkg.user_id,
                base_version_id=f"v_{pkg.model_version}",
                target_element_id="help_panel",
                property="visible",
                old_value=False,
                new_value=True,
                reason=f"error_rate={snap.observation.recent_error_rate:.2f}",
                rule_id=rule_id,
                source_package_trigger=pkg.trigger.value,
                created_at=now,
            )
            if self._on_command:
                res = self._on_command(cmd)
                if res is not None:
                    await res  # type: ignore
            return cmd

        help_n = sum(1 for e in pkg.interaction_events if e.event_type.value == "help_request")
        if help_n >= 3:
            rule_id = "rule_enlarge_font_on_help"
            k = self._key(pkg.user_id, rule_id)
            if k in self._applied:
                return None
            self._applied.add(k)
            cmd = CommandBtoC(
                request_id=f"req_{uuid.uuid4().hex[:8]}",
                interface_id=pkg.interface_id,
                user_id=pkg.user_id,
                base_version_id=f"v_{pkg.model_version}",
                target_element_id="main_content",
                property="fontSize",
                old_value=14,
                new_value=16,
                reason=f"help_in_window={help_n}",
                rule_id=rule_id,
                source_package_trigger=pkg.trigger.value,
                created_at=now,
            )
            if self._on_command:
                res = self._on_command(cmd)
                if res is not None:
                    await res  # type: ignore
            return cmd
        return None

    def reset_anti_flicker(self, user_id: Optional[str] = None) -> None:
        if user_id is None:
            self._applied.clear()
        else:
            self._applied = {k for k in self._applied if not k.startswith(user_id + "|")}
