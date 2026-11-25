Контур: **ModuleA → ModuleB (реальный) → MockModuleC**.

Правила: env `ADAPTATION_RULES` или `module_b/rules_default.json`.

# Интеграция: KB + UI + Module A

Актуальная цепочка демо: браузер → A → B → C → браузер. C хранит версии в SQLite; браузер подтверждает применение. Запуск: `python integration/server.py`. Описание модуля C и его контрактов находится в [module_c/README.md](../module_c/README.md).

## Схема

```
Браузер (integration/static)
    POST /api/event
         │
         ▼
  integration/server.py  →  Module A  →  Mock B  →  Mock C
         │                     │
         │                     └── HybridStorage → sc-server :8090
         ▼
  JSON: model + ui-state (help_panel, fontSize)
```

sc-web (example-app :8000) — просмотр KB; этот UI — **целевой адаптивный интерфейс** модуля A.

## 1. Онтология в KB

```bash
cd ~/Sundries/ostis/module_A_adaptation_py
bash integration/install_kb.sh

cd ~/Sundries/ostis/ostis-example-app
./scripts/start.sh build_kb
./scripts/start.sh machine    # если не запущен (порт 8090)
```

## 2. Сервер A + UI

```bash
cd ~/Sundries/ostis/module_A_adaptation_py
# с sc (по умолчанию):
python3 integration/server.py

# только память:
MODULE_A_USE_SC=0 python3 integration/server.py
```

Откройте: **http://127.0.0.1:8765/**

## 3. Что нажимать в UI

1. Несколько раз **«Смоделировать ошибку»** — растёт error_rate, уйдёт пакет `threshold`, появится **help_panel**.
2. **«Нужна помощь»** — help_request (при накоплении — увеличение шрифта).
3. **Сохранить** с пустым/битым email — error; с нормальным — successful_action.
4. Смена **темы** — `manual_override`.
5. Справа — модель A, UI-state C, пакеты A→B.

## API

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/api/health` | статус A и sc |
| POST | `/api/event` | InteractionEvent |
| GET | `/api/model/{user_id}` | снимок модели |
| GET | `/api/ui-state` | состояние после C |

## sc-web

```bash
cd ~/Sundries/ostis/ostis-example-app
./scripts/start.sh web   # обычно http://localhost:8000
```

Там можно смотреть KB; события адаптации идут через UI на :8765, не через sc-web.


## Универсальный SC UI runtime

При `MODULE_C_USE_SC=1` сервер не регистрирует демонстрационную модель `python_tutor_model`.
Интерфейс загружается лениво из SC по его `interface_id` при первом запросе:

```bash
MODULE_C_USE_SC=1 \
MODULE_C_ALLOW_SHARED_SESSION_MODEL=1 \
PYTHONPATH=. python3 integration/server.py
```

Откройте интерфейс, передав его идентификатор из `nrel_ui_id`:

```
http://127.0.0.1:8765/?interface_id=<interface_id>
```

API состояния также требует этот идентификатор:
`GET /api/ui-state?interface_id=<interface_id>`.
Ответ содержит полный снимок `model` (components, props, links), а не только demo-представление.
События `POST /api/event` в SC-режиме должны содержать тот же `interface_id`.

В SC-режиме демонстрационные правила Python Lab автоматически не загружаются.
Для адаптации задайте `ADAPTATION_RULES` с правилами, предназначенными для соответствующего набора интерфейсов.
Если правила не заданы, Module B безопасно не формирует автоматические команды.


### Поддержка компонентов в браузерном runtime

Runtime строит DOM по `components` и связям `contains`, без привязки к Python Lab:
- `text`, `divider`, `spacer`, `window`, `scroll`, `menu`, `menu_bar`, `list`;
- `button`, `menu_item`, `text_field`, `text_area`, `slider`, `select`;
- `image` и `sound`.

Для `image`/`sound` поле `text_value` трактуется как URL или относительный путь, если оно начинается с `http://`, `https://`, `/`, `./` или `../`. Если в нём находится SC ID ресурса, runtime показывает нейтральную заглушку с этим ID: разрешение SC ID в файл требует отдельного resource resolver и здесь не имитируется.

Для `select` варианты могут быть дочерними `menu_item` или `text` через `contains`. При выборе отправляется `successful_action` с `action_id`; выбранное значение и значения связанных через `input_target` полей передаются в `new_value` события.

Связи `input_target` читаются от action-компонента к полям ввода. При нажатии на `button`/`menu_item` текущие значения связанных полей передаются в событии как `property: "input_values"` и `new_value: {component_id: value}`. Связи `output_target` сохраняются в DOM как `data-output-targets`; выполнение прикладного действия и запись его результата в целевые компоненты пока остаются ответственностью отдельного action handler.

### События интерактивных SC-компонентов

Универсальный renderer отправляет события без изменения SC-модели содержимого:

- `focus` / `blur` — фокус и потеря фокуса текстовым полем, областью, ползунком или списком выбора.
- `successful_action` с `property: "input_value"` — изменение значения поля, области, ползунка или списка выбора; `new_value` содержит новое значение.
- `successful_action` с `property: "action_context"` — нажатие кнопки/пункта меню, связанного с `input_target` и/или `output_target`.

Для действия с входными/выходными связями `new_value` имеет структуру:

```json
{
  "input_values": {"component_id": "current value"},
  "output_target_ids": ["component_id"]
}
```

Для изменения связанного элемента `new_value` содержит его `value`, текущие `input_values` и `output_target_ids`.
Эти данные фиксируют контекст взаимодействия для Module A; сами по себе они не меняют `text_value`, `action_id` или другие свойства SC-модели.