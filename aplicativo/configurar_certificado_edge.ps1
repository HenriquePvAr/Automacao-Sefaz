$ErrorActionPreference = 'Stop'
$patterns = @('https://online.sefaz.am.gov.br', 'https://sistemas.sefaz.am.gov.br')
$store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
    [System.Security.Cryptography.X509Certificates.StoreName]::My,
    [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
)
$store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
try {
    $certs = @($store.Certificates | Where-Object {
        $_.HasPrivateKey -and $_.NotBefore -le (Get-Date) -and $_.NotAfter -ge (Get-Date)
    })
} finally {
    $store.Close()
}
if ($certs.Count -eq 0) {
    throw 'Nenhum certificado valido com chave privada encontrado no usuario atual. Instale o certificado e tente novamente.'
}

$path = 'HKCU:\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls'
$existing = @{}
$numbers = @()
$wantedSubject = $null
$wantedIssuer = $null
$wantedThumbprint = $null
$userSelectorPath = Join-Path $PSScriptRoot 'certificado_usuario.json'
if (Test-Path -LiteralPath $userSelectorPath) {
    $selector = Get-Content -LiteralPath $userSelectorPath -Raw | ConvertFrom-Json
    $wantedThumbprint = ([string]$selector.thumbprint -replace '\s', '').ToUpperInvariant()
    if ([string]::IsNullOrWhiteSpace($wantedThumbprint)) {
        throw 'O seletor de certificado deste pacote esta incompleto.'
    }
    $selected = @($certs | Where-Object { $_.Thumbprint -eq $wantedThumbprint })
    if ($selected.Count -ne 1) {
        throw 'O certificado preparado para este pacote nao esta instalado neste usuario.'
    }
    $nameType = [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName
    $wantedSubject = $selected[0].GetNameInfo($nameType, $false)
    $wantedIssuer = $selected[0].GetNameInfo($nameType, $true)
}
if (Test-Path -LiteralPath $path) {
    $properties = Get-ItemProperty -LiteralPath $path
    $numbers = @($properties.PSObject.Properties.Name | Where-Object { $_ -match '^\d+$' })
    foreach ($number in $numbers) {
        try {
            $entry = $properties.$number | ConvertFrom-Json -ErrorAction Stop
        } catch {
            throw "Entrada de politica $number nao e JSON valido; nenhuma entrada foi substituida."
        }
        if ($entry.pattern -notin $patterns) { continue }
        $entrySubject = [string]$entry.filter.SUBJECT.CN
        $entryIssuer = [string]$entry.filter.ISSUER.CN
        if ([string]::IsNullOrWhiteSpace($entrySubject) -or [string]::IsNullOrWhiteSpace($entryIssuer)) {
            throw "Politica existente para $($entry.pattern) nao identifica titular e emissor; revise antes de alterar."
        }
        if (($wantedSubject -and $wantedSubject -ne $entrySubject) -or
            ($wantedIssuer -and $wantedIssuer -ne $entryIssuer)) {
            throw 'As politicas SEFAZ existentes apontam para certificados diferentes; revise antes de alterar.'
        }
        $wantedSubject = $entrySubject
        $wantedIssuer = $entryIssuer
        $existing[$entry.pattern] = $true
    }
}

$nameType = [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName
if (-not $selected -or $selected.Count -eq 0) {
    if ($wantedSubject -and $wantedIssuer) {
        $selected = @($certs | Where-Object {
            $_.GetNameInfo($nameType, $false) -eq $wantedSubject -and
            $_.GetNameInfo($nameType, $true) -eq $wantedIssuer
        })
        if ($selected.Count -ne 1) {
            throw 'O certificado definido nas politicas existentes nao esta disponivel de forma unica neste usuario.'
        }
    } elseif ($certs.Count -eq 1) {
        $selected = $certs
    } else {
        Write-Host 'Selecione o certificado da empresa que ja esta instalado no Windows:'
        for ($i = 0; $i -lt $certs.Count; $i++) {
            $cert = $certs[$i]
            $subjectName = $cert.GetNameInfo($nameType, $false)
            $issuerName = $cert.GetNameInfo($nameType, $true)
            Write-Host ('[{0}] {1} | Emissor: {2} | Valido ate: {3:dd/MM/yyyy}' -f ($i + 1), $subjectName, $issuerName, $cert.NotAfter)
        }
        $choice = Read-Host 'Numero do certificado'
        $index = 0
        if (-not [int]::TryParse($choice, [ref]$index) -or $index -lt 1 -or $index -gt $certs.Count) {
            throw 'Selecao de certificado invalida; nenhuma politica foi alterada.'
        }
        $selected = @($certs[$index - 1])
    }
}

$cert = $selected[0]
$subject = $cert.GetNameInfo($nameType, $false)
$issuer = $cert.GetNameInfo($nameType, $true)
if ([string]::IsNullOrWhiteSpace($subject) -or [string]::IsNullOrWhiteSpace($issuer)) {
    throw 'Certificado sem nome de titular ou emissor para selecionar com seguranca.'
}

if (-not (Test-Path -LiteralPath $path)) {
    New-Item -Path $path -Force | Out-Null
}
foreach ($pattern in $patterns) {
    if ($existing.ContainsKey($pattern)) { continue }
    $next = 1
    while ($next.ToString() -in $numbers) { $next++ }
    $value = @{
        pattern = $pattern
        filter = @{
            ISSUER = @{ CN = $issuer }
            SUBJECT = @{ CN = $subject }
        }
    } | ConvertTo-Json -Compress -Depth 5
    New-ItemProperty -LiteralPath $path -Name $next.ToString() -PropertyType String -Value $value | Out-Null
    $saved = (Get-ItemProperty -LiteralPath $path -Name $next.ToString()).$($next.ToString()) | ConvertFrom-Json
    if ($saved.pattern -ne $pattern -or
        $saved.filter.SUBJECT.CN -ne $subject -or
        $saved.filter.ISSUER.CN -ne $issuer) {
        throw "A politica para $pattern nao foi gravada corretamente."
    }
    $numbers += $next.ToString()
}
Write-Host '[OK] Edge configurado para selecionar o certificado nos dois dominios usados pela SEFAZ.'
Write-Host '[INFO] Feche todas as janelas do Edge e abra-o novamente antes do teste.'
