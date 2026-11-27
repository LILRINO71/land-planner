# Makes a self-signed HTTPS certificate for this computer, for "Start Land Planner (network).bat".
#
#   powershell -ExecutionPolicy Bypass -File tools\make-cert.ps1            (writes data\tls\cert.pem and key.pem)
#   ... -OutDir C:\somewhere -DnsName planner.example.com -IpAddress 192.168.1.20 -Years 2 -Force
#   ... -OnlyGiven: name only the -DnsName and -IpAddress given (not localhost or this computer)
#
# Python's standard library cannot make certificates, so this uses Windows' own New-SelfSignedCertificate and
# exports the result as PEM. The certificate names localhost, this computer's name and its network addresses, so
# people can use any of them. It is self-signed: browsers warn once that it is not trusted (see the README).
# The private key is written to key.pem unencrypted and the copy in the Windows certificate store is deleted.
# land-planner.cer is the same certificate (no key) for anyone who wants their computer to trust it.
param(
    [string]$OutDir = "",
    [string[]]$DnsName = @(),
    [string[]]$IpAddress = @(),
    [int]$Years = 2,
    [string]$Label = "",
    [switch]$Force,
    [switch]$OnlyGiven
)
$ErrorActionPreference = "Stop"
# Started from PowerShell 7, Windows PowerShell can inherit a module path that hides its own Cert: drive.
if (-not (Get-PSDrive -Name Cert -ErrorAction SilentlyContinue)) {
    Import-Module (Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security") -ErrorAction SilentlyContinue
    Import-Module (Join-Path $PSHOME "Modules\PKI") -ErrorAction SilentlyContinue
}
# "-DnsName a,b" arrives as one string when the script is run with -File
$DnsName = @($DnsName | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$IpAddress = @($IpAddress | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })

if (-not $OutDir) { $OutDir = Join-Path (Split-Path -Parent $PSScriptRoot) "data\tls" }
$certPath = Join-Path $OutDir "cert.pem"
$keyPath = Join-Path $OutDir "key.pem"
if ((Test-Path -LiteralPath $certPath) -and -not $Force) {
    Write-Host "A certificate is already at $certPath (use -Force to make a new one)."
    exit 0
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# the names and addresses people may type
$names = New-Object System.Collections.Generic.List[string]
$baseNames = if ($OnlyGiven) { @() } else { @("localhost", $env:COMPUTERNAME) }
$baseIps = if ($OnlyGiven) { @() } else { @("127.0.0.1", "::1") }
foreach ($n in $baseNames + $DnsName) { if ($n -and -not $names.Contains($n.ToLower())) { $names.Add($n.ToLower()) } }
if (-not $OnlyGiven) { try {
    $fq = [System.Net.Dns]::GetHostEntry($env:COMPUTERNAME).HostName.ToLower()
    if ($fq -and -not $names.Contains($fq)) { $names.Add($fq) }
} catch { } }
$ips = New-Object System.Collections.Generic.List[string]
foreach ($a in $baseIps + $IpAddress) { if ($a -and -not $ips.Contains($a)) { $ips.Add($a) } }
if ($IpAddress.Count -eq 0 -and -not $OnlyGiven) {
    try {
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
            ForEach-Object { if (-not $ips.Contains($_.IPAddress)) { $ips.Add($_.IPAddress) } }
    } catch { }
}
$san = (@($names | ForEach-Object { "DNS=$_" }) + @($ips | ForEach-Object { "IPAddress=$_" })) -join "&"
if (-not $Label) { $Label = "Land Planner ($env:COMPUTERNAME)" }

$cert = New-SelfSignedCertificate -Subject "CN=$Label" -FriendlyName $Label `
    -TextExtension @("2.5.29.17={text}$san", "2.5.29.37={text}1.3.6.1.5.5.7.3.1", "2.5.29.19={text}ca=0") `
    -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 -KeyUsage DigitalSignature, KeyEncipherment `
    -KeyExportPolicy Exportable -NotAfter (Get-Date).AddYears($Years) -CertStoreLocation "Cert:\CurrentUser\My"

function ConvertTo-Pem([byte[]]$der, [string]$kind) {
    $b64 = [Convert]::ToBase64String($der)
    $lines = for ($i = 0; $i -lt $b64.Length; $i += 64) { $b64.Substring($i, [Math]::Min(64, $b64.Length - $i)) }
    "-----BEGIN $kind-----`n" + ($lines -join "`n") + "`n-----END $kind-----`n"
}

# DER for an RSA private key (PKCS#1), built from the key's numbers: works on every Windows PowerShell
function Get-DerLength([int]$n) {
    if ($n -lt 128) { return , [byte[]]@($n) }
    $b = New-Object System.Collections.Generic.List[byte]
    while ($n -gt 0) { $b.Insert(0, [byte]($n -band 0xFF)); $n = $n -shr 8 }
    return , [byte[]](@([byte](0x80 + $b.Count)) + $b.ToArray())
}
function Get-DerInteger([byte[]]$v) {
    $i = 0
    while ($i -lt $v.Length - 1 -and $v[$i] -eq 0) { $i++ }
    $v = [byte[]]$v[$i..($v.Length - 1)]
    if ($v[0] -ge 0x80) { $v = [byte[]](@([byte]0) + $v) }
    return , [byte[]](@([byte]0x02) + (Get-DerLength $v.Length) + $v)
}
function Get-Pkcs1([System.Security.Cryptography.RSAParameters]$p) {
    $body = New-Object System.Collections.Generic.List[byte]
    foreach ($part in @([byte[]]@(0), $p.Modulus, $p.Exponent, $p.D, $p.P, $p.Q, $p.DP, $p.DQ, $p.InverseQ)) {
        $body.AddRange([byte[]](Get-DerInteger $part))
    }
    return , [byte[]](@([byte]0x30) + (Get-DerLength $body.Count) + $body.ToArray())
}

try {
    $rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
    $keyPem = ConvertTo-Pem (Get-Pkcs1 $rsa.ExportParameters($true)) "RSA PRIVATE KEY"
    $certPem = ConvertTo-Pem $cert.RawData "CERTIFICATE"
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($keyPath, $keyPem, $utf8)
    [System.IO.File]::WriteAllText($certPath, $certPem, $utf8)
    [System.IO.File]::WriteAllBytes((Join-Path $OutDir "land-planner.cer"), $cert.RawData)
} finally {
    Remove-Item -LiteralPath ("Cert:\CurrentUser\My\" + $cert.Thumbprint) -DeleteKey -ErrorAction SilentlyContinue
}

Write-Host "Made a certificate for: $(($names + $ips) -join ', ')"
Write-Host "  $certPath"
Write-Host "  $keyPath   (the private key: keep it on this computer, never send it to anyone)"
Write-Host "  Valid until $($cert.NotAfter.ToString('yyyy-MM-dd')). Run again with -Force after this computer's address changes."
