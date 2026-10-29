@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Agendando no horario de config.json e no login do Windows...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0agendar_tarefa.ps1"
if errorlevel 1 (
    echo [ERRO] Nao foi possivel registrar a tarefa.
    echo Verifique se o Agendador de Tarefas esta habilitado.
    pause
    exit /b 1
)
echo.
pause
