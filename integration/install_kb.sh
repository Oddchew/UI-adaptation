#!/usr/bin/env bash
# Установка онтологии модуля A в knowledge-base ostis-example-app
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SCS_SRC="$MODULE_ROOT/sc/user_model_and_events.scs"

# Пути по умолчанию (Fedora / Sundries)
EXAMPLE_APP="${OSTIS_EXAMPLE_APP:-$HOME/Sundries/ostis/ostis-example-app}"

if [[ ! -d "$EXAMPLE_APP" ]]; then
  echo "Не найден ostis-example-app: $EXAMPLE_APP"
  echo "Задайте: export OSTIS_EXAMPLE_APP=/path/to/ostis-example-app"
  exit 1
fi

if [[ ! -f "$SCS_SRC" ]]; then
  echo "Нет файла $SCS_SRC"
  exit 1
fi

DEST="$EXAMPLE_APP/knowledge-base/module_a"
mkdir -p "$DEST"
cp -f "$SCS_SRC" "$DEST/user_model_and_events.scs"
echo "✓ скопировано → $DEST/user_model_and_events.scs"

# repo.path: добавить, если нет
REPO="$EXAMPLE_APP/repo.path"
if [[ -f "$REPO" ]]; then
  if ! grep -q "module_a\|knowledge-base" "$REPO" 2>/dev/null; then
    echo "knowledge-base" >> "$REPO"
    echo "✓ в repo.path добавлен knowledge-base"
  else
    echo "· repo.path уже содержит knowledge-base / module_a"
  fi
  echo "--- repo.path ---"
  cat "$REPO"
fi

echo ""
echo "Дальше:"
echo "  cd $EXAMPLE_APP"
echo "  ./scripts/start.sh build_kb"
echo "  ./scripts/start.sh machine   # если ещё не запущен"
