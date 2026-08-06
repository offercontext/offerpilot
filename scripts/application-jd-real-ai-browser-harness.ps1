param(
  [ValidateSet('all', 'jd-only')]
  [string]$Stage = 'all',
  [string]$CdpUrl = $env:APPLICATION_JD_CDP_URL
)
$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$sourceData = if ($env:OFFERPILOT_DATA) { $env:OFFERPILOT_DATA } else { Join-Path $HOME '.offerpilot' }
$tempData = Join-Path ([IO.Path]::GetTempPath()) ('offerpilot-application-jd-' + [Guid]::NewGuid().ToString('N'))
$httpAudit = Join-Path $tempData 'http-audit.jsonl'
$providerAudit = Join-Path $tempData 'provider-audit.jsonl'
$browserAudit = Join-Path $tempData 'browser-network.jsonl'
$browserStop = Join-Path $tempData 'browser-network.stop'
$browserReady = Join-Path $tempData 'browser-network.ready'
$server = $null
$proxy = $null
$auditor = $null
$browser = $null
$baseUrl = $null
$browserProfile = $null
$browserCdpPort = $null
$applicationId = $null
$resumeId = $null
$eventId = $null
$jdVersionId = $null
$beforeCleanup = $null
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

function Get-BrowserExecutable {
  $candidates = @(
    $env:OFFERPILOT_BROWSER_PATH,
    (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
    (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return (Resolve-Path -LiteralPath $candidate).Path }
  }
  throw 'No Chrome or Edge executable was found for the temporary browser.'
}

function Start-TemporaryBrowser([string]$url) {
  $browserCdpPort = Get-FreePort
  $browserProfile = Join-Path $tempData 'browser-profile'
  $executable = Get-BrowserExecutable
  $browser = Start-Process -FilePath $executable -WindowStyle Hidden -PassThru -ArgumentList @(
    "--remote-debugging-port=$browserCdpPort",
    "--user-data-dir=$browserProfile",
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-features=Translate,OptimizationHints',
    '--window-size=1440,1200',
    $url
  )
  $endpoint = "http://127.0.0.1:$browserCdpPort"
  for ($i = 0; $i -lt 60; $i++) {
    if ($browser.HasExited) { throw 'Temporary browser exited before CDP readiness.' }
    try {
      $version = Invoke-RestMethod -Uri "$endpoint/json/version" -TimeoutSec 2
      if ($version.webSocketDebuggerUrl) { return $endpoint }
    } catch { Start-Sleep -Milliseconds 500 }
  }
  throw 'Temporary browser CDP endpoint did not become ready.'
}

function Stop-Tree([object]$process) {
  if ($null -eq $process) { return }
  try {
    $ids = @($process.Id)
    foreach ($child in @(Get-CimInstance Win32_Process | Where-Object ParentProcessId -eq $process.Id)) {
      $ids += [int]$child.ProcessId
    }
    foreach ($id in @($ids | Sort-Object -Unique)) {
      Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
  } catch { }
}

function Assert-ExitCode([string]$label) {
  if ($LASTEXITCODE -ne 0) { throw "$label failed." }
}

function Get-ProviderEndpoints([string]$configPath) {
  $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
  $byId = @{}
  foreach ($provider in @($config.providers)) {
    if ($provider.id) { $byId[[string]$provider.id] = $provider }
  }
  if ($byId.Count -eq 0 -and $config.base_url) {
    $id = if ($config.active_provider_id) { [string]$config.active_provider_id } else { 'default' }
    $byId[$id] = [pscustomobject]@{ id = $id; enabled = $true; base_url = [string]$config.base_url }
  }
  $ids = @()
  if ($config.active_provider_id) { $ids += [string]$config.active_provider_id }
  if ($config.fallback_provider_ids) { $ids += @($config.fallback_provider_ids | ForEach-Object { [string]$_ }) }
  if ($config.fallback_provider_id) { $ids += [string]$config.fallback_provider_id }
  if ($ids.Count -eq 0) { $ids = @($byId.Keys) }
  $seen = @{}
  foreach ($id in $ids) {
    if (-not $byId.ContainsKey($id)) { continue }
    $provider = $byId[$id]
    if (-not $provider.enabled -or -not $provider.base_url) { continue }
    $uri = [Uri]$provider.base_url
    $port = if ($uri.IsDefaultPort) { if ($uri.Scheme -eq 'https') { 443 } else { 80 } } else { $uri.Port }
    $tuple = "$($uri.Scheme)://$($uri.Host):$port"
    if (-not $seen.ContainsKey($tuple)) {
      $seen[$tuple] = $true
      [pscustomobject]@{ scheme = $uri.Scheme; host = $uri.Host; port = $port; tuple = $tuple }
    }
  }
}

function Get-DbSnapshot {
  $env:APPLICATION_JD_HARNESS_DB = Join-Path $tempData 'data.db'
  $code = @'
import hashlib, json, os, sqlite3
db = sqlite3.connect(os.environ["APPLICATION_JD_HARNESS_DB"])
tables = [
  "applications", "application_events", "resumes", "application_jd_versions",
  "conversations", "chat_messages", "jd_analyses", "resume_matches",
  "application_material_kits", "material_revision_proposals",
  "opportunity_fit_reviews", "opportunity_fit_review_sessions", "opportunity_fit_review_stages",
  "interview_preparation_proposals", "mock_interview_attempts",
  "mock_interview_turns", "mock_interview_feedback_proposals", "mock_interview_review_drafts",
  "interview_notes", "interview_review_proposals", "offers", "offer_comparison_dimensions",
  "offer_comparison_values", "offer_negotiation_proposals", "offer_negotiation_briefs",
  "questions", "question_reviews", "wakeups", "knowledge_sources", "knowledge_source_origins",
  "knowledge_extraction_snapshots", "knowledge_notes", "knowledge_note_versions",
  "knowledge_note_evidence", "knowledge_captured_source_metadata", "knowledge_evidence",
  "knowledge_source_assets", "knowledge_jobs", "knowledge_logs", "knowledge_source_briefs",
  "knowledge_brief_attempts", "knowledge_brief_attempt_steps", "knowledge_retrieval_traces",
  "knowledge_evidence_fts",
  "interview_knowledge_capture_attempts", "application_evidence_bundles",
]
available = {row[0] for row in db.execute("select name from sqlite_master where type='table'")}
out = {}
for name in tables:
    rows = db.execute(f"select * from {name} order by rowid").fetchall() if name in available else []
    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), default=str)
    out[name] = {"count": len(rows), "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest()}
print(json.dumps(out, separators=(",", ":")))
'@
  $json = $code | & uv run python -
  Assert-ExitCode 'database snapshot'
  return (($json -join '').Trim() | ConvertFrom-Json)
}

function Assert-StageUnchanged($before, $after, [string[]]$allowedTables) {
  foreach ($property in $before.PSObject.Properties) {
    if ($property.Name -in $allowedTables) { continue }
    $old = $before.$($property.Name)
    $new = $after.$($property.Name)
    if ([int]$old.count -ne [int]$new.count -or [string]$old.sha256 -ne [string]$new.sha256) {
      throw "Unexpected write in $($property.Name)."
    }
  }
}

function Clear-Consumer([string]$consumer) {
  $env:APPLICATION_JD_HARNESS_DB = Join-Path $tempData 'data.db'
  $env:APPLICATION_JD_HARNESS_APP = [string]$applicationId
  $code = @'
import os, sqlite3
db = sqlite3.connect(os.environ["APPLICATION_JD_HARNESS_DB"])
app = int(os.environ["APPLICATION_JD_HARNESS_APP"])
consumer = os.environ["APPLICATION_JD_HARNESS_CONSUMER"]
if consumer == "triage":
    db.execute("delete from opportunity_fit_review_stages where review_id in (select id from opportunity_fit_review_sessions where application_id = ?)", (app,))
    db.execute("delete from opportunity_fit_review_sessions where application_id = ?", (app,))
elif consumer == "material-kit":
    db.execute("delete from application_material_kits where application_id = ?", (app,))
elif consumer == "interview-preparation":
    db.execute("delete from interview_preparation_proposals where application_id = ?", (app,))
else:
    raise SystemExit("unknown consumer")
db.commit()
'@
  $env:APPLICATION_JD_HARNESS_CONSUMER = $consumer
  $code | & uv run python -
  Assert-ExitCode "cleanup $consumer"
}

function Clear-SyntheticData {
  $env:APPLICATION_JD_HARNESS_DB = Join-Path $tempData 'data.db'
  $env:APPLICATION_JD_HARNESS_APP = [string]$applicationId
  $env:APPLICATION_JD_HARNESS_RESUME = [string]$resumeId
  $env:APPLICATION_JD_HARNESS_EVENT = [string]$eventId
  $code = @'
import os, sqlite3
db = sqlite3.connect(os.environ["APPLICATION_JD_HARNESS_DB"])
app = int(os.environ["APPLICATION_JD_HARNESS_APP"])
resume = int(os.environ["APPLICATION_JD_HARNESS_RESUME"])
event = int(os.environ["APPLICATION_JD_HARNESS_EVENT"])
for sql in (
    "delete from opportunity_fit_review_stages where review_id in (select id from opportunity_fit_review_sessions where application_id = ?)",
    "delete from opportunity_fit_review_sessions where application_id = ?",
    "delete from application_material_kits where application_id = ?",
    "delete from material_revision_proposals where application_id = ?",
    "delete from interview_preparation_proposals where application_id = ?",
    "delete from mock_interview_review_drafts where proposal_id in (select id from mock_interview_feedback_proposals where attempt_id in (select id from mock_interview_attempts where application_id = ?))",
    "delete from mock_interview_feedback_proposals where attempt_id in (select id from mock_interview_attempts where application_id = ?)",
    "delete from mock_interview_turns where attempt_id in (select id from mock_interview_attempts where application_id = ?)",
    "delete from mock_interview_attempts where application_id = ?",
    "delete from application_jd_versions where application_id = ?",
    "delete from chat_messages where conversation_id in (select id from conversations where context_type = 'application' and context_ref = ?)",
    "delete from conversations where context_type = 'application' and context_ref = ?",
    "delete from application_events where id = ?",
    "delete from resumes where id = ?",
    "delete from applications where id = ?",
):
    value = event if "application_events" in sql else resume if "resumes" in sql else app
    db.execute(sql, (value,))
db.commit()
remaining = db.execute("select count(*) from applications where id = ?", (app,)).fetchone()[0]
if remaining:
    raise SystemExit("synthetic Application cleanup left a row")
'@
  $code | & uv run python -
  Assert-ExitCode 'synthetic cleanup'
}

function Get-BrowserRecords {
  if (-not (Test-Path -LiteralPath $browserAudit)) { throw 'Browser audit output is missing.' }
  return @(Get-Content -LiteralPath $browserAudit | ForEach-Object { $_ | ConvertFrom-Json })
}

function Assert-LocalBrowser($records) {
  $origin = [Uri]$baseUrl
  foreach ($record in @($records | Where-Object kind -eq 'browser_request')) {
    $uri = [Uri]$record.url
    if ($uri.Scheme -ne $origin.Scheme -or $uri.Host -ne $origin.Host -or $uri.Port -ne $origin.Port) {
      throw 'Browser accessed a non-local URL.'
    }
    $routeMatch = [regex]::Match($record.url, '/api/applications/(\d+)(?:/|$)')
    $context = $record.request_context
    if ($routeMatch.Success -and $null -ne $context -and $null -ne $context.payload_application_id) {
      if ([int]$context.payload_application_id -ne [int]$routeMatch.Groups[1].Value) {
        throw 'Browser request payload application_id does not match its bound URL.'
      }
    }
  }
}

function Assert-ProviderEgress($allowedEndpoints) {
  if (-not (Test-Path -LiteralPath $providerAudit)) { throw 'Provider audit output is missing.' }
  $entries = @(Get-Content -LiteralPath $providerAudit | ForEach-Object { $_ | ConvertFrom-Json })
  $rejected = @($entries | Where-Object status -eq 'rejected')
  if ($rejected.Count -gt 0) { throw 'Provider egress proxy rejected an outbound connection.' }
  $connected = @($entries | Where-Object status -eq 'connected')
  if ($connected.Count -lt 1) { throw 'No real Provider connection was observed.' }
  foreach ($entry in $connected) {
    $tuple = "$($entry.scheme)://$($entry.host):$($entry.port)"
    if (-not (@($allowedEndpoints | Where-Object tuple -eq $tuple).Count)) {
      throw "Provider egress endpoint is outside the configured allowlist: $tuple"
    }
  }
}

function Assert-StageA($records) {
  $jdPosts = @($records | Where-Object { $_.kind -eq 'browser_request' -and $_.method -eq 'POST' -and $_.url -match '/api/applications/[0-9]+/job-description/versions$' })
  if ($jdPosts.Count -lt 2) { throw 'Stage A did not create UI JD versions.' }
  if (@($jdPosts | Where-Object { $_.request_context.application_id -ne [int]$applicationId }).Count -ne 0) { throw 'Stage A mixed applications.' }
  $jdResponses = @($records | Where-Object {
    $_.kind -eq 'browser_response' -and $_.method -eq 'POST' -and
    $_.url -match '/api/applications/[0-9]+/job-description/versions$' -and
    $_.response_status -in @(200, 201) -and $null -ne $_.response_jd_version_id
  })
  if ($jdResponses.Count -lt 2) { throw 'Stage A did not record successful JD version responses.' }
  $sourceKinds = @($jdResponses | ForEach-Object { [string]$_.response_source_kind } | Sort-Object -Unique)
  if ('ui' -notin $sourceKinds -or 'pilot' -notin $sourceKinds) { throw 'Stage A did not prove both UI and Pilot JD sources.' }
  if (-not ($records | Where-Object { $_.kind -eq 'browser_request' -and $_.method -eq 'GET' -and $_.url -match '/job-description/versions$' })) { throw 'Stage A did not read JD history.' }
  if (-not ($records | Where-Object { $_.kind -eq 'browser_request' -and $_.method -eq 'GET' -and $_.url -match '/job-description/versions/[0-9]+$' })) { throw 'Stage A did not read JD detail.' }
  if (-not ($records | Where-Object { $_.kind -eq 'browser_request' -and $_.method -eq 'POST' -and $_.url -match '/api/chat$' })) { throw 'Stage A did not record Pilot chat.' }
  if (-not ($records | Where-Object { $_.kind -eq 'browser_request' -and $_.method -eq 'POST' -and $_.url -match '/api/chat/confirm$' })) { throw 'Stage A did not record Pilot confirmation.' }
}

function Assert-ConsumerRequest($records, [string]$consumer) {
  $pattern = switch ($consumer) {
    'triage' { '/opportunity-fit-reviews$' }
    'material-kit' { '/material-kit/generate$' }
    'interview-preparation' { '/interview-preparation-proposals$' }
  }
  $matches = @($records | Where-Object {
    $_.kind -eq 'browser_request' -and $_.method -eq 'POST' -and $_.url -match $pattern -and
    $_.request_context.application_id -eq [int]$applicationId -and
    $_.request_context.jd_version_id -eq [int]$jdVersionId
  })
  if ($matches.Count -lt 1) { throw "Stage B did not submit $consumer with the frozen JD version." }
  $successful = @($records | Where-Object {
    $_.kind -eq 'browser_response' -and $_.method -eq 'POST' -and $_.url -match $pattern -and
    $_.request_context.application_id -eq [int]$applicationId -and
    $_.request_context.jd_version_id -eq [int]$jdVersionId -and
    $_.response_status -in @(200, 201) -and $_.response_jd_version_id -eq [int]$jdVersionId
  })
  if ($successful.Count -lt 1) { throw "Stage B did not record a successful $consumer response for the frozen JD version." }
}

try {
  $configPath = Join-Path $sourceData 'config.json'
  if (-not (Test-Path -LiteralPath $configPath)) { throw 'Provider config is missing.' }
  New-Item -ItemType Directory -Force -Path $tempData | Out-Null
  if ([string]::IsNullOrWhiteSpace($CdpUrl)) { $CdpUrl = Start-TemporaryBrowser 'about:blank' }
  Copy-Item -LiteralPath $configPath -Destination (Join-Path $tempData 'config.json')
  $providers = @(Get-ProviderEndpoints (Join-Path $tempData 'config.json'))
  if ($providers.Count -eq 0) { throw 'No enabled Provider endpoint is configured.' }
  $allowlist = Join-Path $tempData 'provider-allowlist.json'
  $providers | ConvertTo-Json -Compress | Set-Content -LiteralPath $allowlist -Encoding utf8
  $port = Get-FreePort
  $proxyPort = Get-FreePort
  $baseUrl = "http://127.0.0.1:$port"
  $env:OFFERPILOT_DATA = $tempData
  $env:OFFERPILOT_HTTP_AUDIT_FILE = $httpAudit
  $env:HTTPS_PROXY = "http://127.0.0.1:$proxyPort"
  $env:HTTP_PROXY = "http://127.0.0.1:$proxyPort"
  $env:NO_PROXY = '127.0.0.1,localhost'
  $proxy = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', "Set-Location '$repo'; uv run python scripts/provider-egress-proxy.py --port $proxyPort --audit '$providerAudit' --expected-endpoints-file '$allowlist'")
  $server = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', "Set-Location '$repo'; uv run oc start --port $port")
  $healthy = $false
  for ($i = 0; $i -lt 120; $i++) {
    if ($server.HasExited) { throw 'Isolated service exited before readiness.' }
    try { if (Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2) { $healthy = $true; break } } catch { Start-Sleep -Milliseconds 500 }
  }
  if (-not $healthy) { throw 'Isolated service did not become healthy.' }

  $beforeCleanup = Get-DbSnapshot
  $application = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/applications" -ContentType 'application/json' -Body '{"company_name":"\u7b71\u54f2\u6848\u4f8b\u516c\u53f8","position_name":"\u540e\u7aef\u5de5\u7a0b\u5e08","status":"applied"}'
  $applicationId = [int]$application.id
  $resume = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/resumes" -ContentType 'application/json' -Body '{"title":"\u7b71\u54f2\u540e\u7aef\u7b80\u5386","text":"Python FastAPI SQLAlchemy"}'
  $resumeId = [int]$resume.id
  $event = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/application-events" -ContentType 'application/json' -Body (ConvertTo-Json @{ application_id = $applicationId; event_type = 'interview'; subtype = 'technical'; scheduled_at = '2026-12-01T10:00:00Z'; duration_minutes = 60; status = 'todo' })
  $eventId = [int]$event.id
  $beforeA = Get-DbSnapshot

  $auditor = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', "Set-Location '$repo'; uv run python scripts/browser-network-audit.py --debugging-url '$CdpUrl' --expected-url '$baseUrl' --audit '$browserAudit' --stop-file '$browserStop' --ready-file '$browserReady'")
  for ($i = 0; $i -lt 120; $i++) {
    if ($auditor.HasExited) { throw 'Browser auditor exited before readiness.' }
    if (Test-Path -LiteralPath $browserReady) { break }
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Path -LiteralPath $browserReady)) { throw 'Browser auditor did not become ready.' }
  Write-Host 'Dedicated browser target is ready. Complete JD UI and Pilot confirmation in that target.'
  Write-Host 'Then complete triage, material kit, and interview preparation in that same target.'
  [void](Read-Host 'Press Enter after the requested browser stages are complete')
  $records = Get-BrowserRecords
  Assert-LocalBrowser $records
  Assert-StageA $records
  Assert-ProviderEgress $providers
  $afterA = Get-DbSnapshot
  Assert-StageUnchanged $beforeA $afterA @('application_jd_versions', 'conversations', 'chat_messages')
  $env:APPLICATION_JD_HARNESS_DB = Join-Path $tempData 'data.db'
  $env:APPLICATION_JD_HARNESS_APP = [string]$applicationId
  $jdVersionCode = @'
import os, sqlite3
db = sqlite3.connect(os.environ["APPLICATION_JD_HARNESS_DB"])
print(db.execute(
    "select id from application_jd_versions where application_id = ? "
    "order by version_number desc limit 1",
    (int(os.environ["APPLICATION_JD_HARNESS_APP"]),),
).fetchone()[0])
'@
  $jdVersionId = [int](($jdVersionCode | & uv run python -).Trim())
  Assert-ExitCode 'JD version readback'

  if ($Stage -eq 'jd-only') {
    Write-Host 'Application JD browser acceptance passed.'
  } else {
    foreach ($consumer in @('triage', 'material-kit', 'interview-preparation')) {
      $consumerBefore = Get-DbSnapshot
      Write-Host "Complete $consumer in the dedicated browser target."
      [void](Read-Host 'Press Enter after this consumer is complete')
      $records = Get-BrowserRecords
      Assert-LocalBrowser $records
      Assert-ConsumerRequest $records $consumer
      $consumerAfter = Get-DbSnapshot
      $allowed = switch ($consumer) {
        'triage' { @('opportunity_fit_review_sessions', 'opportunity_fit_review_stages') }
        'material-kit' { @('application_material_kits') }
        'interview-preparation' { @('interview_preparation_proposals') }
      }
      Assert-StageUnchanged $consumerBefore $consumerAfter $allowed
      Clear-Consumer $consumer
      Assert-StageUnchanged $consumerBefore (Get-DbSnapshot) @()
    }
    Assert-ProviderEgress $providers
    Write-Host 'Application JD browser acceptance passed.'
  }
} catch {
  Write-Host 'Application JD browser acceptance failed.'
  throw
} finally {
  if ($browserStop) { New-Item -ItemType File -Force -Path $browserStop | Out-Null }
  Stop-Tree $auditor
  Stop-Tree $server
  Stop-Tree $proxy
  Stop-Tree $browser
  if ($applicationId -and $resumeId -and $eventId -and (Test-Path -LiteralPath (Join-Path $tempData 'data.db'))) {
    Clear-SyntheticData
    if ($beforeCleanup) { Assert-StageUnchanged $beforeCleanup (Get-DbSnapshot) @() }
  }
  if ($previousData) { $env:OFFERPILOT_DATA = $previousData } else { Remove-Item Env:OFFERPILOT_DATA -ErrorAction SilentlyContinue }
  if ($previousHttpAudit) { $env:OFFERPILOT_HTTP_AUDIT_FILE = $previousHttpAudit } else { Remove-Item Env:OFFERPILOT_HTTP_AUDIT_FILE -ErrorAction SilentlyContinue }
  if ($previousHttpsProxy) { $env:HTTPS_PROXY = $previousHttpsProxy } else { Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue }
  if ($previousHttpProxy) { $env:HTTP_PROXY = $previousHttpProxy } else { Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue }
  if ($previousNoProxy) { $env:NO_PROXY = $previousNoProxy } else { Remove-Item Env:NO_PROXY -ErrorAction SilentlyContinue }
  Remove-Item Env:APPLICATION_JD_HARNESS_DB, Env:APPLICATION_JD_HARNESS_APP, Env:APPLICATION_JD_HARNESS_RESUME, Env:APPLICATION_JD_HARNESS_EVENT, Env:APPLICATION_JD_HARNESS_CONSUMER -ErrorAction SilentlyContinue
  if (Test-Path -LiteralPath $tempData) { Remove-Item -LiteralPath $tempData -Recurse -Force -ErrorAction SilentlyContinue }
}
