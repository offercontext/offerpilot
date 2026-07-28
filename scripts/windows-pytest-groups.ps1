Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Invoke-CheckedPytest {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    Write-Host "== $Label =="
    $output = & uv run pytest @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $output | ForEach-Object { Write-Host $_ }
        throw "$Label failed with exit code $exitCode"
    }
    return @($output)
}

function Get-NodeIds {
    param([Parameter(Mandatory = $true)][object[]]$Output)

    return @(
        $Output | ForEach-Object {
            $line = ([string]$_).Trim()
            if ($line -match '^(tests[\\/].+::.+)$') {
                $Matches[1].Replace('/', '\\')
            }
        } | Where-Object { $_ }
    )
}

function Get-SkipsFromJunit {
    param([Parameter(Mandatory = $true)][string]$Path)

    [xml]$report = Get-Content -LiteralPath $Path -Raw -Encoding utf8
    foreach ($testcase in @($report.testsuites.testsuite.testcase)) {
        $skipped = $testcase.skipped
        if ($null -eq $skipped) {
            continue
        }
        $module = [string]$testcase.classname
        if ($module -notmatch '^tests\.(.+)$') {
            throw "cannot map JUnit testcase module to a pytest node: $module"
        }
        $relativeModule = $Matches[1].Replace('.', '\')
        [pscustomobject]@{
            NodeId = "tests\$relativeModule.py::$([string]$testcase.name)"
            Reason = [string]$skipped.message
        }
    }
}

$allowedSymlinkSkipReason = [Text.Encoding]::UTF8.GetString(
    [Convert]::FromBase64String('5b2T5YmN546v5aKD5rKh5pyJ5Yib5bu656ym5Y+36ZO+5o6l55qE5p2D6ZmQ')
)
$allowedSkipReasons = @{
    'tests\test_knowledge_ingest_integrity.py::test_failed_commit_cleanup_does_not_follow_symlink' = $allowedSymlinkSkipReason
    'tests\test_knowledge_reset.py::test_cli_rejects_knowledge_root_symlink_with_external_sentinels' = $allowedSymlinkSkipReason
    'tests\test_knowledge_reset.py::test_cli_rejects_legacy_reset_root_symlink_with_external_sentinels' = $allowedSymlinkSkipReason
    'tests\test_knowledge_reset.py::test_cli_does_not_follow_nested_escape_symlink' = $allowedSymlinkSkipReason
}

$collection = Invoke-CheckedPytest @('--collect-only', '-q', '--disable-warnings') 'collect full test manifest'
$allNodeIdsRaw = @(Get-NodeIds $collection)
$duplicateManifest = @($allNodeIdsRaw | Group-Object | Where-Object Count -gt 1)
if ($duplicateManifest.Count -gt 0) {
    throw "pytest full manifest contains duplicate node ids: $($duplicateManifest.Name -join ', ')"
}
$allNodeIds = @($allNodeIdsRaw | Sort-Object)
if ($allNodeIds.Count -eq 0) {
    throw 'pytest collection returned no test node ids'
}

$testFiles = @(
    Get-ChildItem -Path (Join-Path $repoRoot 'tests') -Recurse -File -Filter 'test_*.py' |
        ForEach-Object { $_.FullName.Substring($repoRoot.Length + 1) } |
        ForEach-Object { $_.Replace('/', '\\') } |
        Sort-Object -Unique
)

$groups = [ordered]@{
    agent = @($testFiles | Where-Object { $_ -match '\\test_(ai_|chat_|config|settings_api|auth_api|cli)'} )
    domain = @($testFiles | Where-Object { $_ -match '\\test_(applications|events|notes|resumes|offers|questions|jd_resume_ai_api|module_workflows)' })
    knowledge = @($testFiles | Where-Object { $_ -match '\\test_(knowledge|ki)' })
    proposals = @($testFiles | Where-Object { $_ -match '\\test_(opportunity_fit|interview|material|evidence|smoke)' })
    misc = @()
}

$assigned = @($groups.Values | ForEach-Object { $_ })
$groups.misc = @($testFiles | Where-Object { $assigned -notcontains $_ })
$assigned = @($groups.Values | ForEach-Object { $_ })
$unassigned = @($testFiles | Where-Object { $assigned -notcontains $_ })
if ($unassigned.Count -gt 0) {
    throw "unassigned test files: $($unassigned -join ', ')"
}

$manifestPath = Join-Path $env:TEMP ("offerpilot-pytest-manifest-{0}.txt" -f [guid]::NewGuid())
$allNodeIds | Set-Content -Path $manifestPath -Encoding utf8
try {
    $groupNodeIds = [System.Collections.Generic.List[string]]::new()
    foreach ($group in $groups.GetEnumerator()) {
        if ($group.Value.Count -eq 0) {
            continue
        }
        $groupCollection = Invoke-CheckedPytest -Arguments (@('--collect-only', '-q', '--disable-warnings') + @($group.Value)) -Label "$($group.Key) collect"
        $nodesRaw = @(Get-NodeIds $groupCollection)
        $duplicateGroup = @($nodesRaw | Group-Object | Where-Object Count -gt 1)
        if ($duplicateGroup.Count -gt 0) {
            throw "$($group.Key) contains duplicate collected node ids: $($duplicateGroup.Name -join ', ')"
        }
        $nodes = @($nodesRaw | Sort-Object)
        $nodes | ForEach-Object { $groupNodeIds.Add($_) }
        $junitPath = Join-Path $env:TEMP ("offerpilot-pytest-$($group.Key)-{0}.xml" -f [guid]::NewGuid())
        $runArguments = @('-q', '-rs', '--disable-warnings', "--junitxml=$junitPath") + @($group.Value)
        $null = Invoke-CheckedPytest -Arguments $runArguments -Label $group.Key
        if (-not (Test-Path -LiteralPath $junitPath)) {
            throw "$($group.Key) did not produce the required JUnit report"
        }
        try {
            foreach ($skip in @(Get-SkipsFromJunit -Path $junitPath)) {
                if (-not $allowedSkipReasons.ContainsKey($skip.NodeId)) {
                    throw "$($group.Key) has an unexpected skipped test: $($skip.NodeId)"
                }
                if ($allowedSkipReasons[$skip.NodeId] -ne $skip.Reason) {
                    throw "$($group.Key) has an unexpected skip reason for $($skip.NodeId): $($skip.Reason)"
                }
                Write-Host "allowed skip: $($skip.NodeId) [$($skip.Reason)]"
            }
        }
        finally {
            Remove-Item -LiteralPath $junitPath -Force -ErrorAction SilentlyContinue
        }
    }

    $duplicateGrouped = @($groupNodeIds | Group-Object | Where-Object Count -gt 1)
    if ($duplicateGrouped.Count -gt 0) {
        throw "pytest group coverage contains duplicate node ids: $($duplicateGrouped.Name -join ', ')"
    }
    $expected = @($allNodeIds | Sort-Object)
    $actual = @($groupNodeIds | Sort-Object)
    $expectedText = $expected -join "`n"
    $actualText = $actual -join "`n"
    if ($expectedText -ne $actualText) {
        throw "pytest group coverage differs from the locked manifest; see $manifestPath"
    }
    Write-Host "All pytest groups passed; collected node coverage matches $($expected.Count) tests."
}
finally {
    Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
}
