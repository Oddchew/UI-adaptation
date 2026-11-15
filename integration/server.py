#!/usr/bin/env python3
"""
HTTP-сервер: UI ↔ Module A ↔ mocks B/C ↔ (опционально) sc-server.

Запуск (из корня module_A_adaptation_py):
  python3 integration/server.py
  # браузер: http://127.0.0.1:8765/

Переменные:
  MODULE_A_PORT=8765
  SC_WS_URL=ws://127.0.0.1:8090/ws_json
  MODULE_A_USE_SC=1          # 0 = только in-memory
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
    MockModuleB,
    MockModuleC,
)

STATIC = Path(__file__).resolve().parent / "static"
PORT = int(os.environ.get("MODULE_A_PORT", "8765"))
SC_WS = os.environ.get("SC_WS_URL", "ws://127.0.0.1:8090/ws_json")
USE_SC = os.environ.get("MODULE_A_USE_SC", "1") not in ("0", "false", "False")

# --- runtime state ---
_loop: Optional[asyncio.AbstractEventLoop] = None
_module_a: Optional[ModuleA] = None
_module_b: Optional[MockModuleB] = None
_module_c: Optional[MockModuleC] = None
_packages: list[dict[str, Any]] = []
_ready = False
_sc_ok = False


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _run(coro):
    assert _loop is not None
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    return fut.result(timeout=30)


async def _bootstrap() -> None:
    global _module_a, _module_b, _module_c, _ready, _sc_ok

    cfg = ModuleAConfig(
        COLD_START_THRESHOLD=8,
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
    _module_b = MockModuleB()
    _module_c = MockModuleC()

    async def on_cmd(cmd):
        await _module_c.apply(cmd)

    _module_b.set_command_handler(on_cmd)

    async def on_app(result: AdaptationResult):
        await _module_a.handle_application_result(result)

    _module_c.set_application_handler(on_app)

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
                    "packages": len(_packages),
                },
            )
            return

        if path == "/api/ui-state":
            assert _module_c is not None
            _json_response(self, 200, {"ui": _module_c.get_ui_state(), "packages": _packages[-10:]})
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
                interface_id=data.get("interface_id") or "ui_demo",
                timestamp=data.get("timestamp") or _now(),
                event_type=et,
                element_id=data.get("element_id"),
                error_code=data.get("error_code"),
                message=data.get("message"),
                help_type=data.get("help_type"),
                property=data.get("property"),
                old_value=data.get("old_value"),
                new_value=data.get("new_value"),
                action_id=data.get("action_id"),
            )

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
                    "ui": _module_c.get_ui_state(),
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
