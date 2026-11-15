# Модуль A: сбор данных и модель пользователя  
## Полная техническая документация

| Поле | Значение |
|------|----------|
| Проект | Среда разработки компонентов пользовательских интерфейсов ostis-систем |
| Контур | Run-time адаптация UI (A → B → C) |
| Модуль | **A** — сбор событий взаимодействия, ведение модели пользователя, формирование пакетов A→B |
| Реализация | Python 3.10+ (`module_A_adaptation_py`)|
| Версия | 0.1 |
| Платформа интеграции | OSTIS / sc-machine (ostis-example-app), WebSocket `ws://127.0.0.1:8090/ws_json` |

---

## 1. Назначение и место в архитектуре

### 1.1. Два контура проекта

Проект разделяется на:

1. **Design-time** — инструментальная среда визуального конструирования UI  
   (в т.ч. [ostis-ui-editor](https://github.com/vodo4kin/ostis-ui-editor): React/TypeScript, модель UI в sc-памяти, `concept_ui_*` / `nrel_ui_*`).
2. **Run-time** — адаптация уже развёрнутого интерфейса во время эксплуатации пользователя.

Run-time декомпозирован на три модуля:

```
Пользователь / UI
       │  InteractionEvent
       ▼
┌──────────────────────────────────────┐
│  A. Сбор данных + модель пользователя │  ← данный документ
│     • счётчики, окно наблюдения      │
│     • cold start / пороги            │
│     • пакет PackageAtoB              │
└──────────────────┬───────────────────┘
                   │ PackageAtoB
                   ▼
┌──────────────────────────────────────┐
│  B. Принятие решения об адаптации    │  (правила, стратегия, команда)
└──────────────────┬───────────────────┘
                   │ AdaptationCommand
                   ▼
┌──────────────────────────────────────┐
│  C. Применение изменения к UI        │
│     + AdaptationResult → обратно в A │
└──────────────────────────────────────┘
```

### 1.2. Зона ответственности модуля A

Модуль A **не** решает, какое свойство UI менять, и **не** меняет DOM/SC-структуру интерфейса. Он:

1. принимает и валидирует события взаимодействия;
2. поддерживает актуальную **модель пользователя**;
3. по правилам порогов / cold start / manual override формирует **пакет A→B**;
4. принимает **результаты применения** от модуля C и обновляет историю адаптации;
5. опционально сохраняет снимки в sc-память (OSTIS).

### 1.3. Вне зоны A

| Компонент | Кто |
|-----------|-----|
| Визуальный редактор UI | ostis-ui-editor (design-time) |
| Правила адаптации, выбор свойства | модуль B |
| Применение к DOM / runtime UI | модуль C |
| Нативные SCP/C++ агенты problem-solver | отдельный этап |

В текущей поставке B и C представлены **mocks** для сквозной проверки контура.

---

## 2. Функциональные требования

| ID | Требование | Реализация |
|----|------------|------------|
| FR-1 | Приём типизированных событий взаимодействия | `InteractionEvent`, `EventType` |
| FR-2 | Ведение модели пользователя с версионированием | `UserModel.model_version` |
| FR-3 | Cold start: уведомление B после N первых событий | `COLD_START_THRESHOLD`, флаг `cold_start_notified` |
| FR-4 | Пороговые триггеры (ошибки, help, …) | `ModuleAConfig`, `UserModelManager` |
| FR-5 | Немедленный пакет при `manual_override` | `PackageTrigger.MANUAL_OVERRIDE` |
| FR-6 | Формирование пакета A→B | `PackageBuilder`, `PackageAtoB` |
| FR-7 | Учёт результата C | `handle_application_result` |
| FR-8 | Абстракция хранения | `IStorage`: memory / sc / hybrid |
| FR-9 | Интеграция со sc-server | `ScMemoryStorage`, `py-sc-client` |
| FR-10 | Демо-UI и HTTP API для проверки | `integration/server.py` |

---

## 3. Структура репозитория

```text
module_A_adaptation_py/
├── module_a/
│   ├── __init__.py              # публичный API
│   ├── module_a.py              # фасад ModuleA
│   ├── user_model_manager.py    # обновление модели, пороги, locks
│   ├── package_builder.py       # сборка PackageAtoB
│   ├── validation.py            # валидация событий
│   ├── types.py                 # типы, enum, ModuleAConfig
│   ├── storage/
│   │   ├── base.py              # IStorage
│   │   ├── memory.py            # InMemoryStorage
│   │   ├── sc_memory.py         # ScMemoryStorage (py-sc-client)
│   │   └── hybrid.py            # HybridStorage
│   ├── frontend/
│   │   └── event_collector.py   # заготовка сборщика DOM-событий
│   └── mocks/
│       ├── module_b.py          # MockModuleB
│       └── module_c.py          # MockModuleC
├── sc/
│   └── user_model_and_events.scs   # SC-формализация
├── integration/
│   ├── install_kb.sh            # установка .scs в example-app
│   ├── server.py                # HTTP API + статика UI
│   ├── static/                  # демо-интерфейс
│   └── README.md
├── tests/
│   ├── demo.py
│   ├── demo_sc.py
│   ├── test_p0_p1.py
│   └── test_e2e.py
├── docs/
│   └── 00_FULL_DOCUMENTATION.md  # этот документ
├── requirements.txt
├── pyproject.toml
└── README.md
```

Параллельная реализация на TypeScript: каталог `module_A_adaptation/` (те же контракты).

---

## 4. Модель данных

### 4.1. Типы событий (`EventType`)

| Значение | Смысл |
|----------|--------|
| `error` | ошибка в UI (валидация, сбой действия) |
| `help_request` | запрос помощи / подсказки |
| `block_open` / `block_close` | раскрытие / свёртывание блока |
| `successful_action` | успешное действие |
| `focus` / `blur` | фокус элемента |
| `manual_override` | ручное изменение настройки пользователем |
| `time_spent` | время пребывания (опционально) |

### 4.2. `InteractionEvent`

Обязательные поля: `id`, `user_id`, `interface_id`, `event_type`, `timestamp` (ISO-8601).

Опциональные (по типу): `element_id`, `error_code`, `severity`, `message`, `help_type`, `duration_ms`, `action_id`, `property`, `old_value`, `new_value`, `session_id`, `device_context`.

### 4.3. `UserModel`

| Группа | Содержание |
|--------|------------|
| Идентификация | `user_id`, `model_version`, `created_at`, `updated_at` |
| Cold start | `is_cold_start`, `cold_start_notified` |
| Полнота | `completeness` ∈ [0, 1] |
| Характеристики | `experience_level`, `preferred_density`, `accessibility_needs` |
| Счётчики | события, ошибки (в т.ч. по типам), help, успехи, opens/closes, overrides, сессии |
| Окно наблюдения | `window_start/end`, `event_count`, `recent_error_rate`, `recent_help_rate` |
| Предпочтения | theme, tooltips, animation_level |
| История | список `AdaptationResult` |

### 4.4. Триггеры пакета (`PackageTrigger`)

| Триггер | Условие |
|---------|---------|
| `cold_start` | набрано ≥ `COLD_START_THRESHOLD` событий и ещё не уведомляли B |
| `threshold` | превышен порог error_rate / help и т.п. в окне наблюдения |
| `manual_override` | событие ручного изменения |
| `periodic` | по таймеру (если включено) |
| `force` | принудительная отправка |
| `application_result` | связан с обратной связью C (служебный) |

### 4.5. `PackageAtoB`

Минимальный состав:

- `user_id`, `interface_id`, `timestamp`;
- `trigger`;
- `model_version` + снимок существенных полей модели;
- контекст последних событий / агрегаты (error_rate, counters).

Точный набор полей — в `types.py` / `PackageBuilder`.

### 4.6. `AdaptationResult` (C → A)

`request_id`, `interface_id`, `user_id`, `success`, `applied_at`, опционально `target_element_id`, `property`, `old_value`, `new_value`, `reason`, `error_message`.

---

## 5. Конфигурация (`ModuleAConfig`)

Типичные параметры (значения по умолчанию заданы в коде; для демо/интеграции могут переопределяться):

| Параметр | Назначение |
|----------|------------|
| `COLD_START_THRESHOLD` | число событий до первого пакета cold_start (часто 5–8) |
| `ERROR_RATE_THRESHOLD` | доля ошибок в окне для threshold |
| `HELP_THRESHOLD` | порог запросов помощи |
| `OBSERVATION_WINDOW_*` | размер/длительность окна наблюдения |
| `PERIODIC_SNAPSHOT_MS` | период периодических пакетов (0 — выкл.) |
| лимиты ring buffer | ограничение хранимых событий |

Пороги подбираются экспериментально; для воспроизводимых тестов задаются явно в `ModuleAConfig(...)`.

---

## 6. Алгоритм работы

### 6.1. Обработка события

```
handle_event(event)
  1. validate_interaction_event
  2. process_event (под lock на user_id):
       append_event → storage
       обновить counters / observation / completeness
       пересчитать is_cold_start
       save_user_model
  3. решить should_send + trigger:
       • MANUAL_OVERRIDE → always
       • cold_start: events ≥ threshold AND NOT cold_start_notified
         → cold_start_notified = true
       • threshold по error_rate / help / …
  4. если should_send:
       PackageBuilder.build → on_package(handler)  // обычно → B
```

**Важно:** флаг `cold_start_notified` выставляется так, чтобы cold_start **не** блокировался преждевременным сбросом `is_cold_start` до отправки пакета (исправление P0).

### 6.2. Обратная связь C

```
handle_application_result(result)
  → storage.save_adaptation_result
  → дополнение adaptation_history в UserModel
  → save_user_model
```

### 6.3. Потокобезопасность

В Python-реализации обновление модели на одного `user_id` сериализуется через `asyncio.Lock` (один lock на пользователя), что исключает гонки при параллельных `handle_event`.

---

## 7. Хранилища

### 7.1. Интерфейс `IStorage`

- `get_user_model` / `save_user_model`
- `append_event` / `get_events`
- `save_adaptation_result` / `get_adaptation_history`

### 7.2. `InMemoryStorage`

Полностью в RAM процесса. Достаточен для тестов, демо и курсовой демонстрации логики A. Зависимостей нет.

### 7.3. `ScMemoryStorage`

Клиент **py-sc-client** к sc-server:

- URL по умолчанию: `ws://127.0.0.1:8090/ws_json`;
- снимки модели и событий — JSON в sc-link;
- маркеры вида `module_a_model:<user_id>`;
- `soft_fail=True` — ошибки sc не роняют ModuleA.

Ограничения MVP: надёжное чтение «новым» процессом зависит от search API; в рамках одной сессии сервиса чтение/запись подтверждены.

### 7.4. `HybridStorage`

Сначала **InMemory** (источник истины для логики), параллельно попытка записи в sc. Рекомендуемый режим при живом example-app.

---

## 8. SC-формализация

Файл: `sc/user_model_and_events.scs`.

Вводит (фрагментарно):

- классы событий: `concept_interaction_event`, `concept_error_event`, …;
- модель: `concept_user_model` и отношения (`nrel_model_version`, `nrel_is_cold_start`, …);
- пакет: `concept_package_a_to_b`;
- результат адаптации: связанные понятия для C→A.

Установка в ostis-example-app:

```bash
bash integration/install_kb.sh
cd "$OSTIS_EXAMPLE_APP"   # по умолчанию ~/Sundries/ostis/ostis-example-app
./scripts/start.sh build_kb
./scripts/start.sh machine
```

Схема UI редактора (`abstract_ui_model.scs`) устанавливается **отдельно** и не заменяет онтологию модуля A.

---

## 9. Публичный API Python

```python
from module_a import (
    ModuleA,
    ModuleAConfig,
    InMemoryStorage,
    HybridStorage,
    ScMemoryStorage,
    InteractionEvent,
    EventType,
    PackageAtoB,
    AdaptationResult,
    MockModuleB,
    MockModuleC,
)

cfg = ModuleAConfig(COLD_START_THRESHOLD=8)
storage = InMemoryStorage(cfg)          # или HybridStorage(...)
module_a = ModuleA(storage, cfg)

async def on_package(pkg: PackageAtoB):
    ...

module_a.set_package_handler(on_package)

await module_a.handle_event(
    InteractionEvent(
        id="e1",
        user_id="user_001",
        interface_id="ui_main",
        event_type=EventType.ERROR,
        timestamp="2026-11-15T12:00:00Z",
        error_code="validation",
    )
)

model = await module_a.get_user_model("user_001")
module_a.dispose()
```

Сквозной контур с mocks:

```python
b, c = MockModuleB(), MockModuleC()
b.set_command_handler(c.apply)
c.set_application_handler(module_a.handle_application_result)
module_a.set_package_handler(b.handle_package)
```

---

## 10. HTTP API и демо-интерфейс

Запуск:

```bash
cd module_A_adaptation_py
python3 integration/server.py
# MODULE_A_USE_SC=0 — без sc
# MODULE_A_PORT=8765
```

UI: **http://127.0.0.1:8765/**

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | готовность A, флаг sc |
| POST | `/api/event` | тело = поля InteractionEvent (JSON) |
| GET | `/api/model/{user_id}` | снимок модели |
| GET | `/api/ui-state` | состояние после Mock C + последние пакеты |
| POST | `/api/reset-b` | сброс anti-flicker mock B |

Демо-форма генерирует `error`, `successful_action`, `help_request`, `manual_override` и отображает модель и UI-state (help_panel, fontSize, theme).

---

## 11. Связь с ostis-ui-editor и example-app

| Компонент | Порт / путь | Роль |
|-----------|-------------|------|
| sc-machine | `127.0.0.1:8090` | общая sc-память |
| ostis-example-app KB | `knowledge-base/` | `.scs`, в т.ч. module_a, ui_editor_model |
| ostis-ui-editor | Vite, обычно `:5173` | design-time редактор UI |
| Module A server | `:8765` | run-time A + демо |
| sc-web | `:8000` | просмотр KB (не адаптация) |

Идентификаторы элементов (`element_id`) целесообразно согласовывать с каталогом компонентов редактора (`docs/catalog.md` в ostis-ui-editor), чтобы будущие B/C адресовали те же узлы модели UI.

---

## 12. Тестирование

| Скрипт | Назначение |
|--------|------------|
| `tests/demo.py` | сценарии cold_start, threshold, manual_override, C→A |
| `tests/demo_sc.py` | connect к sc, hybrid, read-back |
| `tests/test_p0_p1.py` | регрессия критичных/важных исправлений |
| `tests/test_e2e.py` | A→B→C на mocks |

```bash
python3 tests/demo.py
python3 tests/test_p0_p1.py
python3 tests/test_e2e.py
# при запущенном sc-machine:
python3 tests/demo_sc.py
```

Критерии приёмки MVP модуля A:

1. События обновляют модель и счётчики.  
2. Cold start даёт ровно один (логически корректный) пакет при достижении порога.  
3. Threshold и manual_override порождают пакеты.  
4. Результат C попадает в историю.  
5. Демо UI на `:8765` воспроизводит цепочку без падения.  
6. (Опционально) `HybridStorage.connect_sc() == True` при живом sc-server.

---

## 13. Зависимости

| Режим | Зависимости |
|-------|-------------|
| In-memory, тесты, демо-логика | только стандартная библиотека Python 3.10+ |
| Sc / hybrid | `py-sc-client` (совместим со sc-machine ~0.10) |
| TypeScript-ветка | `ts-sc-client`, `ws`, TypeScript/Node |

`requirements.txt` / `pyproject.toml` — см. корень модуля.

---

## 14. Ограничения и дальнейшее развитие

**Ограничения текущей версии**

- B и C — заглушки (правила упрощены: help при ошибках, fontSize при help и т.д.).
- Sc-хранение — MVP (JSON-link + маркеры); полноценная навигация только SC-конструкциями — следующий шаг.
- Нет встроенного агента в problem-solver (C++/SCP).
- События из ostis-ui-editor preview ещё не подключены «из коробки» (нужен тонкий клиент `POST /api/event` или TS-ModuleA).

**Направления развития**

1. Реальный модуль B (база правил / стратегии) и C (применение к runtime UI / SC-модели).  
2. EventCollector в preview редактора с `data-ui-id`.  
3. Углубление SC-онтологии и отказ от «только JSON» там, где нужна семантическая совместимость агентов.  
4. Метрики качества адаптации (до/после) для отчёта по гранту.

---

## 15. Быстрый чеклист развёртывания

```bash
# KB
bash integration/install_kb.sh
cd ~/Sundries/ostis/ostis-example-app && ./scripts/start.sh build_kb && ./scripts/start.sh machine

# Модуль A + UI
cd ~/Sundries/ostis/module_A_adaptation_py
pip install py-sc-client          # при необходимости
python3 tests/demo.py
python3 integration/server.py
# браузер → http://127.0.0.1:8765/
```

Проверка порта sc: `ss -tlnp | grep 8090`.

---

## 16. Глоссарий

| Термин | Определение |
|--------|-------------|
| OSTIS | Open Semantic Technology for Intelligent Systems |
| sc-machine / sc-server | хранилище SC-кода и WebSocket API |
| InteractionEvent | факт взаимодействия пользователя с UI |
| UserModel | агрегированное представление опыта и предпочтений пользователя |
| PackageAtoB | сообщение от A к B с основанием для решения |
| Cold start | фаза недостатка данных о пользователе |
| HybridStorage | InMemory + опциональная запись в sc |
| Design-time / Run-time | проектирование UI vs адаптация при эксплуатации |

---

## 17. Ссылки

- Репозиторий редактора UI: https://github.com/vodo4kin/ostis-ui-editor  
- ostis-example-app: https://github.com/ostis-apps/ostis-example-app  
- py-sc-client: https://github.com/ostis-ai/py-sc-client  
- ts-sc-client: https://github.com/ostis-ai/ts-sc-client  
- sc-machine: https://github.com/ostis-ai/sc-machine  

Внутренние материалы проекта: `структура_проекта_UI_ostis.md`, пояснительные записки команды, заявка на грант БРФФИ.

---

*Документ описывает состояние реализации модуля A версии 0.1 (Python). При изменении публичных контрактов версию и разделы 4–10 следует синхронизировать.*
