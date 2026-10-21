$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if ($env:CRM_PYTHON) {
    (Get-Command $env:CRM_PYTHON -ErrorAction Stop).Source
} else {
    (Get-Command python -ErrorAction Stop).Source
}
$ServiceScript = Join-Path $ProjectRoot 'crm_service.py'
$FirewallRuleName = 'AI CRM 8877 (LAN)'

Push-Location $ProjectRoot
try {
    & $Python $ServiceScript stop 2>$null
    & $Python $ServiceScript remove
    Remove-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
} finally {
    Pop-Location
}

Write-Host 'Service AICrm8877 removed.'
