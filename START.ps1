$ErrorActionPreference = "Stop"

function Show-Menu {
    Clear-Host
    Write-Host "SVACER ГОСТ TRIAGE" -ForegroundColor Cyan
    Write-Host "==================" -ForegroundColor DarkGray
    Write-Host "1  Новый триаж" -ForegroundColor Green
    Write-Host "2  Открыть панель последней задачи" -ForegroundColor Green
    Write-Host "3  Подключить или перезапустить Svacer" -ForegroundColor Yellow
    Write-Host "4  Открыть папку результатов" -ForegroundColor Cyan
    Write-Host "5  Открыть краткую инструкцию" -ForegroundColor Cyan
    Write-Host "6  Первичная установка на этом компьютере" -ForegroundColor Yellow
    Write-Host "0  Выход" -ForegroundColor DarkGray
    Write-Host ""
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Выберите действие"
    switch ($choice) {
        "1" {
            & (Join-Path $PSScriptRoot "new_triage_job.ps1")
            if ($LASTEXITCODE -ne 0) { Read-Host "Нажмите Enter" }
        }
        "2" {
            & (Join-Path $PSScriptRoot "triage_dashboard.ps1")
        }
        "3" {
            & (Join-Path $PSScriptRoot "restart_svacer_http.ps1")
            Start-Sleep -Seconds 1
        }
        "4" {
            $results = Join-Path $PSScriptRoot "RESULTS"
            if (-not (Test-Path -LiteralPath $results)) {
                New-Item -ItemType Directory -Path $results | Out-Null
            }
            Start-Process explorer.exe -ArgumentList @($results)
        }
        "5" {
            Start-Process notepad.exe -ArgumentList @((Join-Path $PSScriptRoot "README.md"))
        }
        "6" {
            & (Join-Path $PSScriptRoot "setup_mcp.ps1")
            Read-Host "Установка завершена. Нажмите Enter"
        }
        "0" { exit 0 }
        default {
            Write-Host "Неизвестный пункт: $choice" -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
