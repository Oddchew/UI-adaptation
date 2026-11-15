# Интеграция: KB + UI + Module A

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
