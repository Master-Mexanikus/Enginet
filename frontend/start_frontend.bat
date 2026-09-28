@echo off
cd /d "%~dp0"

if not exist "node_modules" (
    echo [OSHIBKA] npm-pakety ne ustanovleny.
    echo Zapustite run.bat iz kornya proekta - on postavit ikh avtomaticheski.
    pause
    exit /b 1
)

if not exist "node_modules\vite\bin\vite.js" (
    echo [OSHIBKA] Ne naiden node_modules\vite\bin\vite.js.
    echo Vozmozhno npm install proshel s oshibkoy. Poprobuyte udalit
    echo papku node_modules i zapustit run.bat zanovo.
    pause
    exit /b 1
)

rem zapusk node napryamuyu na vite.js, v obhod node_modules\.bin\vite.cmd -
rem ego otnositelny put lomaetsya pri start/cmd /k.
node "node_modules\vite\bin\vite.js"
