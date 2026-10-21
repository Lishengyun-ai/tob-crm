$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonCommand = if ($env:CRM_PYTHON) {
    Get-Command $env:CRM_PYTHON -ErrorAction Stop
} else {
    Get-Command python -ErrorAction Stop
}
$Python = $PythonCommand.Source
$ServiceScript = Join-Path $ProjectRoot 'crm_service.py'
$FirewallRuleName = 'AI CRM 8877 (LAN)'

Write-Host "Using Python: $Python"
Write-Host "Installing service AICrm8877 from $ProjectRoot"

Push-Location $ProjectRoot
try {
    & $Python $ServiceScript --startup auto install
    & $Python $ServiceScript update
    & sc.exe failure AICrm8877 reset= 86400 actions= restart/60000/restart/60000/restart/60000
    if (-not (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $FirewallRuleName -Description 'Allow AI CRM backend for the local LAN/VPN only.' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8877 -Profile Domain,Private -RemoteAddress LocalSubnet | Out-Null
    }
    & $Python $ServiceScript start
} finally {
    Pop-Location
}

Write-Host 'Service installed and started.'
Write-Host 'Open http://127.0.0.1:8877/ or http://<this-computer-name>:8877/'
