$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$sourceData = if ($env:OFFERPILOT_DATA) { $env:OFFERPILOT_DATA } else { Join-Path $HOME '.offerpilot' }
$cdpUrl = $env:OFFER_NEGOTIATION_CDP_URL
$tempData = Join-Path ([IO.Path]::GetTempPath()) ('offerpilot-offer-negotiation-' + [Guid]::NewGuid().ToString('N'))
$httpAudit = Join-Path $tempData 'http-audit.jsonl'
$providerAudit = Join-Path $tempData 'provider-audit.jsonl'
$browserAudit = Join-Path $tempData 'browser-network.jsonl'
$browserStop = Join-Path $tempData 'browser-network.stop'
$browserReady = Join-Path $tempData 'browser-network.ready'
$server = $null
$proxy = $null
$browserAuditor = $null
$baseUrl = $null
$offerIds = @()
$dimensionIds = @()
$baselineCounts = $null
$previousData = $env:OFFERPILOT_DATA
$previousHttpAudit = $env:OFFERPILOT_HTTP_AUDIT_FILE
$previousHttpsProxy = $env:HTTPS_PROXY
$previousHttpProxy = $env:HTTP_PROXY
$previousNoProxy = $env:NO_PROXY

function Get-FreePort {
  $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
  try { $probe.Start(); return ([Net.IPEndPoint]$probe.LocalEndpoint).Port }
  finally { $probe.Stop() }
}

function Get-ProcessTree([int]$processId) {
  $processId
  Get-CimInstance Win32_Process | Where-Object ParentProcessId -eq $processId |
    ForEach-Object { Get-ProcessTree ([int]$_.ProcessId) }
}

function Stop-Tree([object]$process) {
  if ($null -eq $process) { return }
  try {
    $ids = @(Get-ProcessTree ([int]$process.Id) | Sort-Object -Unique)
    foreach ($id in $ids) { Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue }
  } catch { }
}

function Assert-ExitCode([string]$label) {
  if ($LASTEXITCODE -ne 0) { throw "$label failed." }
}

function Get-ProviderEndpoint([string]$configPath) {
  if (-not (Test-Path -LiteralPath $configPath)) { throw 'Provider config is missing.' }
  $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
  foreach ($provider in @($config.providers)) {
    if ($provider.enabled -and $provider.base_url) {
      $uri = [Uri]$provider.base_url
      $port = if ($uri.IsDefaultPort) { if ($uri.Scheme -eq 'https') { 443 } else { 80 } } else { $uri.Port }
      return [pscustomobject]@{ Scheme = $uri.Scheme; Host = $uri.Host; Port = $port; Tuple = "$($uri.Scheme)://$($uri.Host):$port" }
    }
  }
  throw 'No enabled Provider endpoint is configured.'
}

function Get-DomainCounts {
  $env:OFFER_NEGOTIATION_HARNESS_DB = Join-Path $tempData 'data.db'
  $code = @'
import json, os, sqlite3
db = sqlite3.connect(os.environ["OFFER_NEGOTIATION_HARNESS_DB"])
names = ["applications", "application_events", "resumes", "conversations", "messages", "questions", "mock_interview_attempts", "mock_interview_turns", "mock_interview_feedback_proposals", "mock_interview_review_drafts", "wakeup"]
tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
print(json.dumps({name: (db.execute(f"select count(*) from {name}").fetchone()[0] if name in tables else 0) for name in names}, separators=(",", ":")))
'@
  $json = & uv run python -c $code
  Assert-ExitCode 'domain baseline capture'
  return (($json -join '').Trim() | ConvertFrom-Json)
}

function Assert-CountsUnchanged($before, $after) {
  foreach ($property in $before.PSObject.Properties) {
    if ([int]$before.$($property.Name) -ne [int]$after.$($property.Name)) {
      throw "Unexpected cross-domain write in $($property.Name)."
    }
  }
}

function Read-BrowserRecords {
  if (-not (Test-Path -LiteralPath $browserAudit)) { throw 'Browser audit output is missing.' }
  return @(Get-Content -LiteralPath $browserAudit | ForEach-Object { $_ | ConvertFrom-Json })
}

function Assert-BrowserSequence([object[]]$records) {
  $localOrigin = [Uri]$baseUrl
  $bad = @($records | Where-Object {
    $uri = [Uri]$_.url
    $uri.Scheme -ne $localOrigin.Scheme -or $uri.Host -ne $localOrigin.Host -or $uri.Port -ne $localOrigin.Port
  })
  if ($bad.Count -gt 0) { throw 'Browser accessed a non-local URL.' }

  $urls = @($records | ForEach-Object { [string]$_.url })
  if (-not ($urls | Where-Object { $_ -match '/api/offers/comparison([?]|$)' })) { throw 'Browser did not read the structured comparison.' }
  if (-not ($records | Where-Object { $_.method -eq 'POST' -and $_.url -match '/api/offers/[0-9]+/negotiation/proposals$' })) { throw 'Browser did not generate a Proposal.' }
  if (-not ($records | Where-Object { $_.method -eq 'POST' -and $_.url -match '/api/offer-negotiation/proposals/[0-9]+/confirm$' })) { throw 'Browser did not confirm a Brief.' }
  if (-not ($records | Where-Object { $_.method -eq 'GET' -and $_.url -match '/api/offer-negotiation/proposals/[0-9]+$' })) { throw 'Browser did not read negotiation history.' }
}

$providerErrorCode = 'offer_negotiation_provider_error'
$unverifiableErrorCode = 'offer_negotiation_unverifiable'
$proposalDiagnosticMarker = 'offer_negotiation_proposal'
$diagnosticFields = @('failure_category', 'failure_categories', 'repair_attempted', 'repair_count', 'provider_request_id')
$chatDomain = 'Chat'

function Get-NegotiationErrorCode($body) {
  return [string]$body.error_code
}

try {
  if ([string]::IsNullOrWhiteSpace($cdpUrl)) { throw 'Set OFFER_NEGOTIATION_CDP_URL before running this harness.' }
  New-Item -ItemType Directory -Force -Path $tempData | Out-Null
  Copy-Item -LiteralPath (Join-Path $sourceData 'config.json') -Destination (Join-Path $tempData 'config.json')
  $provider = Get-ProviderEndpoint (Join-Path $tempData 'config.json')
  if ($provider.Scheme -ne 'https') { throw 'The configured Provider must use HTTPS.' }

  $port = Get-FreePort
  $proxyPort = Get-FreePort
  $baseUrl = "http://127.0.0.1:$port"
  $env:OFFERPILOT_DATA = $tempData
  $env:OFFERPILOT_HTTP_AUDIT_FILE = $httpAudit
  $env:HTTPS_PROXY = "http://127.0.0.1:$proxyPort"
  $env:HTTP_PROXY = "http://127.0.0.1:$proxyPort"
  $env:NO_PROXY = '127.0.0.1,localhost'

  $proxy = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "Set-Location '$repo'; uv run python scripts/provider-egress-proxy.py --port $proxyPort --audit '$providerAudit' --expected-scheme $($provider.Scheme) --expected-host $($provider.Host) --expected-port $($provider.Port)"
  )
  $server = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "Set-Location '$repo'; uv run oc start --port $port"
  )

  $healthy = $false
  for ($i = 0; $i -lt 60; $i++) {
    if ($server.HasExited) { throw 'Isolated service exited before readiness.' }
    try {
      if (Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2) { $healthy = $true; break }
    } catch { Start-Sleep -Milliseconds 500 }
  }
  if (-not $healthy) { throw 'Isolated service did not become healthy.' }

  $browserAuditor = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "Set-Location '$repo'; uv run python scripts/browser-network-audit.py --debugging-url '$cdpUrl' --expected-url '$baseUrl' --audit '$browserAudit' --stop-file '$browserStop' --ready-file '$browserReady'"
  )
  for ($i = 0; $i -lt 120; $i++) {
    if ($browserAuditor.HasExited) { throw 'Browser auditor exited before readiness.' }
    if (Test-Path -LiteralPath $browserReady) { break }
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Path -LiteralPath $browserReady)) { throw 'Browser auditor did not become ready.' }

  $offer = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/offers" -ContentType 'application/json' -Body '{"company_name":"\u661f\u4e91\u6570\u636e","position_name":"\u540e\u7aef\u5de5\u7a0b\u5e08","base_monthly":28000,"months_per_year":12,"signing_bonus":0,"notes":"\u7b71\u54f2\u9a8c\u6536"}'
  $second = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/offers" -ContentType 'application/json' -Body '{"company_name":"\u8fdc\u5c71\u79d1\u6280","position_name":"\u5e73\u53f0\u5de5\u7a0b\u5e08","base_monthly":30000,"months_per_year":12,"signing_bonus":0,"notes":"\u7b71\u54f2\u9a8c\u6536"}'
  $offerIds = @([int]$offer.id, [int]$second.id)
  foreach ($labelBody in @('{"label":"\u901a\u52e4"}', '{"label":"\u6210\u957f\u7a7a\u95f4"}')) {
    $dimension = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/offers/comparison-dimensions" -ContentType 'application/json' -Body $labelBody
    $dimensionIds += [int]$dimension.id
  }
  Invoke-RestMethod -Method Put -Uri "$baseUrl/api/offers/$($offerIds[0])/comparison-values/$($dimensionIds[0])" -ContentType 'application/json' -Body '{"value_text":"\u5730\u94c1 35 \u5206\u949f"}' | Out-Null
  Invoke-RestMethod -Method Put -Uri "$baseUrl/api/offers/$($offerIds[1])/comparison-values/$($dimensionIds[0])" -ContentType 'application/json' -Body '{"value_text":"\u516c\u4ea4 50 \u5206\u949f"}' | Out-Null
  $baselineCounts = Get-DomainCounts

  Write-Host 'Browser target is ready. Compare both Offers and select one Offer.'
  Write-Host 'Enter Chinese goal, concerns, and scenario, confirm AI, edit and confirm the Brief, then reopen history.'
  Write-Host 'Open Pilot, explicitly select the same Offer, and open the same negotiation flow. Do not open a second tab.'
  [void](Read-Host 'Press Enter after the browser acceptance flow is complete')

  Assert-CountsUnchanged $baselineCounts (Get-DomainCounts)
  $records = Read-BrowserRecords
  Assert-BrowserSequence $records
  $historyRows = @(Invoke-RestMethod -Uri "$baseUrl/api/offers/$($offerIds[0])/negotiation/proposals")
  $confirmed = @($historyRows | Where-Object { $null -ne $_.brief })
  if ($confirmed.Count -eq 0) { throw 'No confirmed negotiation Brief was found.' }
  $confirmedProposalId = [int]$confirmed[0].id
  $currentOffer = Invoke-RestMethod -Uri "$baseUrl/api/offers/$($offerIds[0])"
  $editBody = @{
    company_name = $currentOffer.company_name
    position_name = $currentOffer.position_name
    base_monthly = $currentOffer.base_monthly
    months_per_year = $currentOffer.months_per_year
    signing_bonus = $currentOffer.signing_bonus
    equity = $currentOffer.equity
    perks = $currentOffer.perks
    deadline = $currentOffer.deadline
    notes = 'source changed after confirmation'
    assessment = $currentOffer.assessment
    status = $currentOffer.status
  } | ConvertTo-Json
  Invoke-RestMethod -Method Put -Uri "$baseUrl/api/offers/$($offerIds[0])" -ContentType 'application/json' -Body $editBody | Out-Null
  $changedHistory = Invoke-RestMethod -Uri "$baseUrl/api/offer-negotiation/proposals/$confirmedProposalId"
  if (-not $changedHistory.source_changed) { throw 'History did not expose source_changed after Offer edit.' }
  $proxyRecords = @(Get-Content -LiteralPath $providerAudit | ForEach-Object { $_ | ConvertFrom-Json })
  if (-not ($proxyRecords | Where-Object { $_.status -eq 'connected' -and "$($_.scheme)://$($_.host):$($_.port)" -eq $provider.Tuple })) { throw 'Provider egress did not match the configured endpoint.' }
  if ($proxyRecords | Where-Object { $_.status -ne 'connected' -and $_.status -ne 'rejected' }) { throw 'Provider egress audit contains an unknown status.' }
  Write-Host 'Offer negotiation browser acceptance passed.'
} catch {
  Write-Host 'Offer negotiation browser acceptance failed.'
  exit 1
} finally {
  if ($browserStop) { New-Item -ItemType File -Force -Path $browserStop | Out-Null }
  Stop-Tree $browserAuditor
  Stop-Tree $server
  Stop-Tree $proxy
  if ($previousData) { $env:OFFERPILOT_DATA = $previousData } else { Remove-Item Env:OFFERPILOT_DATA -ErrorAction SilentlyContinue }
  if ($previousHttpAudit) { $env:OFFERPILOT_HTTP_AUDIT_FILE = $previousHttpAudit } else { Remove-Item Env:OFFERPILOT_HTTP_AUDIT_FILE -ErrorAction SilentlyContinue }
  if ($previousHttpsProxy) { $env:HTTPS_PROXY = $previousHttpsProxy } else { Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue }
  if ($previousHttpProxy) { $env:HTTP_PROXY = $previousHttpProxy } else { Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue }
  if ($previousNoProxy) { $env:NO_PROXY = $previousNoProxy } else { Remove-Item Env:NO_PROXY -ErrorAction SilentlyContinue }
  Remove-Item Env:OFFER_NEGOTIATION_HARNESS_DB -ErrorAction SilentlyContinue
  if (Test-Path -LiteralPath $tempData) { Remove-Item -LiteralPath $tempData -Recurse -Force -ErrorAction SilentlyContinue }
}
