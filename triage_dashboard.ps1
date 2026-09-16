param(
    [string]$JobDirectory
)

$ErrorActionPreference = "Stop"
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$dashboardPath = Join-Path $PSScriptRoot "triage_dashboard.py"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Не найдено Python-окружение. Сначала запустите setup_mcp.cmd"
}
$localToken = [Environment]::GetEnvironmentVariable("SVACER_LOCAL_MCP_TOKEN", "User")
if (-not [string]::IsNullOrWhiteSpace($localToken)) {
    $env:SVACER_LOCAL_MCP_TOKEN = $localToken
}
try {
    $arguments = @($dashboardPath)
    if (-not [string]::IsNullOrWhiteSpace($JobDirectory)) {
        $arguments += @("--job", $JobDirectory)
    }
    & $pythonPath @arguments
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:SVACER_LOCAL_MCP_TOKEN -ErrorAction SilentlyContinue
}
