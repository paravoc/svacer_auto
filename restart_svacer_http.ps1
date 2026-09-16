$ErrorActionPreference = "Stop"

$port = 8002
$serverScript = (Join-Path $PSScriptRoot "start_svacer_http.py")
$launcher = Join-Path $PSScriptRoot "start_svacer_http.cmd"

try {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        $commandLine = [string]$process.CommandLine
        if ($commandLine -notlike "*$serverScript*") {
            throw "Порт $port занят другой программой (PID $($listener.OwningProcess)). Она не была остановлена."
        }
        Write-Host "Останавливается прежний локальный MCP..." -ForegroundColor Yellow
        Stop-Process -Id $listener.OwningProcess -Force
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while ((Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) -and
           [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Порт $port не освободился после остановки прежнего MCP."
    }

    Write-Host "Сейчас откроется форма входа в Svacer." -ForegroundColor Cyan
    Write-Host "После входа оставьте новое окно MCP открытым." -ForegroundColor Cyan
    $serverLauncher = Join-Path $PSScriptRoot "start_svacer_http.ps1"
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $PSScriptRoot -ArgumentList @(
        "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $serverLauncher
    )
}
catch {
    Write-Host ""
    Write-Host "Не удалось переподключить Svacer:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "Нажмите Enter для закрытия"
    exit 1
}
