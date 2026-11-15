# OSTIS UI Adaptation (A → B → C)

**Module B** — реальный (`module_b.ModuleB`), не заглушка.  
Правила: `module_b/rules_default.json` или файл из редактора (`*.adaptation.json`).

```bash
# тесты B
PYTHONPATH=. python3 tests/test_module_b.py
# A → B → C
PYTHONPATH=. python3 tests/demo_abc.py
# HTTP demo
MODULE_A_USE_SC=0 python3 integration/server.py
# с правилами из редактора:
ADAPTATION_RULES=./my_ui.adaptation.json MODULE_A_USE_SC=0 python3 integration/server.py
```

Заглушка `MockModuleB` остаётся только в `module_a.mocks` для совместимости.

---

# OSTIS UI Adaptation (A → B → C)

**Модуль B** (реальный): пакет `module_b/` — `from module_b import ModuleB`.

Заглушка B остаётся в `module_a.mocks` для обратной совместимости.

---

# Модуль A (Python) — сбор данных и модель пользователя

**Контур:** run-time адаптация A → B → C  
**Версия:** 0.7  
**Язык:** Python 3.10+

Порт TypeScript-реализации `module_A_adaptation` с теми же контрактами и логикой (mutex, validation, cold_start_notified, ring buffer).

## Быстрый старт

```bash
cd module_A_adaptation_py
python3 tests/demo.py
python3 tests/test_p0_p1.py
python3 tests/test_e2e.py
```

Зависимости для in-memory **не нужны**. Для sc-памяти:

```bash
pip install py-sc-client
```

## Использование

```python
import asyncio
from module_a import (
    ModuleA, InMemoryStorage, ModuleAConfig,
    InteractionEvent, EventType, MockModuleB, MockModuleC,
)

async def main():
    cfg = ModuleAConfig(COLD_START_THRESHOLD=8)
    module_a = ModuleA(InMemoryStorage(cfg), cfg)
    module_b = MockModuleB()
    module_c = MockModuleC()

    module_b.set_command_handler(module_c.apply)
    module_c.set_application_handler(module_a.handle_application_result)
    module_a.set_package_handler(module_b.handle_package)

    await module_a.handle_event(InteractionEvent(
        id="1", user_id="u1", interface_id="ui",
        event_type=EventType.ERROR,
        timestamp="2026-11-15T12:00:00Z",
        error_code="required_field",
    ))
    module_a.dispose()

asyncio.run(main())
```

## Структура

```
module_A_adaptation_py/
├── module_a/
│   ├── module_a.py          # фасад
│   ├── user_model_manager.py
│   ├── package_builder.py
│   ├── validation.py
│   ├── types.py
│   ├── storage/             # memory, sc stub, hybrid
│   ├── frontend/            # EventCollector (серверный API)
│   └── mocks/               # B, C
├── sc/user_model_and_events.scs
├── tests/
└── README.md
```

## Связь с TypeScript-версией

| TS | Python |
|----|--------|
| `src/ModuleA.ts` | `module_a/module_a.py` |
| `UserModelManager` | `user_model_manager.py` |
| `InMemoryStorage` | `storage/memory.py` |
| `ts-sc-client` | `py-sc-client` (опционально) |
| `EventCollector` (DOM) | серверный emit API |

Контракты A→B / C→A — те же, что в `docs/05_contracts_abc.md` исходного модуля.
