param(
    [string]$JobDirectory
)

$ErrorActionPreference = "Stop"
$toolDirectory = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $toolDirectory ".venv\Scripts\pythonw.exe"
$guiPath = Join-Path $PSScriptRoot "triage_gui.py"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Не найдено Python-окружение. Откройте START.cmd и выберите пункт 6"
}
$localToken = [Environment]::GetEnvironmentVariable("SVACER_LOCAL_MCP_TOKEN", "User")
if (-not [string]::IsNullOrWhiteSpace($localToken)) {
    $env:SVACER_LOCAL_MCP_TOKEN = $localToken
}
try {
    $arguments = "`"$guiPath`""
    if (-not [string]::IsNullOrWhiteSpace($JobDirectory)) {
        $arguments += " --job `"$JobDirectory`""
    }
    Start-Process -FilePath $pythonPath -ArgumentList $arguments
}
finally {
    Remove-Item Env:SVACER_LOCAL_MCP_TOKEN -ErrorAction SilentlyContinue
}
