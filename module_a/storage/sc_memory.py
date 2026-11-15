"""
Хранилище модуля A на базе sc-памяти (py-sc-client).

Стратегия:
  - JSON пишется через ScConstruction + ScLinkContent (НЕ через SCs-литерал [...]),
    иначе парсер падает на символах [ ] { } внутри JSON.
  - Отдельный link с текстом-маркером module_a_model:<user_id> для поиска.
  - soft_fail=True по умолчанию.

Требования:
  pip install py-sc-client
  sc-server: ws://127.0.0.1:8090/ws_json
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from ..types import (
    AdaptationResult,
    AnimationLevel,
    DensityPreference,
    DeviceContext,
    EventType,
    ExperienceLevel,
    InteractionEvent,
    ObservationWindow,
    ThemePreference,
    UserCharacteristics,
    UserCounters,
    UserModel,
    UserPreferences,
)
from .base import IStorage

logger = logging.getLogger(__name__)


def _to_jsonable(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    return obj


class ScMemoryStorage(IStorage):
    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:8090/ws_json",
        idtf_prefix: str = "module_a_",
        soft_fail: bool = True,
    ) -> None:
        self.ws_url = ws_url
        self.idtf_prefix = idtf_prefix
        self.soft_fail = soft_fail
        self._connected = False
        # marker -> (payload_link_addr, marker_link_addr)
        self._model_addrs: dict[str, list[Any]] = {}
        self._history_addrs: dict[str, list[Any]] = {}
        # marker -> addr link с JSON (search_links ищет точное content, не подстроку)
        self._payload_by_marker: dict[str, Any] = {}

    # ------------------------------------------------------------------ connect
    async def connect(self) -> None:
        try:
            from sc_client.client import connect, is_connected  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "py-sc-client не установлен: pip install py-sc-client"
            ) from e
        try:
            connect(self.ws_url)
            self._connected = bool(is_connected())
            if not self._connected:
                raise RuntimeError("is_connected() is False after connect()")
            logger.info("ScMemoryStorage connected to %s", self.ws_url)
        except Exception as e:
            self._connected = False
            raise RuntimeError(f"ScMemoryStorage.connect failed: {e}") from e

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        try:
            from sc_client.client import is_connected  # type: ignore

            return bool(is_connected())
        except Exception:
            return self._connected

    async def disconnect(self) -> None:
        try:
            from sc_client.client import disconnect  # type: ignore

            disconnect()
        except Exception:
            pass
        self._connected = False

    def _ensure(self) -> None:
        if not self.is_connected():
            raise RuntimeError("ScMemoryStorage: not connected. Call connect() first.")

    # ------------------------------------------------------------------ markers
    def _marker_model(self, user_id: str) -> str:
        return f"{self.idtf_prefix}model:{user_id}"

    def _marker_event(self, user_id: str, event_id: str) -> str:
        return f"{self.idtf_prefix}event:{user_id}:{event_id}"

    def _marker_history(self, user_id: str, request_id: str) -> str:
        return f"{self.idtf_prefix}hist:{user_id}:{request_id}"

    def _marker_events_index(self, user_id: str) -> str:
        return f"{self.idtf_prefix}events_idx:{user_id}"

    # ------------------------------------------------------------------ low-level API
    def _create_string_link(self, content: str) -> Any:
        """Создать sc-link со строковым содержимым без SCs-парсера."""
        from sc_client.client import generate_elements  # type: ignore
        from sc_client.constants import sc_type  # type: ignore
        from sc_client.models import ScConstruction, ScLinkContent, ScLinkContentType  # type: ignore

        construction = ScConstruction()
        link_content = ScLinkContent(content, ScLinkContentType.STRING)
        construction.generate_link(sc_type.CONST_NODE_LINK, link_content)
        result = generate_elements(construction)
        if not result:
            raise RuntimeError("generate_elements returned empty for link")
        return result[0]

    def _set_link_string(self, addr: Any, content: str) -> None:
        from sc_client.client import set_link_contents  # type: ignore
        from sc_client.models import ScLinkContent, ScLinkContentType  # type: ignore

        set_link_contents(ScLinkContent(content, ScLinkContentType.STRING, addr))

    def _search_links(self, content: str) -> list[Any]:
        from sc_client.client import search_links_by_contents  # type: ignore

        result = search_links_by_contents(content)
        if not result:
            return []
        first = result[0] if isinstance(result, (list, tuple)) else result
        if first is None:
            return []
        if not isinstance(first, (list, tuple)):
            return [first]
        return [a for a in first if a is not None]

    def _get_link_data(self, addr: Any) -> Optional[str]:
        # Актуальный API py-sc-client: get_link_content (не get_links_contents)
        try:
            from sc_client.client import get_link_content  # type: ignore
        except ImportError:
            try:
                from sc_client.client import get_link_contents as get_link_content  # type: ignore
            except ImportError:
                from sc_client.client import get_links_contents as get_link_content  # type: ignore

        try:
            contents = get_link_content(addr)
        except TypeError:
            contents = get_link_content([addr])
        if not contents:
            return None
        # иногда возвращает один объект, не список
        if not isinstance(contents, (list, tuple)):
            contents = [contents]
        item = contents[0]
        if hasattr(item, "data"):
            return str(item.data)
        if isinstance(item, dict) and "data" in item:
            return str(item["data"])
        return str(item) if item is not None else None

    def _erase(self, addrs: list[Any]) -> None:
        if not addrs:
            return
        try:
            from sc_client.client import erase_elements  # type: ignore

            try:
                erase_elements(addrs)
            except TypeError:
                erase_elements(*addrs)
        except Exception as e:
            logger.debug("erase_elements skip: %s", e)

    def _write_json_payload(self, marker: str, payload: dict[str, Any]) -> list[Any]:
        """
        Пишет:
          1) link с содержимым = marker (для search_links_by_contents)
          2) link с содержимым = JSON (полезная нагрузка)
        Возвращает [marker_addr, payload_addr].
        """
        payload = dict(payload)
        payload["__marker__"] = marker
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(raw) > 500_000:
            raw = raw[:500_000]

        # удалить старые link'и с этим marker
        old = self._search_links(marker)
        if old:
            self._erase(old)

        marker_addr = self._create_string_link(marker)
        payload_addr = self._create_string_link(raw)
        self._payload_by_marker[marker] = payload_addr
        return [marker_addr, payload_addr]

    def _read_json_by_marker(self, marker: str) -> Optional[dict[str, Any]]:
        # 1) локальный индекс (тот же процесс / тот же storage)
        addr = self._payload_by_marker.get(marker)
        if addr is not None:
            data = self._get_link_data(addr)
            if data and data.strip().startswith("{"):
                try:
                    obj = json.loads(data)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    pass

        # 2) marker-link существует?
        marker_links = self._search_links(marker)
        if not marker_links and addr is None:
            return None

        # 3) fallback: точный search JSON-строки невозможен без знания полного content;
        #    если payload был записан в этой сессии — уже покрыто п.1
        return None

    def _soft(self, op: str, err: Exception) -> None:
        logger.warning("ScMemoryStorage.%s: %s", op, err)
        if not self.soft_fail:
            raise

    # ------------------------------------------------------------------ UserModel
    async def get_user_model(self, user_id: str) -> Optional[UserModel]:
        self._ensure()
        try:
            data = self._read_json_by_marker(self._marker_model(user_id))
            if not data:
                return None
            return self._dict_to_model(data)
        except Exception as e:
            self._soft("get_user_model", e)
            return None

    async def save_user_model(self, model: UserModel) -> None:
        self._ensure()
        try:
            marker = self._marker_model(model.user_id)
            old = self._model_addrs.get(model.user_id) or []
            if old:
                self._erase(old)
            addrs = self._write_json_payload(marker, _to_jsonable(model))
            self._model_addrs[model.user_id] = addrs
        except Exception as e:
            self._soft("save_user_model", e)

    # ------------------------------------------------------------------ events
    async def append_event(self, event: InteractionEvent) -> None:
        self._ensure()
        try:
            marker = self._marker_event(event.user_id, event.id)
            self._write_json_payload(marker, _to_jsonable(event))

            idx_marker = self._marker_events_index(event.user_id)
            idx = self._read_json_by_marker(idx_marker) or {"ids": []}
            ids = list(idx.get("ids") or [])
            ids.append(event.id)
            if len(ids) > 500:
                ids = ids[-500:]
            self._write_json_payload(
                idx_marker, {"ids": ids, "user_id": event.user_id}
            )
        except Exception as e:
            self._soft("append_event", e)

    async def get_events(
        self,
        user_id: str,
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[InteractionEvent]:
        self._ensure()
        try:
            idx = self._read_json_by_marker(self._marker_events_index(user_id))
            ids = list((idx or {}).get("ids") or [])
            events: list[InteractionEvent] = []
            for eid in ids:
                data = self._read_json_by_marker(self._marker_event(user_id, eid))
                if not data:
                    continue
                try:
                    events.append(self._dict_to_event(data))
                except Exception:
                    continue

            def _ts(e: InteractionEvent) -> float:
                try:
                    return datetime.fromisoformat(
                        e.timestamp.replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    return 0.0

            if from_ts:
                ft = datetime.fromisoformat(from_ts.replace("Z", "+00:00")).timestamp()
                events = [e for e in events if _ts(e) >= ft]
            if to_ts:
                tt = datetime.fromisoformat(to_ts.replace("Z", "+00:00")).timestamp()
                events = [e for e in events if _ts(e) <= tt]
            events.sort(key=_ts)
            if limit is not None and len(events) > limit:
                events = events[-limit:]
            return events
        except Exception as e:
            self._soft("get_events", e)
            return []

    # ------------------------------------------------------------------ history
    async def save_adaptation_result(self, result: AdaptationResult) -> None:
        self._ensure()
        try:
            marker = self._marker_history(result.user_id, result.request_id)
            addrs = self._write_json_payload(marker, _to_jsonable(result))
            self._history_addrs.setdefault(result.user_id, []).extend(addrs)
        except Exception as e:
            self._soft("save_adaptation_result", e)

    async def get_adaptation_history(
        self, user_id: str, limit: int = 50
    ) -> list[AdaptationResult]:
        self._ensure()
        try:
            results: list[AdaptationResult] = []
            for addr in self._history_addrs.get(user_id, []):
                data = self._get_link_data(addr)
                if not data or not data.strip().startswith("{"):
                    continue
                try:
                    obj = json.loads(data)
                    if obj.get("user_id") == user_id:
                        results.append(self._dict_to_result(obj))
                except Exception:
                    continue
            return results[-limit:]
        except Exception as e:
            self._soft("get_adaptation_history", e)
            return []

    # ------------------------------------------------------------------ reconstruct
    def _dict_to_model(self, d: dict[str, Any]) -> UserModel:
        ch = d.get("characteristics") or {}
        ctr = d.get("counters") or {}
        obs = d.get("observation") or {}
        pref = d.get("preferences") or {}
        hist_raw = d.get("adaptation_history") or []

        def _enum(cls, v, default=None):
            if v is None:
                return default
            try:
                return cls(v)
            except Exception:
                return default

        hist = []
        for h in hist_raw:
            if isinstance(h, dict):
                try:
                    hist.append(self._dict_to_result(h))
                except Exception:
                    pass

        return UserModel(
            user_id=str(d.get("user_id") or ""),
            model_version=int(d.get("model_version") or 1),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            is_cold_start=bool(d.get("is_cold_start", True)),
            cold_start_notified=bool(d.get("cold_start_notified", False)),
            completeness=float(d.get("completeness") or 0.0),
            characteristics=UserCharacteristics(
                experience_level=_enum(
                    ExperienceLevel, ch.get("experience_level"), ExperienceLevel.NOVICE
                ),
                preferred_density=_enum(
                    DensityPreference,
                    ch.get("preferred_density"),
                    DensityPreference.COMFORTABLE,
                ),
                accessibility_needs=list(ch.get("accessibility_needs") or []),
            ),
            counters=UserCounters(
                total_events=int(ctr.get("total_events") or 0),
                total_errors=int(ctr.get("total_errors") or 0),
                errors_by_type=dict(ctr.get("errors_by_type") or {}),
                help_requests=int(ctr.get("help_requests") or 0),
                successful_actions=int(ctr.get("successful_actions") or 0),
                block_opens=int(ctr.get("block_opens") or 0),
                block_closes=int(ctr.get("block_closes") or 0),
                manual_overrides=int(ctr.get("manual_overrides") or 0),
                total_sessions=int(ctr.get("total_sessions") or 0),
            ),
            observation=ObservationWindow(
                window_start=str(obs.get("window_start") or ""),
                window_end=str(obs.get("window_end") or ""),
                event_count=int(obs.get("event_count") or 0),
                recent_error_rate=float(obs.get("recent_error_rate") or 0.0),
                recent_help_rate=float(obs.get("recent_help_rate") or 0.0),
            ),
            preferences=UserPreferences(
                show_tooltips=pref.get("show_tooltips"),
                animation_level=_enum(AnimationLevel, pref.get("animation_level")),
                theme=_enum(ThemePreference, pref.get("theme")),
            ),
            adaptation_history=hist,
        )

    def _dict_to_event(self, d: dict[str, Any]) -> InteractionEvent:
        et = d.get("event_type")
        if not isinstance(et, EventType):
            et = EventType(et)
        dc = d.get("device_context")
        device = None
        if isinstance(dc, dict):
            device = DeviceContext(
                type=dc.get("type"),
                screen_width=dc.get("screen_width"),
                screen_height=dc.get("screen_height"),
            )
        return InteractionEvent(
            id=str(d["id"]),
            user_id=str(d["user_id"]),
            interface_id=str(d["interface_id"]),
            event_type=et,
            timestamp=str(d["timestamp"]),
            session_id=d.get("session_id"),
            element_id=d.get("element_id"),
            error_code=d.get("error_code"),
            severity=d.get("severity"),
            message=d.get("message"),
            help_type=d.get("help_type"),
            duration_ms=d.get("duration_ms"),
            action_id=d.get("action_id"),
            property=d.get("property"),
            old_value=d.get("old_value"),
            new_value=d.get("new_value"),
            device_context=device,
        )

    def _dict_to_result(self, d: dict[str, Any]) -> AdaptationResult:
        return AdaptationResult(
            request_id=str(d["request_id"]),
            interface_id=str(d["interface_id"]),
            user_id=str(d["user_id"]),
            success=bool(d["success"]),
            applied_at=str(d["applied_at"]),
            target_element_id=d.get("target_element_id"),
            property=d.get("property"),
            old_value=d.get("old_value"),
            new_value=d.get("new_value"),
            reason=d.get("reason"),
            error_message=d.get("error_message"),
        )
