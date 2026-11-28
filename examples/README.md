# Проверка полного цикла SC UI action

Этот пример проверяет полный цикл Module A → Module B → Module C: событие кнопки,
передачу контекста input/output target, изменение SC-модели и подтверждение браузером.

## 1. Автоматически установите тестовый интерфейс

Интерфейс уже описан в `examples/ui_action_test.scs`. Создавать его вручную
в ostis-ui-editor не требуется. Из корня репозитория выполните:

```bash
bash examples/install_ui_action_fixture.sh
```

Скрипт копирует fixture в `$HOME/Sundries/ostis/ostis-example-app/knowledge-base/module_a`,
добавляет `knowledge-base` в `repo.path`, если это необходимо, и запускает
`./scripts/start.sh build_kb`. Если ostis-example-app расположен в другом месте,
задайте `OSTIS_EXAMPLE_APP=/путь/к/ostis-example-app`.

Fixture создаёт отдельный интерфейс `ui_action_test` с четырьмя компонентами:
`main_window`, `show_button`, `message_input` и `status_panel`. Кнопка имеет
`action_id=show_status_panel`, панель изначально `visible=false`; связи
`nrel_ui_contains`, `nrel_ui_input_target`, `nrel_ui_output_target` и
`nrel_ui_has_component` уже описаны. Рабочий `ex_calendar` не изменяется.

Если SC machine уже работала во время пересборки KB, перезапустите её, чтобы она
загрузила обновлённую базу знаний.

## 2. Запустите runtime с правилом

Из корня репозитория:

```bash
ADAPTATION_RULES="$PWD/examples/ui_action_test.rules.json" \
MODULE_A_USE_SC=1 \
MODULE_C_USE_SC=1 \
PYTHONPATH=. python3 integration/server.py
```

Не включайте `MODULE_C_ALLOW_SHARED_SESSION_MODEL=1`: используется интерфейсная
SC-модель без отдельной модели на сессию. Параметр `sessionless=1` отключает
генерацию `session_id` только для открытой вкладки; остальные интерфейсы сохраняют
обычную маршрутизацию по сессиям.

Откройте:

```
http://127.0.0.1:8765/?interface_id=ui_action_test&sessionless=1
```

Изменение `visible` записывается в общую модель интерфейса `ui_action_test`, а не
в персональную модель пользователя или вкладки.

## 3. Проверьте сценарий

1. Убедитесь, что панель результата изначально скрыта.
2. Введите произвольный текст в поле.
3. Нажмите «Показать результат».
4. Панель должна стать видимой после подтверждения обновления браузером.

Правило срабатывает только для `action_id=show_status_panel` и разрешает цель через
единственную связь `nrel_ui_output_target`. Module B получает значения
`nrel_ui_input_target` в контексте события. Module C проверяет компонент, свойство,
whitelist и старое значение `false`, затем обновляет SC-свойство `visible`.
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
