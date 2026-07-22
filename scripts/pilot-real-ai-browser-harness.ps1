$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$sourceData = if ($env:OFFERPILOT_DATA) { $env:OFFERPILOT_DATA } else { Join-Path $HOME '.offerpilot' }
$tempData = Join-Path ([IO.Path]::GetTempPath()) ('offerpilot-pilot-real-ai-' + [Guid]::NewGuid().ToString('N'))
$portProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$portProbe.Start()
$port = ([Net.IPEndPoint]$portProbe.LocalEndpoint).Port
$portProbe.Stop()

if (@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
  throw "Selected browser harness port $port is already in use."
}

New-Item -ItemType Directory -Force -Path $tempData | Out-Null
$sourceConfig = Join-Path $sourceData 'config.json'
if (Test-Path -LiteralPath $sourceConfig) {
  Copy-Item -LiteralPath $sourceConfig -Destination (Join-Path $tempData 'config.json')
}

$previousData = $env:OFFERPILOT_DATA
$env:OFFERPILOT_DATA = $tempData
$server = $null
$applicationId = $null
$resumeIds = @()
$baseUrl = "http://127.0.0.1:$port"

function Get-TreeIds([int]$processId) {
  $processId
  Get-CimInstance Win32_Process | Where-Object ParentProcessId -eq $processId |
    ForEach-Object { Get-TreeIds ([int]$_.ProcessId) }
}

function Assert-HarnessPortOwner([int]$rootProcessId, [int]$expectedPort) {
  $listeners = @(Get-NetTCPConnection -LocalPort $expectedPort -State Listen -ErrorAction SilentlyContinue)
  if ($listeners.Count -eq 0) { return $false }
  $treeIds = @(Get-TreeIds $rootProcessId)
  $foreign = @($listeners | Where-Object { $treeIds -notcontains [int]$_.OwningProcess })
  if ($foreign.Count -gt 0) {
    throw "Harness port $expectedPort is owned by a process outside the harness tree."
  }
  return $true
}

try {
  $server = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "Set-Location '$repo'; `$env:OFFERPILOT_DATA = '$tempData'; uv run oc start --port $port"
  )
  $healthy = $false
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $ownerVerified = Assert-HarnessPortOwner ([int]$server.Id) $port
    if (-not $ownerVerified) {
      if ($server.HasExited) { throw "Isolated OfferPilot exited before binding harness port $port." }
      Start-Sleep -Milliseconds 500
      continue
    }
    try {
      $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2
      if ($health) { $healthy = $true; break }
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  if (-not $healthy) { throw "Isolated OfferPilot service did not become healthy." }
  Assert-HarnessPortOwner ([int]$server.Id) $port

  $resume = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/resumes" -ContentType 'application/json' -Body (@{
    title = 'Pilot Browser Smoke Resume'
    text = 'Built API services and led migration.'
    content_json = @{ raw_text = 'Built API services and led migration.'; skills = @('Python') }
  } | ConvertTo-Json -Depth 8)
  $resumeIds += [int]$resume.id
  $application = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/applications" -ContentType 'application/json' -Body (@{
    company_name = 'Pilot Browser Smoke'
    position_name = 'Verification Engineer'
    status = 'applied'
    source = 'smoke'
  } | ConvertTo-Json)
  $applicationId = [int]$application.id

  Write-Host "Isolated browser harness is ready: $baseUrl"
  Write-Host "Synthetic Application ID: $applicationId; Resume ID: $($resumeIds -join ', ')"
  Write-Host 'Open the base URL in the in-app browser. Navigate to the application list/board, open Pilot Browser Smoke · Verification Engineer, click 在 Pilot 中评估, and complete the Triage → Deep Review → 准备材料 flow.'
  Write-Host 'Verify requests stay on local /api and the configured AI provider, then return here.'
  [void](Read-Host 'Press Enter after browser acceptance')
}
finally {
  if ($server) {
    $treeIds = @(Get-TreeIds ([int]$server.Id) | Sort-Object -Descending)
    foreach ($processId in $treeIds) {
      Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue
    }
  }

  if ($applicationId -and $resumeIds.Count -gt 0) {
    $env:PILOT_BROWSER_HARNESS_DATA = $tempData
    $env:PILOT_BROWSER_HARNESS_APPLICATION_ID = [string]$applicationId
    $env:PILOT_BROWSER_HARNESS_RESUME_IDS = ($resumeIds -join ',')
    Push-Location $repo
    try {
      uv run python -c "import os; from pathlib import Path; from offerpilot.smoke import _cleanup_real_ai_browser_records; _cleanup_real_ai_browser_records(Path(os.environ['PILOT_BROWSER_HARNESS_DATA']), int(os.environ['PILOT_BROWSER_HARNESS_APPLICATION_ID']), [int(value) for value in os.environ['PILOT_BROWSER_HARNESS_RESUME_IDS'].split(',') if value])"
      uv run python -c "import os; from pathlib import Path; from offerpilot.smoke import _assert_real_ai_smoke_data_clean; _assert_real_ai_smoke_data_clean(Path(os.environ['PILOT_BROWSER_HARNESS_DATA']))"
    }
    finally {
      Pop-Location
      Remove-Item Env:PILOT_BROWSER_HARNESS_DATA -ErrorAction SilentlyContinue
      Remove-Item Env:PILOT_BROWSER_HARNESS_APPLICATION_ID -ErrorAction SilentlyContinue
      Remove-Item Env:PILOT_BROWSER_HARNESS_RESUME_IDS -ErrorAction SilentlyContinue
    }
  }

  if (Test-Path -LiteralPath $tempData) {
    Remove-Item -LiteralPath $tempData -Recurse -Force
  }
  if ($null -eq $previousData) { Remove-Item Env:OFFERPILOT_DATA -ErrorAction SilentlyContinue }
  else { $env:OFFERPILOT_DATA = $previousData }
}
