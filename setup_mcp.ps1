$ErrorActionPreference = "Stop"

$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$repoPath = Join-Path $PSScriptRoot "svacer-mcp"

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "Команда codex не найдена. Запусти скрипт из терминала Codex или установи Codex CLI."
}
Write-Host "Доступность подагентов проверяется в самой задаче Codex; без них анализ идёт последовательно."
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git не найден в PATH. Установите Git и откройте новое окно терминала."
}
if (-not (Test-Path -LiteralPath $repoPath)) {
    throw "Не найден репозиторий svacer-mcp: $repoPath"
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host "Создаю локальное Python-окружение..."
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source -m venv (Join-Path $PSScriptRoot ".venv")
    }
    if (-not (Test-Path -LiteralPath $pythonPath) -and $pyCommand) {
        & $pyCommand.Source -3 -m venv (Join-Path $PSScriptRoot ".venv")
    }
    if (-not $pythonCommand -and -not $pyCommand) {
        throw "Python не найден. Установи Python 3.10 или новее и повтори setup_mcp.cmd"
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonPath)) {
        throw "Не удалось создать локальное Python-окружение"
    }
}

& $pythonPath -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Нужен Python 3.10 или новее. Старое .venv автоматически не удаляется." }
Write-Host "Устанавливаю или обновляю svacer-mcp..."
# Текущая версия коннектора использует FastMCP API из MCP SDK 1.x.
# Явная верхняя граница защищает установку от несовместимого MCP SDK 2.x.
& $pythonPath -m pip install --disable-pip-version-check "mcp>=1,<2" -e $repoPath
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить svacer-mcp" }

$localToken = [Environment]::GetEnvironmentVariable("SVACER_LOCAL_MCP_TOKEN", "User")
if ([string]::IsNullOrWhiteSpace($localToken)) {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    $localToken = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    [Environment]::SetEnvironmentVariable("SVACER_LOCAL_MCP_TOKEN", $localToken, "User")
}
$env:SVACER_LOCAL_MCP_TOKEN = $localToken

# Windows PowerShell 5.1 can promote native stderr into a terminating error.
$savedErrorPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & codex mcp get svacer *> $null
    $existingMcp = ($LASTEXITCODE -eq 0)
}
finally { $ErrorActionPreference = $savedErrorPreference }
if ($existingMcp) {
    & codex mcp remove svacer
    if ($LASTEXITCODE -ne 0) { throw "Не удалось удалить старую настройку MCP" }
}

& codex mcp add svacer --url "http://127.0.0.1:8002/mcp" --bearer-token-env-var SVACER_LOCAL_MCP_TOKEN
if ($LASTEXITCODE -ne 0) { throw "Не удалось зарегистрировать Svacer MCP в Codex" }

Write-Host ""
Write-Host "Svacer MCP зарегистрирован."
Write-Host "Теперь один раз запусти start_svacer_http.cmd и войди в Svacer."
Write-Host "Оставь открывшееся окно сервера запущенным на время разметки."
Write-Host "После этого полностью перезапусти Codex Desktop."
