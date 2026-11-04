$ErrorActionPreference = 'Stop'
$forgeRoot = $PSScriptRoot
$forgeNode = (Get-Command node.exe -ErrorAction Stop).Source
$forgeState = Join-Path $forgeRoot '.data'
New-Item -ItemType Directory -Path $forgeState -Force | Out-Null

function Test-ForgeEndpoint([string]$Uri) {
    try { return (Invoke-WebRequest -Uri $Uri -TimeoutSec 2).StatusCode -eq 200 }
    catch { return $false }
}

if (-not (Test-ForgeEndpoint 'http://127.0.0.1:8000/health')) {
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Port 8000 is occupied by an unhealthy service. Inspect it before relaunching.'
    }
    $forgeSupervisor = Join-Path $forgeRoot 'scripts\serve-backend.mjs'
    $forgeSupervisorRunning = $false
    $forgeSupervisorRecord = Join-Path $forgeState 'backend-supervisor.json'
    if (Test-Path -LiteralPath $forgeSupervisorRecord) {
        try {
            $forgeSavedSupervisor = Get-Content -LiteralPath $forgeSupervisorRecord -Raw | ConvertFrom-Json
            $forgeOwner = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$forgeSavedSupervisor.supervisor)
            $forgeSupervisorRunning = $null -ne $forgeOwner -and $forgeOwner.CommandLine.Contains($forgeSupervisor)
        } catch { $forgeSupervisorRunning = $false }
    }
    if (-not $forgeSupervisorRunning) {
        Start-Process -FilePath $forgeNode -ArgumentList @(('"' + $forgeSupervisor + '"')) -WorkingDirectory $forgeRoot -WindowStyle Hidden | Out-Null
    }
}

if (-not (Test-ForgeEndpoint 'http://127.0.0.1:3000/')) {
    if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Port 3000 is occupied by an unhealthy service. Inspect it before relaunching.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $forgeRoot 'frontend\.next\BUILD_ID'))) {
        throw 'Build the frontend with npm run build in frontend before starting Forge.'
    }
    $forgeNext = Join-Path $forgeRoot 'frontend\node_modules\next\dist\bin\next'
    Start-Process -FilePath $forgeNode -ArgumentList @(('"' + $forgeNext + '"'), 'start', '--hostname', '127.0.0.1', '--port', '3000') -WorkingDirectory (Join-Path $forgeRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $forgeState 'forge-web.stdout.log') -RedirectStandardError (Join-Path $forgeState 'forge-web.stderr.log') | Out-Null
}

for ($forgeAttempt = 0; $forgeAttempt -lt 20; $forgeAttempt++) {
    if (Test-ForgeEndpoint 'http://127.0.0.1:3000/api/health') {
        $forgeBackend = (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
        $forgeFrontend = (Get-NetTCPConnection -LocalPort 3000 -State Listen).OwningProcess
        @{backend=$forgeBackend;frontend=$forgeFrontend;app_url='http://127.0.0.1:3000';api_url='http://127.0.0.1:8000';launch_mode='supervised-background'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $forgeState 'running-services.json')
        Write-Output 'Forge is ready: http://127.0.0.1:3000/'
        exit 0
    }
    Start-Sleep -Milliseconds 500
}
throw 'Forge did not become healthy. Inspect .data\forge-api.stderr.log and .data\backend-supervisor.log.'
