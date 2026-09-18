#!/bin/bash

# Скрипт для запуска MCP Inspector с подключением к Svacer MCP серверу
# Использование: ./run_inspector.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# Проверка наличия виртуального окружения
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Ошибка: виртуальное окружение не найдено в $SCRIPT_DIR/.venv"
    echo "Создайте его командой: python3 -m venv .venv && .venv/bin/pip install -e ."
    exit 1
fi

# Проверка наличия npx
if ! command -v npx &> /dev/null; then
    echo "Ошибка: npx не найден. Установите Node.js: https://nodejs.org"
    exit 1
fi

echo "Запуск MCP Inspector..."
echo "Python: $VENV_PYTHON"
echo "Сервер: svacer_mcp.server"
echo ""
echo "Inspector откроется в браузере автоматически."
echo "Для остановки нажмите Ctrl+C"
echo ""

# Запуск Inspector с STDIO сервером
cd "$SCRIPT_DIR"
npx @modelcontextprotocol/inspector "$VENV_PYTHON" -m svacer_mcp.server
