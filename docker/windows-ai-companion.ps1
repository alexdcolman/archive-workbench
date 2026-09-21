param(
    [Parameter(Mandatory = $true)]
    [string]$BridgePathFile
)

$ErrorActionPreference = "Stop"
$candidates = New-Object System.Collections.Generic.List[string]
if (-not [string]::IsNullOrWhiteSpace($env:ARCHIVE_WORKBENCH_AI_EXECUTABLE)) {
    $candidates.Add($env:ARCHIVE_WORKBENCH_AI_EXECUTABLE)
}
if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Archive Workbench AI\aw-ai.exe"))
}
try {
    $fromPath = (Get-Command aw-ai -ErrorAction Stop).Source
    if ($fromPath) { $candidates.Add($fromPath) }
}
catch { }

$executable = $null
foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $executable = $candidate
        break
    }
}
if ($null -eq $executable) {
    exit 2
}

$bridgeRoot = (& $executable bridge path 2>$null | Select-Object -First 1)
if ([string]::IsNullOrWhiteSpace($bridgeRoot)) {
    exit 3
}
& $executable bridge start --root $bridgeRoot *> $null
if ($LASTEXITCODE -ne 0) {
    exit 4
}
[System.IO.File]::WriteAllText($BridgePathFile, [string]$bridgeRoot, (New-Object System.Text.UTF8Encoding($false)))
exit 0
