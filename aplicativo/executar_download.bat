@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ====================================================================
echo  DOWNLOAD DE TESTE SEFAZ-AM - Edge normal
echo  Requer certificado. Baixa ontem/hoje e preserva ZIP no Desktop.
echo  NAO envia nada ao Sankhya.
echo ====================================================================
echo.
call "%~dp0_python.bat" --baixar-apenas
set "RPA_RC=%errorlevel%"
if not "%RPA_RC%"=="0" echo [AVISO] Execucao interrompida com codigo %RPA_RC%. Veja logs.
pause
exit /b %RPA_RC%
