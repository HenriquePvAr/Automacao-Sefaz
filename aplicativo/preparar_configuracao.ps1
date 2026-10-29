param(
    [Parameter(Mandatory = $true)]
    [string]$TemplatePath,
    [string]$UserConfigPath
)

$ErrorActionPreference = 'Stop'
$app = Join-Path $env:LOCALAPPDATA 'RPA_SEFAZ'
$configPath = Join-Path $app 'config.json'
New-Item -ItemType Directory -Path $app -Force | Out-Null
if (-not (Test-Path -LiteralPath $configPath)) {
    $seed = if ($UserConfigPath -and (Test-Path -LiteralPath $UserConfigPath)) { $UserConfigPath } else { $TemplatePath }
    Copy-Item -LiteralPath $seed -Destination $configPath
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if ($config.PSObject.Properties.Name -contains 'empresa_cnpj') {
    $config.PSObject.Properties.Remove('empresa_cnpj')
}
$config.sankhya_url = 'https://sankhya.example.invalid'

$ie = [string]$config.empresa_inscricao_estadual
while ($ie -notmatch '^\d{2}\.\d{3}\.\d{3}-\d$') {
    $ie = (Read-Host 'Inscricao estadual da matriz (formato 00.000.000-0)').Trim()
    if ([string]::IsNullOrWhiteSpace($ie)) {
        throw 'Inscricao estadual obrigatoria; nenhuma consulta sera iniciada.'
    }
}
$config.empresa_inscricao_estadual = $ie
$json = $config | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($configPath, $json, [System.Text.UTF8Encoding]::new($false))
Write-Host '[OK] Configuracao local salva para esta conta do Windows.'
