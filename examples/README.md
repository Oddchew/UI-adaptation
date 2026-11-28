# Проверка полного цикла SC UI action

Этот пример проверяет не только отрисовку, но и передачу контекста действия через
Module A → Module B → Module C с подтверждением применения в браузере.

## 1. Создайте интерфейс в ostis-ui-editor

Создайте **новый** интерфейс с ID `ui_action_test`. Не изменяйте `ex_calendar`.

Добавьте четыре компонента:

| ID | Тип | Основные свойства |
|---|---|---|
| `main_window` | window | name: Action test |
| `show_button` | button | text_value: Показать результат; action_id: `show_status_panel` |
| `message_input` | text_field | name: Сообщение; text_value: Введите текст |
| `status_panel` | window | name: Результат; visible: `false` |

Установите вложенность через `nrel_ui_contains`:

- `main_window` → `show_button`
- `main_window` → `message_input`
- `main_window` → `status_panel`

Добавьте связи от кнопки:

- `show_button` → `message_input` через `nrel_ui_input_target`;
- `show_button` → `status_panel` через `nrel_ui_output_target`.

Важно: `action_id` задаётся именно у кнопки; у панели изначально должно быть
`visible=false`. Все четыре компонента должны входить в `nrel_ui_has_component`
интерфейса. Сохраните интерфейс в SC-память.

## 2. Запустите runtime с правилом

Из корня репозитория:

```bash
ADAPTATION_RULES="$PWD/examples/ui_action_test.rules.json" \
MODULE_A_USE_SC=1 \
MODULE_C_USE_SC=1 \
PYTHONPATH=. python3 integration/server.py
```

Не включайте `MODULE_C_ALLOW_SHARED_SESSION_MODEL=1`: для этого сценария используется
интерфейсная SC-модель без отдельной модели на сессию. Параметр `sessionless=1`
отключает генерацию `session_id` только для открытой вкладки; остальные интерфейсы
сохраняют обычную маршрутизацию по сессиям.

Откройте:

```
http://127.0.0.1:8765/?interface_id=ui_action_test&sessionless=1
```

Изменение `visible` записывается в общую модель интерфейса `ui_action_test`, а не
в персональную модель пользователя или вкладки. Для проверки используйте отдельный
тестовый интерфейс, не рабочий `ex_calendar`.

## 3. Проверьте сценарий

1. Убедитесь, что панель результата изначально скрыта.
2. Введите произвольный текст в поле.
3. Нажмите «Показать результат».
4. Панель должна стать видимой после подтверждения обновления браузером.

Правило в `ui_action_test.rules.json` срабатывает только для `action_id=show_status_panel`
и разрешает цель через единственную связь `nrel_ui_output_target`. Module B получает
значения `nrel_ui_input_target` в контексте события. Module C проверяет компонент,
свойство, whitelist и старое значение `false`, затем обновляет SC-свойство `visible`.
Браузер подтверждает применение команды через runtime acknowledgement.

## 4. Диагностика

Проверьте API:

```bash
curl -s "http://127.0.0.1:8765/api/ui-state?interface_id=ui_action_test" | python3 -m json.tool
```

В `model.links` должны присутствовать связи `contains`, `input_target` и
`output_target`. У `show_button` должно быть `action_id=show_status_panel`,
а у `status_panel` — `visible=false` до нажатия.

Если кнопка нажимается, но панель не появляется, проверьте вывод сервера: там должны
быть видны пакет Module A → Module B и результат применения Module C. Не повторяйте
нажатие до проверки значения `visible`: повторное применение правила ожидает
`old_value=false`.
