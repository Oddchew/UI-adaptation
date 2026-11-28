#!/usr/bin/env bash
# Install the adaptive calculator extension into the local ostis-example-app KB.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXAMPLE_APP="${OSTIS_EXAMPLE_APP:-$HOME/Sundries/ostis/ostis-example-app}"
SOURCE="$MODULE_ROOT/examples/ex_calculator_adaptive.scs"
DEST_DIR="$EXAMPLE_APP/knowledge-base/module_a"
REPO_PATH="$EXAMPLE_APP/repo.path"

if [[ ! -d "$EXAMPLE_APP" ]]; then
  echo "Не найден ostis-example-app: $EXAMPLE_APP" >&2
  echo "Задайте OSTIS_EXAMPLE_APP=/path/to/ostis-example-app" >&2
  exit 1
fi
if [[ ! -f "$REPO_PATH" ]]; then
  echo "Не найден $REPO_PATH" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
install -m 0644 "$SOURCE" "$DEST_DIR/ex_calculator_adaptive.scs"
if ! grep -Eq '(^|/)knowledge-base/?$|module_a' "$REPO_PATH"; then
  printf '\nknowledge-base\n' >> "$REPO_PATH"
fi

echo "Установлено: $DEST_DIR/ex_calculator_adaptive.scs"
echo "Пересобираю knowledge base..."
(cd "$EXAMPLE_APP" && ./scripts/start.sh build_kb)
echo "Готово. Перезапустите SC machine, если она была запущена до пересборки."
