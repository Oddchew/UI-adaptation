# SC-интеграция, design-time и оценка эффекта

Документ описывает доработки run-time контура (после ревью 2026-11-23).

## 1. SC-интеграция с гарантиями

### Проблема
Запись свойства UI в SC — это «прочитать link → сравнить → `set_link_contents`».
Между клиентами операция **не атомарна**. Несколько процессов могут затереть чужое изменение.

### Решение в коде
| Компонент | Файл | Роль |
|-----------|------|------|
| `ScUiModelAdapter(exclusive_writer=True)` | `module_c/sc_model.py` | Запрещает запись без флага exclusive |
| `ExclusiveScWriter` | `module_c/sc_writer.py` | Единый writer в процессе: `asyncio.Lock`, optimistic version token, journal |
| `NullScWriter` | тот же | Заглушка для in-memory демо |

Правила использования:
1. В процессе запускается **один** `ExclusiveScWriter` на один `ScUiModelAdapter`.
2. Все `CommandBtoC`, меняющие SC, проходят через `writer.apply(...)`.
3. При `old_value_mismatch` команда отклоняется (C → `rejected`).
4. Журнал writer хранит последние 500 записей для аудита.

Полная распределённая транзакционность (несколько sc-client) требует внешнего lock-сервиса или single-writer сервиса; текущая гарантия — **внутри одного процесса Module C**.

### Runtime
`ScModelRuntime` требует `exclusive_writer=True` и опциональный `scope_resolver` для session-specific SC-моделей.

## 2. Связь с design-time (каталог)

Источник истины: [ostis-ui-editor/docs/catalog.md](https://github.com/vodo4kin/ostis-ui-editor/blob/main/docs/catalog.md).

| Артефакт | Назначение |
|----------|------------|
| `module_c/catalog.py` | `COMPONENT_TYPES`, `PROPERTY_TYPES`, `ADAPTABLE_PROPERTIES`, SC-имена |
| `module_c/model.py` | Импортирует каталог; `AdaptationPolicy.from_catalog(ids)` |
| `sc/adaptation_effect_and_catalog.scs` | Онтологические маркеры adaptable / forbidden свойств |

Идентификаторы `typeId` и ключи свойств в run-time **совпадают** с редактором.
Политика адаптации по умолчанию разрешает только `ADAPTABLE_PROPERTIES`;
`text_value`, `action_id`, геометрию — нельзя.

## 3. Оценка эффекта и более богатая модель

### EffectTracker (`module_a/effect_tracker.py`)
1. При `AdaptationResult.success` регистрируется baseline (error_rate, help_rate, successes).
2. После окна follow-up (по умолчанию 5 мин, ≥3 события) считается score:
   - снижение error/help rate → плюс;
   - рост successful_action → плюс.
3. Агрегаты по `rule_id` → `rule_scores` в `UserModel`.

### Расширение UserModel
- `struggle_index` (0..1) — recent error/help;
- `engagement_index` (0..1) — доля успешных действий;
- `rule_scores` — dict rule_id → mean score;
- `effect_summary` — снимок для отладки/пакета A→B.

### Module B
`evaluate_declarative_rules` учитывает `model_snapshot.rule_scores`:
- сильно отрицательный mean → правило пропускается;
- положительный → приоритет улучшается (меньший effective priority).

## 4. Установка SC-схем

```bash
# в ostis-example-app knowledge-base
cp sc/user_model_and_events.scs sc/module_c_adaptation.scs sc/adaptation_effect_and_catalog.scs \
   "$OSTIS_EXAMPLE_APP/knowledge-base/module_a/"
./scripts/start.sh build_kb
./scripts/start.sh machine
```

## 5. Ограничения (честно)
- SC writer гарантирует порядок только в одном процессе.
- Оценка эффекта — эвристика; для гранта нужны статистические критерии и A/B.
- Каталог синхронизируется **вручную** с `catalog.md`; автоматический diff с редактором — следующий шаг.
