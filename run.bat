@echo off
setlocal

rem Работаем от папки самого файла, чтобы двойной клик в Проводнике
rem всегда попадал куда нужно.
cd /d "%~dp0"

echo ============================================================
echo   Enginet - local launch
echo ============================================================
echo.

rem --- проверка python и node в PATH ---
where python >nul 2>nul
if errorlevel 1 (
    echo [OSHIBKA] Python ne naiden v PATH: https://www.python.org/downloads/
    pause
    exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [OSHIBKA] Node.js/npm ne naiden v PATH: https://nodejs.org/
    pause
    exit /b 1
)

rem --- backend: venv и зависимости, если ещё не установлены ---
if not exist "backend\.venv\Scripts\python.exe" (
    echo [backend] sozdanie virtualnogo okruzheniya...
    python -m venv backend\.venv
    if errorlevel 1 (
        echo [OSHIBKA] ne udalos sozdat virtualnoe okruzhenie.
        pause
        exit /b 1
    )
)

echo [backend] proverka zavisimostey...
backend\.venv\Scripts\python.exe -m pip install -q --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt
if errorlevel 1 (
    echo [OSHIBKA] ne udalos ustanovit zavisimosti backend.
    pause
    exit /b 1
)

rem --- frontend: npm-пакеты, если ещё не установлены ---
if not exist "frontend\node_modules" (
    echo [frontend] ustanovka npm-paketov...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [OSHIBKA] npm install zavershilsya s oshibkoy.
        popd
        pause
        exit /b 1
    )
    popd
)

echo.
echo [backend]  http://localhost:8000
echo [frontend] http://localhost:5173
echo.

start "Enginet - backend (port 8000)" cmd /k "backend\start_backend.bat"
start "Enginet - frontend (port 5173)" cmd /k "frontend\start_frontend.bat"

echo zagruzka frontenda...
timeout /t 6 /nobreak > nul
start "" "http://localhost:5173"

echo.
echo ============================================================
echo   Gotovo - backend i frontend v dvukh oknakh.
echo   Ostanovka: zakryt oba okna (ili Ctrl+C v kazhdom).
echo ============================================================
pause
