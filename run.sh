#!/usr/bin/env bash
# Запуск backend + frontend: ./run.sh (Ctrl+C — остановка обоих процессов)
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "============================================================"
echo "  Enginet — локальный запуск"
echo "============================================================"
echo

command -v python3 >/dev/null 2>&1 || {
    echo "[ОШИБКА] python3 не найден: https://www.python.org/downloads/"
    exit 1
}
command -v npm >/dev/null 2>&1 || {
    echo "[ОШИБКА] npm не найден: https://nodejs.org/"
    exit 1
}

if [ ! -f "backend/.venv/bin/python" ]; then
    echo "[backend] создание виртуального окружения..."
    python3 -m venv backend/.venv
fi

echo "[backend] проверка зависимостей..."
backend/.venv/bin/python -m pip install -q --upgrade pip
backend/.venv/bin/python -m pip install -q -r backend/requirements.txt

if [ ! -d "frontend/node_modules" ]; then
    echo "[frontend] установка npm-пакетов..."
    (cd frontend && npm install)
fi

# Подхватываем ключи Yandex из backend/.env, если он есть
if [ -f "backend/.env" ]; then
    echo "загрузка backend/.env..."
    set -a
    # shellcheck disable=SC1091
    source backend/.env
    set +a
fi

echo
echo "[backend]  http://localhost:8000"
echo "[frontend] http://localhost:5173"
echo

cleanup() {
    echo
    echo "остановка backend и frontend..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!

(cd frontend && npm run dev) &
FRONTEND_PID=$!

sleep 4
if command -v open >/dev/null 2>&1; then
    open "http://localhost:5173"        # macOS
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:5173"    # Linux
fi

echo "Готово. Ctrl+C — остановка."
wait
