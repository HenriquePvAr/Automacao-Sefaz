@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ===================================================================
echo  INSTALACAO - AUTOMACAO NOTAS SEFAZ-AM
echo ===================================================================
echo.

if not exist "%~dp0Automacao Notas Sefaz.exe" (
    echo [BUILD] Executavel ausente. Preparando dependencias e compilando...
    call "%~dp0gerar_executavel.bat" --silencioso
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel gerar o executavel.
        echo Para compilar fontes, instale Python 3.12 ou superior e tente novamente.
        pause
        exit /b 1
    )
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0preparar_configuracao.ps1" -TemplatePath "%~dp0config.json" -UserConfigPath "%~dp0config.usuario.json"
if errorlevel 1 (
    echo [ERRO] Nao foi possivel preparar a configuracao local.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_certificado.ps1" -SelectorPath "%~dp0certificado_usuario.json" -PfxPath "%~dp0certificado_usuario.pfx"
if errorlevel 1 (
    echo [ERRO] Nao foi possivel garantir o certificado nesta conta do Windows.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $source=(Get-Location).Path; $desktop=[Environment]::GetFolderPath('DesktopDirectory'); New-Item -ItemType Directory -Force -Path (Join-Path $desktop 'Notas sefaz') | Out-Null; Copy-Item -LiteralPath (Join-Path $source 'Automacao Notas Sefaz.exe') -Destination (Join-Path $desktop 'Automacao Notas Sefaz.exe') -Force"
if errorlevel 1 (
    echo [ERRO] Nao foi possivel copiar o executavel e a configuracao.
    pause
    exit /b 1
)

echo [OK] Executavel criado na Area de Trabalho.
echo [OK] Pasta de saida criada: Area de Trabalho\Notas sefaz
echo.
echo Registrando rotina diaria e recuperacao no login...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0agendar_tarefa.ps1"
if errorlevel 1 (
    echo [ERRO] Falha ao registrar a tarefa diaria.
    pause
    exit /b 1
)

echo.
echo Configurando a selecao automatica do certificado SEFAZ...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configurar_certificado_edge.ps1"
if errorlevel 1 (
    echo [AVISO] Nao foi possivel configurar o certificado automaticamente.
    echo [INFO] Instale o certificado na conta desta usuaria e execute instalar.bat novamente.
) else (
    echo [OK] Selecao automatica do certificado configurada para os dois dominios.
)

echo.
echo [OK] Instalacao concluida.
echo [INFO] Dois cliques em "Automacao Notas Sefaz.exe" iniciam uma consulta manual.
echo [INFO] A tarefa automatica roda as 07:30, no login se o horario foi perdido,
echo        e aguarda a internet voltar. A usuaria deve estar conectada ao Windows.
echo [INFO] Se o certificado ja estava instalado nesta conta, sua selecao automatica
echo        foi configurada. Feche e reabra o Edge uma vez.
echo [INFO] Se o certificado estava ausente, o instalador solicitou a senha do PFX
echo        e o instalou somente nesta conta. A senha nao foi salva no pacote.
pause
exit /b 0
