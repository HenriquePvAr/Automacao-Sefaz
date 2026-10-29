@echo off
rem Detecta um interpretador REAL, pois o WindowsApps/python.exe pode ser
rem apenas um atalho para a Microsoft Store (where python nao basta).
rem Variaveis RPA_PYEXE e RPA_PYARGS sao retornadas ao BAT chamador.
set "RPA_PYEXE="
set "RPA_PYARGS="

rem Preferir Python 3.12: versao escolhida para homologar as dependencias.
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%ProgramFiles%\Python312\python.exe"
) do (
    if exist "%%~P" (
        "%%~P" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
        if errorlevel 0 if not errorlevel 1 (
            set "RPA_PYEXE=%%~P"
            exit /b 0
        )
    )
)

where py >nul 2>&1
if errorlevel 0 if not errorlevel 1 (
    py -3.12 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
    if errorlevel 0 if not errorlevel 1 (
        set "RPA_PYEXE=py"
        set "RPA_PYARGS=-3.12"
        exit /b 0
    )
)

rem Aceitar outras versoes >= 3.12 ja presentes, sem instalar em duplicidade.
for %%V in (313 314 315 316) do (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        "%ProgramFiles%\Python%%V\python.exe"
    ) do (
        if exist "%%~P" (
            "%%~P" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
            if errorlevel 0 if not errorlevel 1 (
                set "RPA_PYEXE=%%~P"
                exit /b 0
            )
        )
    )
)

where py >nul 2>&1
if errorlevel 0 if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
    if errorlevel 0 if not errorlevel 1 (
        set "RPA_PYEXE=py"
        set "RPA_PYARGS=-3"
        exit /b 0
    )
)

where python >nul 2>&1
if errorlevel 0 if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
    if errorlevel 0 if not errorlevel 1 (
        set "RPA_PYEXE=python"
        exit /b 0
    )
)

exit /b 1
