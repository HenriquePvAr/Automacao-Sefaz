@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_detectar_python.bat"
if errorlevel 1 (
    echo [ERRO] Python 3.12 ou superior nao encontrado para compilar os fontes.
    echo [DICA] Instale Python 3.12+ e habilite o Python Launcher, ou use o pacote de implantacao com EXE.
    exit /b 1
)
rem Isola as dependencias do RPA para nao alterar o Python de outros projetos.
set "RPA_BASE_PYEXE=%RPA_PYEXE%"
set "RPA_BASE_PYARGS=%RPA_PYARGS%"
set "RPA_ENV=%LOCALAPPDATA%\RPA_SEFAZ\venv"
if exist "%RPA_ENV%\Scripts\python.exe" goto venv_ok
echo [PYTHON] Criando ambiente isolado em "%RPA_ENV%"...
"%RPA_BASE_PYEXE%" %RPA_BASE_PYARGS% -m venv "%RPA_ENV%"
if errorlevel 1 goto sem_dependencias
:venv_ok
set "RPA_PYEXE=%RPA_ENV%\Scripts\python.exe"
set "RPA_PYARGS="
for %%A in (%*) do if /I "%%~A"=="--instalar-dependencias" goto instalar_dependencias
rem Verifica as dependencias no mesmo Python que executara o robo.
"%RPA_PYEXE%" %RPA_PYARGS% -c "import importlib.util,sys; mods=('PIL','pyautogui','pywinauto','psutil','win32gui','playwright'); missing=[m for m in mods if importlib.util.find_spec(m) is None]; print('[DEPENDENCIAS] Ausentes: '+', '.join(missing)) if missing else None; sys.exit(bool(missing))"
if not errorlevel 1 goto executar
rem Nunca instalar pacotes automaticamente em execucao agendada.
set "RPA_INSTALL_AUTO=1"
for %%A in (%*) do if /I "%%~A"=="--agendado" set "RPA_INSTALL_AUTO=0"
if "%RPA_INSTALL_AUTO%"=="0" goto sem_dependencias
echo [DEPENDENCIAS] Instalando no ambiente isolado do RPA...
"%RPA_PYEXE%" %RPA_PYARGS% -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto sem_dependencias
"%RPA_PYEXE%" %RPA_PYARGS% -c "import importlib.util,sys; mods=('PIL','pyautogui','pywinauto','psutil','win32gui','playwright'); sys.exit(0 if all(importlib.util.find_spec(m) is not None for m in mods) else 1)"
if errorlevel 1 goto sem_dependencias
:executar
"%RPA_PYEXE%" %RPA_PYARGS% "%~dp0download_sefaz_xml.py" %*
exit /b %errorlevel%

:instalar_dependencias
"%RPA_PYEXE%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto sem_dependencias
"%RPA_PYEXE%" -c "import importlib.util,sys; mods=('PIL','pyautogui','pywinauto','psutil','win32gui','playwright'); sys.exit(0 if all(importlib.util.find_spec(m) is not None for m in mods) else 1)"
if errorlevel 1 goto sem_dependencias
echo [OK] Dependencias instaladas no ambiente isolado.
exit /b 0

:sem_dependencias
echo [ERRO] Nao foi possivel instalar/verificar as dependencias no Python do robo.
echo [DICA] Execute instalar.bat e confira eventuais mensagens do pip.
exit /b 3
