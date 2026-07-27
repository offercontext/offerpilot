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

$collection = Invoke-CheckedPytest @('--collect-only', '-q', '--disable-warnings') 'collect full test manifest'
$allNodeIds = @(Get-NodeIds $collection | Sort-Object -Unique)
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
        $groupCollection = Invoke-CheckedPytest @('--collect-only', '-q', '--disable-warnings') $group.Key
        $nodes = @(Get-NodeIds $groupCollection | Sort-Object -Unique)
        $nodes | ForEach-Object { $groupNodeIds.Add($_) }
        $null = Invoke-CheckedPytest @('-q', '--disable-warnings') $group.Value $group.Key
    }

    $expected = @($allNodeIds | Sort-Object -Unique)
    $actual = @($groupNodeIds | Sort-Object -Unique)
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
