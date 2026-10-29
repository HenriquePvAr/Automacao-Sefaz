@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================
echo  CONSULTA MANUAL - SEFAZ-AM
echo  Baixa somente XML recebidos e guarda o ZIP localmente.
echo  Nao acessa nem envia arquivos ao Sankhya.
echo ================================================================
echo.
call "%~dp0_python.bat" --baixar-apenas
set "RPA_RC=%errorlevel%"
echo.
if not "%RPA_RC%"=="0" echo [AVISO] Teste encerrado com codigo %RPA_RC%.
pause
exit /b %RPA_RC%
