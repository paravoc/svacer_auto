$ErrorActionPreference = "Stop"

$port = 8002
$stopScript = Join-Path $PSScriptRoot "stop_components.ps1"

try {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        Write-Host "Порт $port занят старым MCP. Выполняется автоматическая остановка..." -ForegroundColor Yellow
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $stopScript -Mode Svacer
        if ($LASTEXITCODE -ne 0) {
            throw "Не удалось автоматически освободить порт $port. Используй STOP SVACER.cmd."
        }
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
