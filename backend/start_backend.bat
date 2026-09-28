@echo off
cd /d "%~dp0"

rem .env (skopirovanny iz .env.example, s klyuchami Yandex) - stroki
rem vida KEY=VALUE, stroki s # v nachale ignoriruyutsya.
if exist ".env" (
    echo zagruzka peremennykh iz .env...
    for /f "usebackq tokens=1,2 delims==" %%A in (`findstr /v "^#" .env`) do (
        if not "%%A"=="" set "%%A=%%B"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [OSHIBKA] Virtualnoe okruzhenie backend ne naideno.
    echo Zapustite run.bat iz kornya proekta - on sozdast ego avtomaticheski.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
