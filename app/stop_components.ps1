[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Svacer", "Analyze", "All")]
    [string]$Mode,
    [switch]$Elevated
)

$ErrorActionPreference = "Stop"
$mcpPort = 8002
$toolDirectory = Split-Path -Parent $PSScriptRoot

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedSelf {
    Write-Host "Для остановки процесса требуется подтверждение Windows (UAC)." -ForegroundColor Yellow
    $arguments = @(
        "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $PSCommandPath + '"'),
        "-Mode", $Mode,
        "-Elevated"
    )
    $process = Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -PassThru `
        -WorkingDirectory $PSScriptRoot -ArgumentList $arguments
    exit $process.ExitCode
}

function Get-ProcessSnapshot {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
}

function Stop-ProcessTree {
    param([Parameter(Mandatory = $true)][int]$RootProcessId)

    $snapshot = Get-ProcessSnapshot
    $children = @{}
    foreach ($process in $snapshot) {
        $parentId = [int]$process.ParentProcessId
        if (-not $children.ContainsKey($parentId)) {
            $children[$parentId] = New-Object System.Collections.Generic.List[int]
        }
        $children[$parentId].Add([int]$process.ProcessId)
    }

    $ordered = New-Object System.Collections.Generic.List[int]
    $pending = New-Object System.Collections.Generic.Stack[int]
    $pending.Push($RootProcessId)
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        $ordered.Add($current)
        if ($children.ContainsKey($current)) {
            foreach ($child in $children[$current]) {
                $pending.Push($child)
            }
        }
    }

    for ($index = $ordered.Count - 1; $index -ge 0; $index--) {
        Stop-Process -Id $ordered[$index] -Force -ErrorAction SilentlyContinue
    }
}

function Stop-SvacerServer {
    $listeners = @(Get-NetTCPConnection -LocalPort $mcpPort -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        Write-Host "Svacer MCP уже остановлен: порт $mcpPort свободен." -ForegroundColor Green
        return
    }

    $snapshot = Get-ProcessSnapshot
    $byId = @{}
    foreach ($process in $snapshot) {
        $byId[[int]$process.ProcessId] = $process
    }

    foreach ($listener in ($listeners | Sort-Object OwningProcess -Unique)) {
        $listenerId = [int]$listener.OwningProcess
        $process = $byId[$listenerId]
        if ($null -eq $process) {
            throw "Не удалось определить процесс PID $listenerId на порту $mcpPort."
        }

        $name = [string]$process.Name
        $commandLine = [string]$process.CommandLine
        $recognized = (
            $name -in @("python.exe", "pythonw.exe") -or
            $commandLine -match "(?i)(start_svacer_http|svacer[_-]mcp)"
        )
        if (-not $recognized) {
            throw "Порт $mcpPort занят неизвестной программой $name (PID $listenerId). Она не остановлена."
        }

        $rootId = $listenerId
        $current = $process
        while ($null -ne $current) {
            $parentId = [int]$current.ParentProcessId
            $parent = $byId[$parentId]
            if ($null -eq $parent -or [string]$parent.Name -notin @("python.exe", "pythonw.exe")) {
                break
            }
            $rootId = $parentId
            $current = $parent
        }

        Write-Host "Останавливается Svacer MCP (PID $rootId)..." -ForegroundColor Yellow
        Stop-ProcessTree -RootProcessId $rootId
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ((Get-NetTCPConnection -LocalPort $mcpPort -State Listen -ErrorAction SilentlyContinue) -and
           [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if (Get-NetTCPConnection -LocalPort $mcpPort -State Listen -ErrorAction SilentlyContinue) {
        throw "Порт $mcpPort не освободился после остановки Svacer MCP."
    }
    Write-Host "Svacer MCP остановлен." -ForegroundColor Green
}

function Stop-LocalAnalysis {
    $resultsRoot = Join-Path $toolDirectory "RESULTS"
    $pausedJobs = 0
    if (Test-Path -LiteralPath $resultsRoot) {
        foreach ($job in (Get-ChildItem -LiteralPath $resultsRoot -Directory -ErrorAction SilentlyContinue)) {
            if (-not (Test-Path -LiteralPath (Join-Path $job.FullName "job.json"))) {
                continue
            }
            $control = [ordered]@{
                pause_requested = $true
                updated_at = [DateTime]::UtcNow.ToString("o")
                source = "STOP ANALYZE.cmd"
            }
            $control | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $job.FullName "control.json") -Encoding UTF8
            $pausedJobs++
        }
    }

    $scriptNames = @("triage_dashboard.py", "triage_queue.py")
    $stopped = 0
    foreach ($process in (Get-ProcessSnapshot)) {
        $commandLine = [string]$process.CommandLine
        if ([string]::IsNullOrWhiteSpace($commandLine)) {
            continue
        }
        $belongsToTool = $commandLine -like "*$toolDirectory*"
        $isAnalysisProcess = $false
        foreach ($scriptName in $scriptNames) {
            if ($commandLine -like "*$scriptName*") {
                $isAnalysisProcess = $true
                break
            }
        }
        if ($belongsToTool -and $isAnalysisProcess) {
            Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
            $stopped++
        }
    }

    Write-Host "Локальная очередь поставлена на паузу: задач $pausedJobs." -ForegroundColor Green
    Write-Host "Остановлено локальных процессов анализа/панели: $stopped." -ForegroundColor Green
    Write-Host "Уже выполняемую партию Codex останови кнопкой Stop в самой задаче." -ForegroundColor Yellow
}

try {
    if ($Mode -in @("Svacer", "All") -and -not (Test-IsAdministrator) -and -not $Elevated) {
        Invoke-ElevatedSelf
    }
    if ($Mode -in @("Analyze", "All")) {
        Stop-LocalAnalysis
    }
    if ($Mode -in @("Svacer", "All")) {
        Stop-SvacerServer
    }
    exit 0
}
catch {
    Write-Host "Ошибка остановки: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
