@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "RPA_PAUSAR=1"
for %%A in (%*) do if /I "%%~A"=="--silencioso" set "RPA_PAUSAR=0"
call "%~dp0_python.bat" --instalar-dependencias
if errorlevel 1 (
    echo [ERRO] Dependencias nao preparadas. Confira Python 3.12+ e a conexao.
    if "%RPA_PAUSAR%"=="1" pause
    exit /b 1
)
set "RPA_ENV=%LOCALAPPDATA%\RPA_SEFAZ\venv"
"%RPA_ENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name "Automacao Notas Sefaz" --collect-all playwright --collect-all pywinauto --hidden-import win32timezone --add-data "acessarDTe.png;." --add-data "xml_item_template.png;." download_sefaz_xml.py
if errorlevel 1 (
    echo [ERRO] Falha ao gerar o executavel.
    if "%RPA_PAUSAR%"=="1" pause
    exit /b 1
)
copy /y "dist\Automacao Notas Sefaz.exe" "Automacao Notas Sefaz.exe" >nul
if errorlevel 1 (
    echo [ERRO] EXE criado em dist, mas nao foi copiado para a pasta do codigo.
    if "%RPA_PAUSAR%"=="1" pause
    exit /b 1
)
echo [OK] Executavel atualizado: "%~dp0Automacao Notas Sefaz.exe"
if "%RPA_PAUSAR%"=="1" pause
exit /b 0
