$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$sourceData = if ($env:OFFERPILOT_DATA) { $env:OFFERPILOT_DATA } else { Join-Path $HOME '.offerpilot' }
$tempData = Join-Path ([IO.Path]::GetTempPath()) ('offerpilot-mock-interview-' + [Guid]::NewGuid().ToString('N'))
$probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$probe.Start()
$port = ([Net.IPEndPoint]$probe.LocalEndpoint).Port
$probe.Stop()
$baseUrl = "http://127.0.0.1:$port"
$server = $null
$applicationId = $null
$eventId = $null
$resumeIds = @()
$previousData = $env:OFFERPILOT_DATA

function Get-ProcessTree([int]$processId) {
  $processId
  Get-CimInstance Win32_Process | Where-Object ParentProcessId -eq $processId |
    ForEach-Object { Get-ProcessTree ([int]$_.ProcessId) }
}

function Assert-ExitCode([string]$label) {
  if ($LASTEXITCODE -ne 0) { throw "$label failed with exit code $LASTEXITCODE" }
}

function Assert-PortOwner([int]$rootProcessId, [int]$expectedPort) {
  $listeners = @(Get-NetTCPConnection -LocalPort $expectedPort -State Listen -ErrorAction SilentlyContinue)
  if ($listeners.Count -eq 0) { return $false }
  $tree = @(Get-ProcessTree $rootProcessId)
  if (@($listeners | Where-Object { $tree -notcontains [int]$_.OwningProcess }).Count -gt 0) {
    throw "Port $expectedPort is owned outside the harness process tree."
  }
  return $true
}

try {
  if ((@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)).Count -gt 0) {
    throw "Selected harness port $port is already in use."
  }
  New-Item -ItemType Directory -Force -Path $tempData | Out-Null
  $sourceConfig = Join-Path $sourceData 'config.json'
  if (Test-Path -LiteralPath $sourceConfig) {
    Copy-Item -LiteralPath $sourceConfig -Destination (Join-Path $tempData 'config.json')
  }
  $env:OFFERPILOT_DATA = $tempData
  $server = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "Set-Location '$repo'; `$env:OFFERPILOT_DATA = '$tempData'; uv run oc start --port $port"
  )
  $healthy = $false
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($server.HasExited) { throw 'Mock interview harness service exited before becoming ready.' }
    if (Assert-PortOwner ([int]$server.Id) $port) {
      try {
        $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2
        if ($health) { $healthy = $true; break }
      } catch { Start-Sleep -Milliseconds 500 }
    } else { Start-Sleep -Milliseconds 500 }
  }
  if (-not $healthy) { throw "Isolated service did not become healthy on $baseUrl." }

  $resume = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/resumes" -ContentType 'application/json' -Body (@{
    title = 'Mock Interview Browser Smoke Resume'
    text = 'Built Python services and explained rollback tradeoffs.'
    content_json = @{ raw_text = 'Built Python services and explained rollback tradeoffs.' }
  } | ConvertTo-Json -Depth 8)
  $resumeIds += [int]$resume.id
  $application = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/applications" -ContentType 'application/json' -Body (@{
    company_name = 'Mock Interview Browser Smoke'
    position_name = 'Verification Engineer'
    status = 'interview'
    source = 'isolated-smoke'
  } | ConvertTo-Json)
  $applicationId = [int]$application.id
  $event = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/application-events" -ContentType 'application/json' -Body (@{
    application_id = $applicationId
    event_type = 'interview'
    subtype = 'text-mock-interview'
    round = 1
    scheduled_at = '2026-07-28T10:00:00+08:00'
    duration_minutes = 30
  } | ConvertTo-Json)
  $eventId = [int]$event.id

  Push-Location $repo
  try {
    $env:MOCK_INTERVIEW_HARNESS_DATA = $tempData
    $env:MOCK_INTERVIEW_HARNESS_APPLICATION = [string]$applicationId
    $env:MOCK_INTERVIEW_HARNESS_EVENT = [string]$eventId
    $env:MOCK_INTERVIEW_HARNESS_RESUME = [string]$resumeIds[0]
    $baseline = & uv run python -c "import json, os; from pathlib import Path; from offerpilot.smoke import _capture_real_ai_browser_domain_baseline; print(json.dumps(_capture_real_ai_browser_domain_baseline(Path(os.environ['MOCK_INTERVIEW_HARNESS_DATA']), int(os.environ['MOCK_INTERVIEW_HARNESS_APPLICATION']), [int(os.environ['MOCK_INTERVIEW_HARNESS_EVENT'])], [int(os.environ['MOCK_INTERVIEW_HARNESS_RESUME'])])))"
    Assert-ExitCode 'baseline capture'
    $env:MOCK_INTERVIEW_HARNESS_BASELINE = ($baseline -join '')
  } finally { Pop-Location }

  Write-Host "Open $baseUrl in the in-app browser. Navigate to 面试, choose Mock Interview Browser Smoke · Verification Engineer, then click 开始文本模拟面试."
  Write-Host 'Select the synthetic resume, paste a non-empty JD, start the text session, submit an answer, finish, select feedback if present, and use the second confirmation to save the independent review draft.'
  Write-Host 'Close and reopen the event to view read-only history. Browser requests must stay on local static resources and /api; Provider egress is server-side only.'
  [void](Read-Host 'Press Enter after completing the real browser flow')

  Push-Location $repo
  try {
    & uv run python -c "import json, os; from pathlib import Path; from offerpilot.smoke import _assert_real_ai_browser_no_cross_domain_writes; _assert_real_ai_browser_no_cross_domain_writes(Path(os.environ['MOCK_INTERVIEW_HARNESS_DATA']), int(os.environ['MOCK_INTERVIEW_HARNESS_APPLICATION']), json.loads(os.environ['MOCK_INTERVIEW_HARNESS_BASELINE']), [int(os.environ['MOCK_INTERVIEW_HARNESS_EVENT'])], [int(os.environ['MOCK_INTERVIEW_HARNESS_RESUME'])])"
    Assert-ExitCode 'cross-domain boundary assertion'
  } finally { Pop-Location }
} finally {
  if ($server) {
    $tree = @(Get-ProcessTree ([int]$server.Id) | Sort-Object -Descending)
    foreach ($processId in $tree) { Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue }
  }
  if ($applicationId) {
    Push-Location $repo
    try {
      $env:MOCK_INTERVIEW_HARNESS_DATA = $tempData
      $env:MOCK_INTERVIEW_HARNESS_APPLICATION = [string]$applicationId
      $env:MOCK_INTERVIEW_HARNESS_RESUME = ($resumeIds -join ',')
      & uv run python -c "import os; from pathlib import Path; from offerpilot.smoke import _cleanup_real_ai_browser_records; _cleanup_real_ai_browser_records(Path(os.environ['MOCK_INTERVIEW_HARNESS_DATA']), int(os.environ['MOCK_INTERVIEW_HARNESS_APPLICATION']), [int(v) for v in os.environ['MOCK_INTERVIEW_HARNESS_RESUME'].split(',') if v])"
      Assert-ExitCode 'isolated cleanup'
      & uv run python -c "import os; from pathlib import Path; from offerpilot.smoke import _assert_real_ai_smoke_data_clean; _assert_real_ai_smoke_data_clean(Path(os.environ['MOCK_INTERVIEW_HARNESS_DATA']))"
      Assert-ExitCode 'isolated residual assertion'
    } finally { Pop-Location }
  }
  if (Test-Path -LiteralPath $tempData) { Remove-Item -LiteralPath $tempData -Recurse -Force }
  if ($null -eq $previousData) { Remove-Item Env:OFFERPILOT_DATA -ErrorAction SilentlyContinue }
  else { $env:OFFERPILOT_DATA = $previousData }
  Remove-Item Env:MOCK_INTERVIEW_HARNESS_DATA -ErrorAction SilentlyContinue
  Remove-Item Env:MOCK_INTERVIEW_HARNESS_APPLICATION -ErrorAction SilentlyContinue
  Remove-Item Env:MOCK_INTERVIEW_HARNESS_EVENT -ErrorAction SilentlyContinue
  Remove-Item Env:MOCK_INTERVIEW_HARNESS_RESUME -ErrorAction SilentlyContinue
  Remove-Item Env:MOCK_INTERVIEW_HARNESS_BASELINE -ErrorAction SilentlyContinue
}
