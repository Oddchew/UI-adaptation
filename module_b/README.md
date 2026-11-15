# Модуль B — принятие решения об адаптации

**Контур:** A → **B** → C · **v0.2** — декларативные правила

## Идея

Автор UI (в перспективе — в ostis-ui-editor) задаёт правила **без кода**:
`триггер → действие`. B только интерпретирует их по пакету от A.

## Подключение

```python
from module_b import ModuleB

b = ModuleB()                          # встроенные DEFAULT_RULES
b = ModuleB(rules="module_b/rules_default.json")
b = ModuleB(rules=[ {...}, ... ])      # как сохранит редактор
b.set_rules(new_rules)                 # горячая подмена
```

API для A/C то же: `handle_package`, `set_command_handler`, `reset_anti_flicker`.

## Формат правила (JSON)

```json
{
  "id": "R_hint_after_2_errors",
  "priority": 1,
  "enabled": true,
  "trigger": { "kind": "error_count", "threshold": 2, "op": "gte" },
  "action": {
    "target_element_id": "hints_panel",
    "property": "visible",
    "old_value": false,
    "new_value": true
  }
}
```

**trigger.kind:** `error_count` | `error_rate` | `help_count` | `success_count` | `event_count`  
**action:** любой element_id + property из модели UI редактора.

## Поля для UI редактора

| Поле | UI |
|------|-----|
| trigger.kind | select |
| threshold | number |
| action.target_element_id | select из дерева UI |
| action.property | select из свойств компонента |
| action.new_value | input / color / bool |
| priority | number |
| enabled | checkbox |

Сохранение: `rules` в JSON модели интерфейса (позже — SC).

## Тесты

```bash
PYTHONPATH=. python3 tests/test_module_b.py
PYTHONPATH=. python3 tests/demo_abc.py
```
