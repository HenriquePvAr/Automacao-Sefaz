param(
    [string]$SelectorPath,
    [string]$PfxPath
)

$ErrorActionPreference = 'Stop'
$storeLocation = [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
$storeName = [System.Security.Cryptography.X509Certificates.StoreName]::My
$readOnly = [System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly

# Na distribuicao-fonte, o certificado pode ja estar instalado na conta Windows.
# Sem arquivos PFX/seletor locais, apenas confirmamos que existe um certificado
# valido; a escolha automatica para os dominios da SEFAZ e configurada depois.
if (-not $SelectorPath -or -not (Test-Path -LiteralPath $SelectorPath)) {
    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new($storeName, $storeLocation)
    $store.Open($readOnly)
    try {
        $available = @($store.Certificates | Where-Object {
            $_.HasPrivateKey -and $_.NotBefore -le (Get-Date) -and $_.NotAfter -ge (Get-Date)
        })
    } finally {
        $store.Close()
    }
    if ($available.Count -eq 0) {
        throw 'Nenhum certificado valido foi encontrado nesta conta. Instale-o no Windows ou use o pacote de implantacao protegido.'
    }
    Write-Host '[OK] Certificado valido ja esta instalado nesta conta; nenhuma importacao foi necessaria.'
    exit 0
}

$selector = Get-Content -LiteralPath $SelectorPath -Raw | ConvertFrom-Json
$thumbprint = ([string]$selector.thumbprint -replace '\s', '').ToUpperInvariant()
if ([string]::IsNullOrWhiteSpace($thumbprint)) {
    throw 'O seletor de certificado deste pacote esta incompleto.'
}

$store = [System.Security.Cryptography.X509Certificates.X509Store]::new($storeName, $storeLocation)
$store.Open($readOnly)
try {
    $installed = @($store.Certificates | Where-Object {
        $_.Thumbprint -eq $thumbprint -and $_.HasPrivateKey -and
        $_.NotBefore -le (Get-Date) -and $_.NotAfter -ge (Get-Date)
    })
} finally {
    $store.Close()
}
if ($installed.Count -eq 1) {
    Write-Host '[OK] Certificado ja instalado e valido; importacao ignorada.'
    exit 0
}
if ($installed.Count -gt 1) {
    throw 'Mais de uma copia do certificado preparado esta instalada; revise o armazenamento do usuario.'
}
if (-not (Test-Path -LiteralPath $PfxPath)) {
    throw 'Certificado preparado nao esta instalado e o arquivo PFX nao esta no pacote.'
}

$password = Read-Host 'Certificado ausente. Digite a senha do PFX para instalar somente nesta conta do Windows' -AsSecureString
$pointer = [IntPtr]::Zero
$plainPassword = $null
$bytes = [System.IO.File]::ReadAllBytes($PfxPath)
$certificate = $null
try {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $ephemeral = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
    $candidate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($bytes, $plainPassword, $ephemeral)
    if ($candidate.Thumbprint.ToUpperInvariant() -ne $thumbprint) {
        $candidate.Dispose()
        throw 'O PFX informado nao corresponde ao certificado preparado para esta usuaria.'
    }
    if (-not $candidate.HasPrivateKey -or $candidate.NotBefore -gt (Get-Date) -or $candidate.NotAfter -lt (Get-Date)) {
        $candidate.Dispose()
        throw 'O certificado do PFX nao possui chave privada valida para uso agora.'
    }
    $candidate.Dispose()

    $persist = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::UserKeySet -bor
               [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::PersistKeySet
    $certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($bytes, $plainPassword, $persist)
    $writeStore = [System.Security.Cryptography.X509Certificates.X509Store]::new($storeName, $storeLocation)
    $writeStore.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    try {
        $writeStore.Add($certificate)
    } finally {
        $writeStore.Close()
    }
} catch {
    throw "Nao foi possivel instalar o certificado: $($_.Exception.Message)"
} finally {
    if ($certificate) { $certificate.Dispose() }
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $plainPassword = $null
    $password.Dispose()
    [Array]::Clear($bytes, 0, $bytes.Length)
}

$store = [System.Security.Cryptography.X509Certificates.X509Store]::new($storeName, $storeLocation)
$store.Open($readOnly)
try {
    $verified = @($store.Certificates | Where-Object {
        $_.Thumbprint -eq $thumbprint -and $_.HasPrivateKey -and
        $_.NotBefore -le (Get-Date) -and $_.NotAfter -ge (Get-Date)
    })
} finally {
    $store.Close()
}
if ($verified.Count -ne 1) {
    throw 'A verificacao final do certificado instalado falhou.'
}
Write-Host '[OK] Certificado instalado e verificado nesta conta do Windows.'
