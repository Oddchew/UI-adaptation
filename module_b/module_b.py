"""Модуль B — принятие решения об адаптации и формирование команды.

Правила — декларативные (rule_schema / JSON из редактора).
Встроенный DEFAULT_RULES = бывшие R1–R3.
"""

from __future__ import annotations

import json
import inspect
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Sequence, Union

from module_a.types import PackageAtoB, PackageTrigger, session_key

from .models import (
    DEFAULT_B_CONFIG,
    CommandBtoC,
    DecisionResult,
    DecisionStatus,
    ModuleBConfig,
    RejectReason,
)
from .rule_engine import choose_minimal_intervention, evaluate_declarative_rules
from .rule_schema import (
    DEFAULT_RULES,
    AdaptationRule,
    rules_from_jsonable,
)

CommandHandler = Callable[[CommandBtoC], Awaitable[None] | None]
RulesSource = Union[Sequence[AdaptationRule], Sequence[dict[str, Any]], str, Path, None]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_rules(source: RulesSource) -> list[AdaptationRule]:
    if source is None:
        return list(DEFAULT_RULES)
    if isinstance(source, (str, Path)):
        path = Path(source)
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "rules" in data:
            data = data["rules"]
        return rules_from_jsonable(list(data))
    if not source:
        return []
    first = source[0]
    if isinstance(first, AdaptationRule):
        return list(source)  # type: ignore[arg-type]
    return rules_from_jsonable(list(source))  # type: ignore[arg-type]


def is_forbidden_target(target_element_id: str, cfg: ModuleBConfig) -> bool:
    t = (target_element_id or "").lower()
    for forbidden in cfg.FORBIDDEN_TARGETS:
        fl = forbidden.lower()
        if fl in t or t in fl:
            return True
    return False


class ModuleB:
    """Фасад модуля принятия решения об адаптации."""

    def __init__(
        self,
        config: Optional[ModuleBConfig] = None,
        rules: RulesSource = None,
    ) -> None:
        self.config = config or DEFAULT_B_CONFIG
        self._rules: list[AdaptationRule] = _load_rules(rules)
        self._on_command: Optional[CommandHandler] = None
        self._applied: set[str] = set()
        self._version_provider = None

    def set_version_provider(self, provider) -> None:
        self._version_provider = provider

    @property
    def rules(self) -> list[AdaptationRule]:
        return list(self._rules)

    def set_rules(self, rules: RulesSource) -> None:
        """Подменить набор правил (из редактора / JSON / списка)."""
        self._rules = _load_rules(rules)

    def set_command_handler(self, handler: CommandHandler) -> None:
        self._on_command = handler

    def _key(self, user_id: str, rule_id: str, session_id: str = 'default', interface_id: str = '') -> str:
        return f"{user_id}|{interface_id}|{session_id}|{rule_id}"

    def reset_anti_flicker(self, user_id: Optional[str] = None) -> None:
        if user_id is None:
            self._applied.clear()
        else:
            prefix = user_id + "|"
            self._applied = {k for k in self._applied if not k.startswith(prefix)}

    async def handle_package(self, pkg: PackageAtoB) -> Optional[CommandBtoC]:
        result = await self.decide(pkg)
        if result.status == DecisionStatus.COMMAND and result.command is not None:
            if self._on_command is not None:
                out = self._on_command(result.command)
                if inspect.isawaitable(out):
                    out = await out
                if getattr(out, 'status', None) == 'applied' or getattr(out, 'success', False):
                    session = (pkg.interaction_events[-1].session_id or 'default') if pkg.interaction_events else 'default'
                    self._applied.add(self._key(pkg.user_id, result.command.rule_id, session, pkg.interface_id))
            return result.command
        return None

    async def decide(self, pkg: PackageAtoB) -> DecisionResult:
        cfg = self.config

        last = pkg.interaction_events[-1] if pkg.interaction_events else None
        session_id = last.session_id if last else None
        version = None
        if self._version_provider:
            parameters = inspect.signature(self._version_provider).parameters
            if len(parameters) >= 3:
                version = self._version_provider(pkg.interface_id, pkg.user_id, session_id)
            else:
                version = self._version_provider(pkg.interface_id)
        if inspect.isawaitable(version):
            version = await version
        if not version:
            return DecisionResult(status=DecisionStatus.REJECTED, reject_reason=RejectReason.INSUFFICIENT_DATA, reject_message='активная версия интерфейса недоступна')
        if last and last.event_type.value == 'hint_hide':
            return DecisionResult(status=DecisionStatus.COMMAND, command=CommandBtoC(
                request_id=f'req_{uuid.uuid4().hex}', interface_id=pkg.interface_id,
                user_id=pkg.user_id, base_version_id=version, target_element_id='hints_panel',
                property='visible', old_value=True, new_value=False, reason='пользователь скрыл подсказку',
                rule_id='user_hide_hint', source_event_ids=[last.id], created_at=_now_iso(), session_id=session_id))
        if last and last.event_type.value == 'block_open' and last.element_id == 'history_content':
            return DecisionResult(status=DecisionStatus.COMMAND, command=CommandBtoC(
                request_id=f'req_{uuid.uuid4().hex}', interface_id=pkg.interface_id,
                user_id=pkg.user_id, base_version_id=version, target_element_id='history_content',
                property='visible', old_value=False, new_value=True, reason='пользователь развернул историю',
                rule_id='user_open_history', source_event_ids=[last.id], created_at=_now_iso(), session_id=session_id))

        if pkg.manual_override or pkg.trigger == PackageTrigger.MANUAL_OVERRIDE:
            return DecisionResult(
                status=DecisionStatus.REJECTED,
                reject_reason=RejectReason.MANUAL_OVERRIDE,
                reject_message="ручной режим / manual_override — авто-команды запрещены",
            )

        n_events = len(pkg.interaction_events)
        if n_events == 0:
            n_events = int(getattr(pkg.model_snapshot.observation, "event_count", 0) or 0)
        if n_events < cfg.MIN_EVENTS_IN_WINDOW:
            return DecisionResult(
                status=DecisionStatus.REJECTED,
                reject_reason=RejectReason.INSUFFICIENT_DATA,
                reject_message=f"событий в окне {n_events} < {cfg.MIN_EVENTS_IN_WINDOW}",
            )

        if pkg.model_snapshot.is_cold_start and n_events < 2:
            return DecisionResult(
                status=DecisionStatus.REJECTED,
                reject_reason=RejectReason.COLD_START,
                reject_message="cold_start: адаптация отложена до накопления модели",
            )

        import copy
        scoped = copy.copy(pkg)
        if last:
            scoped.interaction_events = [e for e in pkg.interaction_events if e.interface_id == pkg.interface_id and e.session_id == last.session_id]
        matches = evaluate_declarative_rules(scoped, self._rules)
        if last and session_key(pkg.interface_id, last.session_id) in pkg.model_snapshot.hint_hidden_sessions:
            matches = [m for m in matches if m.target_element_id != 'hints_panel']
        if cfg.ANTI_FLICKER:
            session = (last.session_id or 'default') if last else 'default'
            matches = [m for m in matches if self._key(pkg.user_id, m.rule_id, session, pkg.interface_id) not in self._applied]
        if not matches:
            return DecisionResult(
                status=DecisionStatus.REJECTED,
                reject_reason=RejectReason.NO_RULE_MATCHED,
                reject_message="ни одно правило не сработало",
            )

        chosen = choose_minimal_intervention(matches)
        if chosen is None:
            return DecisionResult(
                status=DecisionStatus.REJECTED,
                reject_reason=RejectReason.NO_RULE_MATCHED,
                reject_message="после стратегии минимального вмешательства пусто",
            )

        constraints = list(chosen.constraints) or [
            "не изменять code_editor.content",
            "не изменять этап задания",
            "не изменять критерии проверки",
        ]

        cmd = CommandBtoC(
            request_id=f"req_{uuid.uuid4().hex[:10]}",
            interface_id=pkg.interface_id,
            user_id=pkg.user_id,
            base_version_id=version,
            target_element_id=chosen.target_element_id,
            property=chosen.property,
            old_value=chosen.old_value,
            new_value=chosen.new_value,
            reason=chosen.reason,
            rule_id=chosen.rule_id,
            source_event_ids=list(chosen.source_event_ids),
            constraints=constraints,
            source_package_trigger=pkg.trigger.value if pkg.trigger else None,
            created_at=_now_iso(),
            session_id=session_id,
        )

        if is_forbidden_target(cmd.target_element_id, cfg):
            return DecisionResult(
                status=DecisionStatus.REJECTED,
                reject_reason=RejectReason.CONSTRAINT_VIOLATION,
                reject_message=f"запрещённая цель: {cmd.target_element_id}",
            )

        return DecisionResult(status=DecisionStatus.COMMAND, command=cmd)
