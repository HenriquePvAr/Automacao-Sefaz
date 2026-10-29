$ErrorActionPreference = 'Stop'
$taskName = 'RPA_SEFAZ_Download_XML'
$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$exe = Join-Path $desktop 'Automacao Notas Sefaz.exe'
$configPath = Join-Path $env:LOCALAPPDATA 'RPA_SEFAZ\config.json'
$usuario = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

foreach ($required in @($exe, $configPath)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Arquivo necessario nao encontrado: $required" }
}

$settingsJson = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$horario = [DateTime]::ParseExact([string]$settingsJson.hora_diaria, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
$acao = New-ScheduledTaskAction -Execute $exe -Argument '--background-download --agendado' -WorkingDirectory $desktop
$gatilhoDiario = New-ScheduledTaskTrigger -Daily -At $horario
$gatilhoLogin = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 7) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited

# O Edge headless e o lançador VBScript rodam sem janelas visíveis. O gatilho
# de login recupera um horário perdido; o código aguarda a internet voltar.
Register-ScheduledTask -TaskName $taskName -Action $acao -Trigger @($gatilhoDiario, $gatilhoLogin) -Settings $config -Principal $principal -Force | Out-Null

$folder = Join-Path $desktop 'Notas sefaz'
New-Item -ItemType Directory -Path $folder -Force | Out-Null

Write-Host "[OK] Agendado diariamente as $($settingsJson.hora_diaria) e no login de $usuario"
Write-Host '[OK] Atraso por PC desligado e espera pela internet habilitados.'
Write-Host "[OK] Executavel manual: $exe"
