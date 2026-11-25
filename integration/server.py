#!/usr/bin/env python3
"""
HTTP-сервер: UI ↔ Module A ↔ Module B ↔ Mock C ↔ (опционально) sc-server.

Запуск (из корня UI-adaptation):
  python3 integration/server.py
  # браузер: http://127.0.0.1:8765/

Переменные:
  MODULE_A_PORT=8765
  SC_WS_URL=ws://127.0.0.1:8090/ws_json
  MODULE_A_USE_SC=0          # 0 = только in-memory для модели пользователя
  MODULE_C_USE_SC=0          # 1 = Module C пишет свойства UI через ExclusiveScWriter + ScModelRuntime
  ADAPTATION_RULES=path/to/ui.adaptation.json   # правила из редактора; иначе DEFAULT
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_a import (  # noqa: E402
    AdaptationResult,
    EventType,
    HybridStorage,
    InMemoryStorage,
    InteractionEvent,
    ModuleA,
    ModuleAConfig,
)
from module_b import ModuleB  # noqa: E402 — реальный модуль B, не заглушка
from module_c import ModuleC, SQLiteRepository, default_model, display_state
from module_c.model import AdaptationPolicy
from module_c.catalog import ADAPTABLE_PROPERTIES

STATIC = Path(__file__).resolve().parent / "static"
PORT = int(os.environ.get("MODULE_A_PORT", "8765"))
SC_WS = os.environ.get("SC_WS_URL", "ws://127.0.0.1:8090/ws_json")
USE_SC = os.environ.get("MODULE_A_USE_SC", "0") not in ("0", "false", "False")
USE_SC_C = os.environ.get("MODULE_C_USE_SC", "0") not in ("0", "false", "False")
USE_SC_SHARED_SESSION_MODEL = os.environ.get("MODULE_C_ALLOW_SHARED_SESSION_MODEL", "0") not in ("0", "false", "False")
RULES_PATH = os.environ.get("ADAPTATION_RULES", "").strip()

# --- runtime state ---
_loop: Optional[asyncio.AbstractEventLoop] = None
_module_a: Optional[ModuleA] = None
_module_b: Optional[ModuleB] = None
_module_c: Optional[ModuleC] = None
_repository = None
_runtime = None
_packages: list[dict[str, Any]] = []
_ready = False
_sc_ok = False


class BrowserRuntime:
    def __init__(self):
        self.pending = {}

    async def activate(self, interface_id, model, *, user_id=None, session_id=None):
        token = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[token] = (interface_id, model, future, user_id, session_id)
        try:
            if not await future:
                raise RuntimeError('browser rejected update')
        finally:
            self.pending.pop(token, None)

    def commands(self, user_id, session_id):
        return [{'token': token, 'interface_id': item[0], 'model': item[1]}
                for token, item in self.pending.items() if item[3] == user_id and item[4] == session_id]

    def acknowledge(self, token, success):
        item = self.pending.get(token)
        if item and not item[2].done():
            item[2].set_result(success)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _run(coro):
    assert _loop is not None
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    return fut.result(timeout=30)


async def _bootstrap() -> None:
    global _module_a, _module_b, _module_c, _ready, _sc_ok, _runtime, _repository

    cfg = ModuleAConfig(
        COLD_START_THRESHOLD=2,
        ERROR_RATE_THRESHOLD=0.25,
        HELP_THRESHOLD=3,
        PERIODIC_SNAPSHOT_MS=10 * 60 * 1000,
    )

    storage: Any
    if USE_SC:
        hybrid = HybridStorage(config=cfg, ws_url=SC_WS)
        _sc_ok = await hybrid.connect_sc()
        storage = hybrid
        print(f"[module-a] sc connect: {_sc_ok} ({SC_WS})")
    else:
        storage = InMemoryStorage(cfg)
        _sc_ok = False
        print("[module-a] in-memory only")

    _module_a = ModuleA(storage, cfg)
    # Реальный Module B: правила из редактора (.adaptation.json) или DEFAULT_RULES
    rules_src = RULES_PATH if RULES_PATH else None
    if rules_src:
        print(f"[module-b] rules file: {rules_src}")
    elif not USE_SC_C:
        default_json = ROOT / "module_b" / "rules_default.json"
        if default_json.is_file():
            rules_src = str(default_json)
            print(f"[module-b] rules file: {rules_src}")
        else:
            print("[module-b] built-in DEFAULT_RULES")
    else:
        print("[module-b] no generic rules configured; set ADAPTATION_RULES")
    _module_b = ModuleB(rules=rules_src if rules_src else ([] if USE_SC_C else None))
    _repository = SQLiteRepository(os.environ.get('MODULE_C_DB', str(ROOT / 'module_c.sqlite3')))
    # The SC-backed path discovers each interface by interface_id on demand.
    # The Python tutor seed is retained only for the standalone legacy demo.
    if not USE_SC_C and not await _repository.current('python_tutor_model'):
        _repository.register('python_tutor_model', default_model())
    browser = BrowserRuntime()
    _runtime = browser
    sc_writer = None
    if USE_SC_C:
        try:
            from module_c.sc_model import ScUiModelAdapter, ScModelRuntime
            from module_c.sc_writer import ExclusiveScWriter
            adapter = ScUiModelAdapter(SC_WS, exclusive_writer=True)
            await adapter.connect()
            sc_writer = ExclusiveScWriter(adapter)
            # SC is source of truth for property values; browser confirms screen.
            _runtime = ScModelRuntime(
                adapter,
                browser,
                writer=sc_writer,
                allow_shared_session_model=USE_SC_SHARED_SESSION_MODEL,
            )
            print(f"[module-c] SC writer enabled ({SC_WS})")
        except Exception as exc:
            print(f"[module-c] MODULE_C_USE_SC failed, falling back to browser only: {exc}")
            sc_writer = None
            _runtime = browser
    else:
        print("[module-c] browser/SQLite only (MODULE_C_USE_SC=0)")
    # When ScModelRuntime is used, do not dual-write via ModuleC.sc_writer.
    _module_c = ModuleC(
        _repository,
        _runtime,
        sc_writer=None if USE_SC_C and sc_writer is not None else sc_writer,
    )
    _module_b.set_version_provider(_module_c.active_version)

    async def on_cmd(cmd):
        return await _module_c.apply(cmd)

    _module_b.set_command_handler(on_cmd)

    async def on_app(result: AdaptationResult):
        await _module_a.handle_application_result(result)

    _module_c.set_application_handler(on_app)

    async def retry_outcomes():
        while True:
            await _module_c.retry_notifications()
            await asyncio.sleep(5)

    asyncio.create_task(retry_outcomes())

    async def on_pkg(pkg):
        _packages.append(
            {
                "trigger": pkg.trigger.value,
                "model_version": pkg.model_version,
                "user_id": pkg.user_id,
                "timestamp": pkg.timestamp,
            }
        )
        if len(_packages) > 50:
            del _packages[:-50]
        await _module_b.handle_package(pkg)

    _module_a.set_package_handler(on_pkg)
    _ready = True
    print("[module-a] ready")


def _start_async_loop() -> None:
    global _loop

    def runner():
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_bootstrap())
        _loop.run_forever()

    t = threading.Thread(target=runner, name="module-a-loop", daemon=True)
    t.start()
    # wait ready
    for _ in range(100):
        if _ready:
            break
        time.sleep(0.05)


async def _ensure_interface(interface_id: str) -> None:
    """Lazily import an interface snapshot from SC into Module C's version store."""
    if not isinstance(interface_id, str) or not interface_id.strip():
        raise ValueError("interface_id_required")
    if _repository is None:
        raise RuntimeError("repository_not_ready")
    current = await _repository.current(interface_id)
    if current:
        model = current[1]
    else:
        adapter = getattr(_runtime, "model_adapter", None) if USE_SC_C else None
        if adapter is None:
            raise KeyError(f"unknown interface: {interface_id}")
        model = await adapter.read_model(interface_id)
        _repository.register(interface_id, model)
    # Every component from the SC model receives the catalog's safe property
    # allow-list. Component IDs are scoped by interface at command validation.
    allowed = dict(_module_c.policy.allowed)
    for component in model["components"]:
        allowed[component["id"]] = set(ADAPTABLE_PROPERTIES)
    _module_c.policy = AdaptationPolicy(allowed)


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[http] " + (fmt % args) + "\n")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._serve_file(STATIC / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_file(STATIC / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/style.css":
            self._serve_file(STATIC / "style.css", "text/css; charset=utf-8")
            return

        if path == "/api/health":
            _json_response(
                self,
                200,
                {
                    "ok": _ready,
                    "sc": _sc_ok,
                    "use_sc": USE_SC,
                    "use_sc_c": USE_SC_C,
                    "allow_shared_session_model": USE_SC_SHARED_SESSION_MODEL,
                    "packages": len(_packages),
                },
            )
            return

        if path == "/api/ui-state":
            assert _module_c is not None
            query = parse_qs(parsed.query)
            interface_id = query.get('interface_id', [None])[0]
            if not interface_id and not USE_SC_C:
                interface_id = 'python_tutor_model'
            try:
                _run(_ensure_interface(interface_id))
                current = _run(_module_c.state(interface_id, query.get('user_id', [None])[0], query.get('session_id', [None])[0]))
                if current is None:
                    raise KeyError(f"unknown interface: {interface_id}")
                _json_response(self, 200, {
                    "interface_id": interface_id,
                    "model": current[1],
                    "ui": display_state(current[1]),
                    "version": current[0],
                    "packages": _packages[-10:],
                })
            except (ValueError, KeyError) as exc:
                _json_response(self, 404, {"error": str(exc)})
            except Exception as exc:
                _json_response(self, 502, {"error": str(exc)})
            return

        if path == '/api/runtime/pending':
            query = parse_qs(parsed.query)
            async def pending():
                return _runtime.commands(query.get('user_id', [None])[0], query.get('session_id', [None])[0])
            _json_response(self, 200, {'commands': _run(pending())})
            return

        if path.startswith("/api/model/"):
            user_id = path.split("/api/model/", 1)[1].strip("/") or "user_demo"
            assert _module_a is not None

            async def get_m():
                m = await _module_a.get_user_model(user_id)
                if not m:
                    return None
                return {
                    "user_id": m.user_id,
                    "model_version": m.model_version,
                    "is_cold_start": m.is_cold_start,
                    "cold_start_notified": m.cold_start_notified,
                    "completeness": m.completeness,
                    "experience_level": m.characteristics.experience_level.value,
                    "counters": {
                        "total_events": m.counters.total_events,
                        "total_errors": m.counters.total_errors,
                        "help_requests": m.counters.help_requests,
                        "successful_actions": m.counters.successful_actions,
                        "manual_overrides": m.counters.manual_overrides,
                    },
                    "observation": {
                        "event_count": m.observation.event_count,
                        "recent_error_rate": m.observation.recent_error_rate,
                        "recent_help_rate": m.observation.recent_help_rate,
                    },
                    "preferences": {
                        "theme": m.preferences.theme.value if m.preferences.theme else None,
                        "show_tooltips": m.preferences.show_tooltips,
                    },
                }

            model = _run(get_m())
            _json_response(self, 200, {"model": model})
            return

        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/runtime/ack':
            data = _read_json(self)
            async def ack():
                _runtime.acknowledge(data.get('token'), data.get('success') is True)
            _run(ack())
            _json_response(self, 200, {'ok': True})
            return

        if path == "/api/event":
            if not _ready or _module_a is None:
                _json_response(self, 503, {"error": "not ready"})
                return
            try:
                data = _read_json(self)
            except json.JSONDecodeError:
                _json_response(self, 400, {"error": "invalid json"})
                return

            try:
                et = EventType(data.get("event_type", "successful_action"))
            except ValueError:
                _json_response(self, 400, {"error": "bad event_type"})
                return

            event = InteractionEvent(
                id=data.get("id") or f"e_{uuid.uuid4().hex[:8]}",
                user_id=data.get("user_id") or "user_demo",
                interface_id=data.get("interface_id") or (None if USE_SC_C else "python_tutor_model"),
                timestamp=data.get("timestamp") or _now(),
                event_type=et,
                session_id=data.get('session_id'),
                element_id=data.get("element_id"),
                error_code=data.get("error_code"),
                message=data.get("message"),
                help_type=data.get("help_type"),
                property=data.get("property"),
                old_value=data.get("old_value"),
                new_value=data.get("new_value"),
                action_id=data.get("action_id"),
            )

            if not event.interface_id:
                _json_response(self, 400, {"error": "interface_id_required"})
                return
            try:
                _run(_ensure_interface(event.interface_id))
            except (ValueError, KeyError) as exc:
                _json_response(self, 404, {"error": str(exc)})
                return
            except Exception as exc:
                _json_response(self, 502, {"error": str(exc)})
                return

            async def handle():
                await _module_a.handle_event(event)
                m = await _module_a.get_user_model(event.user_id)
                return m

            model = _run(handle())
            assert _module_c is not None
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "ui": display_state(_run(_module_c.state(event.interface_id, event.user_id, event.session_id))[1]),
                    "packages": _packages[-5:],
                    "model": {
                        "version": model.model_version if model else None,
                        "events": model.counters.total_events if model else 0,
                        "error_rate": model.observation.recent_error_rate if model else 0,
                        "is_cold_start": model.is_cold_start if model else True,
                        "completeness": model.completeness if model else 0,
                    },
                },
            )
            return

        if path == "/api/reset-b":
            assert _module_b is not None
            _module_b.reset_anti_flicker()
            _json_response(self, 200, {"ok": True})
            return

        _json_response(self, 404, {"error": "not found"})

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            _json_response(self, 404, {"error": "file not found", "path": str(path)})
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    if not STATIC.is_dir():
        print(f"Нет каталога static: {STATIC}")
        sys.exit(1)

    _start_async_loop()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[module-a] UI:  http://127.0.0.1:{PORT}/")
    print(f"[module-a] API: http://127.0.0.1:{PORT}/api/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstop")
    finally:
        if _module_a:
            _module_a.dispose()
        server.server_close()


if __name__ == "__main__":
    main()
